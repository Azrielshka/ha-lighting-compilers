# -*- coding: utf-8 -*-
"""
ha_ws.py
Пространства (Areas) и этажи (Floors) Home Assistant через WebSocket API.

Areas и Floors — не YAML-конфигурация, а записи в реестрах. Файлами их не
создать: только по WebSocket, с long-lived токеном.

⚠ ЗАГОТОВКА. Сетевая часть НЕ РЕАЛИЗОВАНА — за основу возьмётся
`Auto-area-HA/areacreator/ha_client.py` (обкатан в бою, создал 12 Areas).

Что здесь РЕАЛИЗОВАНО и работает: разбор задания и вычисление диффа —
что создать, что пропустить. Это чистая логика, она тестируется без сети,
и именно она отвечает за идемпотентность: повторный деплой ничего не дублирует.

Протокол (из Auto-area-HA):
    ws(s)://<host>/api/websocket
    -> auth_required
    <- {"type": "auth", "access_token": ...}
    -> auth_ok
    <- {"id": N, "type": "config/area_registry/list"}
    <- {"id": N, "type": "config/area_registry/create", "name": ..., "aliases": [...]}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import yaml


class WSNotConfigured(RuntimeError):
    """Не хватает параметров подключения."""


class WSTransportNotImplemented(NotImplementedError):
    """Транспорт ещё не подключён — честно отказываемся вместо тихой заглушки."""


@dataclass(frozen=True)
class WSConfig:
    """Параметры подключения к Home Assistant."""

    base_url: str
    token: str

    @property
    def ws_url(self) -> str:
        """http -> ws, https -> wss, путь /api/websocket."""
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, "/api/websocket", "", "", ""))

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
        return f"{self.base_url} (токен {self.token[:8]}…)" if self.token else self.base_url


# ============================================================
# ЗАДАНИЕ И ДИФФ — реализованы, сети не требуют
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

    existing_* приходят из HA (config/area_registry/list). В dry-run без
    подключения передаём пустые списки: тогда план покажет всё как «создать».
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
# КЛИЕНТ — заготовка
# ============================================================

class HAWebSocketClient:
    """
    Клиент WebSocket API Home Assistant.

    ⚠ ЗАГОТОВКА: сетевые методы бросают WSTransportNotImplemented.
    За основу возьмётся Auto-area-HA/areacreator/ha_client.py.
    """

    def __init__(self, config: WSConfig):
        self.config = config

    def connect(self) -> None:
        raise WSTransportNotImplemented(
            "WebSocket-транспорт ещё не подключён.\n"
            "   Пространства придётся создать вручную — deploy.py --dry-run\n"
            "   покажет, какие именно."
        )

    def list_areas(self) -> List[Dict]:
        raise WSTransportNotImplemented("WebSocket-транспорт ещё не подключён")

    def list_floors(self) -> List[Dict]:
        raise WSTransportNotImplemented("WebSocket-транспорт ещё не подключён")

    def create_floor(self, name: str, level: int, icon: Optional[str] = None) -> Dict:
        raise WSTransportNotImplemented("WebSocket-транспорт ещё не подключён")

    def create_area(self, name: str, aliases: List[str],
                    floor_id: Optional[str] = None) -> Dict:
        raise WSTransportNotImplemented("WebSocket-транспорт ещё не подключён")

    def close(self) -> None:
        pass
