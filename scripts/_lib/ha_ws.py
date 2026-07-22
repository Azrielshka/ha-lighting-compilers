# -*- coding: utf-8 -*-
"""
ha_ws.py
Пространства (Areas) и этажи (Floors) Home Assistant через WebSocket API.

Areas и Floors — не YAML-конфигурация, а записи в реестрах. Файлами их не
создать: только по WebSocket, с long-lived токеном.

Транспорт взят из Auto-area-HA/areacreator/ha_client.py (создал 12 Areas на
живом HA — значит area_registry рабочий). Добавлены этажи и привязка Area→Floor.

⚠ Сетевая часть НЕ проверена на живом HA этого проекта: снаружи он только через
Traefik с самоподписанным сертификатом, а наладчик всё равно ходит локально
по http://. Команды реестров и имена полей взяты из документации HA. Ошибку от
HA пробрасываем с текстом — если поле названо не так, это будет сразу видно.

Разделение внутри модуля намеренное:
    - разбор задания и ДИФФ — чистая логика, тестируется без сети;
      она же отвечает за идемпотентность
    - клиент — сеть, проверяется только на живом HA

Протокол:
    ws(s)://<host>/api/websocket
    →  {"type": "auth_required"}
    ←  {"type": "auth", "access_token": ...}
    →  {"type": "auth_ok"}
    ←  {"id": N, "type": "config/floor_registry/list"}
    ←  {"id": N, "type": "config/floor_registry/create", "name", "level", "icon"}
    ←  {"id": N, "type": "config/area_registry/create", "name", "aliases", "floor_id"}

⚠ TLS: проверка сертификата ВКЛЮЧЕНА по умолчанию. Отключается явно
(insecure=True) — для объектов с самоподписанным https. Наладчику на
локальном http:// это не нужно.
"""

from __future__ import annotations

import asyncio
import json
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import yaml

try:
    import websockets
except ImportError:  # без websockets недоступен только деплой Areas
    websockets = None  # type: ignore

TIMEOUT = 15.0


def _area_id_of(created: object) -> str:
    """
    Вытащить area_id из ответа на создание Area.

    HA отвечает объектом Area целиком; на всякий случай принимаем и голую
    строку — цена проверки нулевая, а промах здесь молча оставил бы Area без
    меток и без света.
    """
    if isinstance(created, dict):
        return created.get("area_id", "")
    return str(created or "")


class WSNotConfigured(RuntimeError):
    """Не хватает параметров подключения."""


class WSTransportError(RuntimeError):
    """Не удалось подключиться или выполнить команду."""


@dataclass(frozen=True)
class WSConfig:
    """Параметры подключения к Home Assistant."""

    base_url: str
    token: str

    # Отключить проверку TLS-сертификата. Нужно для объектов с самоподписанным
    # https (Traefik default cert). Наладчику на локальном http:// не требуется.
    insecure: bool = False

    @property
    def ws_url(self) -> str:
        """http -> ws, https -> wss, путь /api/websocket."""
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, "/api/websocket", "", "", ""))

    @property
    def is_tls(self) -> bool:
        return urlparse(self.base_url).scheme == "https"

    def validate(self) -> List[str]:
        problems: List[str] = []

        if not self.base_url.strip():
            problems.append("не задан адрес Home Assistant")
        elif not urlparse(self.base_url).netloc:
            problems.append(f"адрес не похож на URL: {self.base_url}")

        if not self.token.strip():
            problems.append("не задан long-lived token")

        return problems

    def describe(self) -> str:
        note = " [TLS без проверки]" if self.insecure and self.is_tls else ""
        head = f"{self.base_url} (токен {self.token[:8]}…)" if self.token else self.base_url
        return head + note


# ============================================================
# ЗАДАНИЕ И ДИФФ — чистая логика, сети не требует
# ============================================================

