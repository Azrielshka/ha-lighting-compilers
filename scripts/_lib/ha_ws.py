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

    @property
    def is_empty(self) -> bool:
        return not self.floors_to_create and not self.areas_to_create


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
) -> AreasPlan:
    """
    Что создавать, а что уже есть.

    Идемпотентность: ключ сравнения — ИМЯ. Оно уникально за счёт номера
    помещения («103_Вестибюль»), поэтому повторный деплой ничего не дублирует.

    existing_* приходят из HA. В dry-run без подключения передаём пустые
    списки: тогда план покажет всё как «создать».
    """
    plan = AreasPlan()

    have_floors = set(existing_floors)
    for floor in payload.get("floors", []):
        if floor["name"] in have_floors:
            plan.floors_existing.append(floor["name"])
        else:
            plan.floors_to_create.append(floor)

    have_areas = set(existing_areas)
    for area in payload.get("areas", []):
        if area["name"] in have_areas:
            plan.areas_existing.append(area["name"])
        else:
            plan.areas_to_create.append(area)

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

    async def _fetch_existing_async(self) -> Dict[str, List[str]]:
        await self._connect()
        try:
            areas = await self._command({"type": "config/area_registry/list"})
            floors = await self._command({"type": "config/floor_registry/list"})

            return {
                "areas": [a.get("name", "") for a in areas],
                "floors": [f.get("name", "") for f in floors],
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

                await self._command(payload)
                stats["areas_created"] += 1

            return stats
        finally:
            await self._close()

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