@dataclass
class AreasPlan:
    """Что сделать с реестрами HA."""

    floors_to_create: List[Dict] = field(default_factory=list)
    floors_existing: List[str] = field(default_factory=list)

    areas_to_create: List[Dict] = field(default_factory=list)
    areas_existing: List[str] = field(default_factory=list)

    # Разметка для Оркестратора здания (см. канон, раздел меток).
    labels_to_create: List[str] = field(default_factory=list)
    areas_to_label: List[Dict] = field(default_factory=list)   # {"area", "labels"}
    assignments: List[Dict] = field(default_factory=list)      # {"entity", "area"}

    # Сущности, которых ещё нет в реестре HA. Не ошибка: на первом деплое
    # групп света там нет, пакеты только положены на диск, а HA мы не
    # перезапускаем. Доедут вторым проходом после рестарта.
    entities_missing: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """
        ⚠ Разметка входит в проверку намеренно: без неё повторный деплой, где
        все Areas уже созданы, счёл бы работу выполненной и молча пропустил бы
        назначения — ровно тот второй проход, ради которого он и запускается.
        """
        return not (
            self.floors_to_create
            or self.areas_to_create
            or self.labels_to_create
            or self.areas_to_label
            or self.assignments
        )


def load_areas_file(path: Path) -> Dict:
    """Прочитать data/areas/areas.yaml — задание, собранное generate_areas.py."""
    if not path.exists():
        raise FileNotFoundError(f"не найден {path}\nСначала запустите generate_areas.py")

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))

    if not doc:
        return {"floors": [], "areas": []}

    return {
        "floors": list(doc.get("floors") or []),
        "areas": list(doc.get("areas") or []),
    }


def build_areas_plan(
    payload: Dict,
    existing_areas: List[str],
    existing_floors: List[str],
    existing_labels: Optional[List[str]] = None,
    existing_area_labels: Optional[Dict[str, List[str]]] = None,
    entity_areas: Optional[Dict[str, Optional[str]]] = None,
) -> AreasPlan:
    """
    Что создавать, а что уже есть.

    Идемпотентность: ключ сравнения — ИМЯ. Оно уникально за счёт номера
    помещения («103_Вестибюль»), поэтому повторный деплой ничего не дублирует.

    existing_* приходят из HA. В dry-run без подключения передаём пустые
    списки: тогда план покажет всё как «создать».

    Разметка для Оркестратора (метки и назначение света) сравнивается ПО
    ИМЕНАМ, а не по id: клиент разрешает id в имена ещё на чтении реестра.
    Так дифф остаётся чистой логикой и тестируется без сети — то же
    разделение, что у создания Areas.

    ⚠ entity_areas=None означает «мы не знаем состав реестра сущностей» —
    так бывает в dry-run. Тогда планируем ВСЕ назначения, ничего не считая
    отсутствующим: пугать наладчика списком «сущность не найдена» там, где
    мы просто не спрашивали, нельзя.
    """
    plan = AreasPlan()

    have_floors = set(existing_floors)
    for floor in payload.get("floors", []):
        if floor["name"] in have_floors:
            plan.floors_existing.append(floor["name"])
        else:
            plan.floors_to_create.append(floor)

    have_areas = set(existing_areas)
    have_labels = set(existing_labels or [])
    area_labels_now = existing_area_labels or {}

    wanted_labels: List[str] = []

    for area in payload.get("areas", []):
        name = area["name"]

        if name in have_areas:
            plan.areas_existing.append(name)
        else:
            plan.areas_to_create.append(area)

        # --- метки ---
        labels = list(area.get("labels") or [])
        for label in labels:
            if label not in have_labels and label not in wanted_labels:
                wanted_labels.append(label)

        # Ставим только недостающие: чужие метки, навешенные владельцем в
        # интерфейсе HA, трогать нельзя — их дополняем, а не заменяем.
        already = set(area_labels_now.get(name, []))
        missing = [lab for lab in labels if lab not in already]
        if missing:
            plan.areas_to_label.append({"area": name, "labels": missing})

        # --- назначение света ---
        entity = area.get("light")
        if not entity:
            continue

        if entity_areas is None:
            plan.assignments.append({"entity": entity, "area": name})
        elif entity not in entity_areas:
            plan.entities_missing.append(entity)
        elif entity_areas[entity] != name:
            plan.assignments.append({"entity": entity, "area": name})

    plan.labels_to_create = wanted_labels

    return plan


# ============================================================
# КЛИЕНТ
# ============================================================

class HAWebSocketClient:
    """
    Клиент WebSocket API Home Assistant.

    Синхронный снаружи (deploy.py синхронный), асинхронный внутри —
    websockets иначе не умеет.
    """

    def __init__(self, config: WSConfig):
        self.config = config
        self._ws = None
        self._id = 0

    # ------------------------------------------------------------
    # Публичный синхронный интерфейс
    # ------------------------------------------------------------

    def fetch_existing(self) -> Dict[str, List[str]]:
        """Имена того, что уже есть в реестрах, — для диффа."""
        return asyncio.run(self._fetch_existing_async())

    def apply(self, plan: AreasPlan) -> Dict[str, int]:
        """
        Создать недостающие этажи и пространства.

        Порядок важен: сначала этажи — их floor_id нужен, чтобы привязать
        пространства.
        """
        return asyncio.run(self._apply_async(plan))

    def fetch_dashboard_config(self, url_path: str) -> Dict:
        """Прочитать конфиг дашборда (storage-режим)."""
        return asyncio.run(self._fetch_dashboard_async(url_path))

    def save_dashboard_config(self, url_path: str, config: Dict) -> None:
        """
        Записать конфиг дашборда целиком.

        Команда перезаписывает ВЕСЬ дашборд, поэтому config должен быть уже
        слитым (свои views + чужие) — слияние делает ha_views.merge_views.
        Требует прав администратора: токен обычного пользователя получит отказ.
        """
        asyncio.run(self._save_dashboard_async(url_path, config))

    # ------------------------------------------------------------
    # Асинхронная реализация
    # ------------------------------------------------------------

    async def _fetch_existing_async(self) -> Dict:
        await self._connect()
        try:
            areas = await self._command({"type": "config/area_registry/list"})
            floors = await self._command({"type": "config/floor_registry/list"})
            labels = await self._command({"type": "config/label_registry/list"}) or []
            entities = await self._command({"type": "config/entity_registry/list"}) or []

            # id -> имя: наружу отдаём ИМЕНА, чтобы дифф не зависел от того,
            # как HA нарезал идентификаторы.
            label_name_by_id = {
                lab["label_id"]: lab.get("name", "") for lab in labels
            }
            area_name_by_id = {a["area_id"]: a.get("name", "") for a in areas}

            return {
                # Списки имён — форма, на которую опирается deploy.py.
                "areas": [a.get("name", "") for a in areas],
                "floors": [f.get("name", "") for f in floors],

                # Разметка для Оркестратора.
                "area_ids": {a.get("name", ""): a["area_id"] for a in areas},
                "labels": {lab.get("name", ""): lab["label_id"] for lab in labels},
                "area_labels": {
                    a.get("name", ""): [
                        label_name_by_id.get(lid, lid) for lid in (a.get("labels") or [])
                    ]
                    for a in areas
                },
                "entity_areas": {
                    e["entity_id"]: area_name_by_id.get(e.get("area_id"))
                    for e in entities
                },
            }
        finally:
            await self._close()

    async def _fetch_dashboard_async(self, url_path: str) -> Dict:
        await self._connect()
        try:
            return await self._command(
                {"type": "lovelace/config", "url_path": url_path}) or {}
        finally:
            await self._close()

    async def _save_dashboard_async(self, url_path: str, config: Dict) -> None:
        await self._connect()
        try:
            await self._command({
                "type": "lovelace/config/save",
                "url_path": url_path,
                "config": config,
            })
        finally:
            await self._close()

    async def _apply_async(self, plan: AreasPlan) -> Dict[str, int]:
        await self._connect()

        stats = {"floors_created": 0, "areas_created": 0}

        try:
            # Имя Area -> area_id. Пополняется созданными ниже; существующие
            # нужны для повторного деплоя, где создавать уже нечего, а
            # размечать есть что.
            area_id_by_name = await self._existing_area_ids()

            # Этажи первыми: их floor_id понадобится пространствам.
            # Сам id выдаёт Home Assistant при создании — заранее его не знать,
            # поэтому в areas.yaml лежит только уровень. Уже существующие этажи
            # тоже нужны в этой карте (повторный деплой).
            level_to_floor_id = await self._existing_floor_ids()

            for floor in plan.floors_to_create:
                created = await self._command({
                    "type": "config/floor_registry/create",
                    "name": floor["name"],
                    "level": floor["level"],
                    "icon": floor.get("icon"),
                })
                level_to_floor_id[int(floor["level"])] = created["floor_id"]
                stats["floors_created"] += 1

            for area in plan.areas_to_create:
                payload = {
                    "type": "config/area_registry/create",
                    "name": area["name"],
                    "aliases": area.get("aliases") or [],
                }

                level = area.get("floor")
                if level is not None and int(level) in level_to_floor_id:
                    payload["floor_id"] = level_to_floor_id[int(level)]

                created_area = await self._command(payload)
                stats["areas_created"] += 1

                # area_id выдаёт HA при создании. Раньше ответ отбрасывался —
                # теперь он нужен, чтобы навесить метки и назначить свет.
                if created_area:
                    area_id_by_name[area["name"]] = _area_id_of(created_area)

            stats.update(await self._apply_registry_marks(plan, area_id_by_name))

            return stats
        finally:
            await self._close()

    async def _apply_registry_marks(
        self,
        plan: AreasPlan,
        area_id_by_name: Dict[str, str],
    ) -> Dict[str, int]:
        """
        Разметка для Оркестратора: метки на Areas и назначение света.

        Отделено от создания Areas не для красоты: создание идемпотентно по
        имени и выполняется один раз на объект, а разметка догоняет реестр при
        каждом деплое — в том числе вторым проходом, когда группы света уже
        появились после рестарта HA.
        """
        stats = {"labels_created": 0, "areas_labeled": 0, "entities_assigned": 0}

        labels_now = await self._command({"type": "config/label_registry/list"}) or []
        label_id_by_name = {lab.get("name", ""): lab["label_id"] for lab in labels_now}

        # Метки существующих Areas забираем одним запросом: иначе на объекте в
        # 76 помещений вышло бы 76 обходов реестра.
        areas_now = await self._command({"type": "config/area_registry/list"}) or []
        labels_by_area_id = {
            a.get("area_id"): list(a.get("labels") or []) for a in areas_now
        }

        for name in plan.labels_to_create:
            created = await self._command({
                "type": "config/label_registry/create",
                "name": name,
            })
            if created:
                label_id_by_name[name] = created["label_id"]
                stats["labels_created"] += 1

        for item in plan.areas_to_label:
            area_id = area_id_by_name.get(item["area"])
            if not area_id:
                continue

            # Метки перечисляются ЦЕЛИКОМ: команда заменяет список, а не
            # дополняет его. Поэтому к недостающим добавляем те, что уже
            # стоят на Area, — иначе снесём метки, навешенные владельцем.
            current = labels_by_area_id.get(area_id, [])
            wanted = [label_id_by_name[n] for n in item["labels"] if n in label_id_by_name]
            merged = current + [lid for lid in wanted if lid not in current]

            if merged == current:
                continue

            await self._command({
                "type": "config/area_registry/update",
                "area_id": area_id,
                "labels": merged,
            })
            stats["areas_labeled"] += 1

        for item in plan.assignments:
            area_id = area_id_by_name.get(item["area"])
            if not area_id:
                continue

            await self._command({
                "type": "config/entity_registry/update",
                "entity_id": item["entity"],
                "area_id": area_id,
            })
            stats["entities_assigned"] += 1

        return stats

    async def _existing_area_ids(self) -> Dict[str, str]:
        """Имя Area -> area_id для тех, что уже есть в реестре.

        Нужно на повторном деплое: Areas созданы прошлым разом, id их мы не
        помним, а без него ни метку не навесить, ни свет не назначить.
        """
        areas = await self._command({"type": "config/area_registry/list"}) or []
        return {a.get("name", ""): a["area_id"] for a in areas if a.get("area_id")}

    async def _existing_floor_ids(self) -> Dict[int, str]:
        """
        Уровень этажа -> floor_id для этажей, которые уже были на HA.

        Нужно, чтобы при повторном деплое привязать новые пространства к
        существующему этажу, а не создавать его заново.
        """
        floors = await self._command({"type": "config/floor_registry/list"})

        result: Dict[int, str] = {}
        for floor in floors:
            level = floor.get("level")
            if level is not None:
                result[int(level)] = floor["floor_id"]

        return result

    # ------------------------------------------------------------
    # Транспорт
    # ------------------------------------------------------------

    def _ssl_context(self):
        """
        TLS-контекст. Проверка сертификата включена по умолчанию; отключаем
        только по явному insecure=True — для самоподписанных https.
        Для ws:// (локальный http) TLS нет вовсе, контекст не нужен.
        """
        if not self.config.is_tls:
            return None

        if not self.config.insecure:
            return True  # websockets возьмёт дефолтный проверяющий контекст

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def _connect(self) -> None:
        if websockets is None:
            raise WSTransportError(
                "не установлен websockets — переустановите зависимости:\n"
                "   pip install -r requirements.txt"
            )

        problems = self.config.validate()
        if problems:
            raise WSNotConfigured("; ".join(problems))

        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self.config.ws_url, ssl=self._ssl_context()),
                timeout=TIMEOUT,
            )
        except ssl.SSLCertVerificationError as exc:
            raise WSTransportError(
                f"сертификат HA не прошёл проверку: {exc}\n"
                f"   Если у объекта самоподписанный https — включите «insecure»\n"
                f"   (галочка в диалоге деплоя или флаг --insecure)."
            ) from exc
        except (OSError, asyncio.TimeoutError) as exc:
            raise WSTransportError(
                f"не могу подключиться к {self.config.ws_url} — {exc}"
            ) from exc

        hello = json.loads(await self._recv())
        if hello.get("type") != "auth_required":
            raise WSTransportError(
                f"неожиданный ответ при подключении: {hello.get('type')}"
            )

        await self._send({"type": "auth", "access_token": self.config.token})
        resp = json.loads(await self._recv())

        if resp.get("type") != "auth_ok":
            raise WSTransportError(
                "токен не принят. Создайте новый long-lived token:\n"
                "   HA → профиль → Security → Long-lived access tokens"
            )

    async def _command(self, payload: Dict):
        """Отправить команду и дождаться результата именно с нашим id."""
        self._id += 1
        cmd_id = self._id

        await self._send({"id": cmd_id, **payload})

        while True:
            msg = json.loads(await self._recv())

            if msg.get("id") != cmd_id or msg.get("type") != "result":
                continue  # события и чужие ответы игнорируем

            if not msg.get("success"):
                error = msg.get("error", {})
                # Текст ошибки HA пробрасываем как есть: если поле команды
                # названо не так, это будет видно сразу.
                raise WSTransportError(
                    f"{payload['type']} отклонена Home Assistant: "
                    f"{error.get('message', error)}"
                )

            return msg.get("result")

    async def _send(self, obj: Dict) -> None:
        await self._ws.send(json.dumps(obj))

    async def _recv(self) -> str:
        return await asyncio.wait_for(self._ws.recv(), timeout=TIMEOUT)

    async def _close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
