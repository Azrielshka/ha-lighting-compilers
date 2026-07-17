# -*- coding: utf-8 -*-
"""
WebSocket-транспорт: конфиг, дифф, привязка этажей, TLS.

Сетевая часть на живом HA этого проекта НЕ проверена: снаружи он только через
Traefik с самоподписанным сертификатом, а наладчик ходит локально. Команды и
имена полей — из документации HA, проверяются на объекте живьём.
Здесь — то, что можно проверить без сети.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts._lib.ha_ws import (
    AreasPlan,
    HAWebSocketClient,
    WSConfig,
    WSNotConfigured,
    WSTransportError,
    build_areas_plan,
    load_areas_file,
)


# ============================================================
# КОНФИГ
# ============================================================

def test_ws_url_derivation():
    assert WSConfig("http://ha:8123", "t").ws_url == "ws://ha:8123/api/websocket"
    assert WSConfig("https://ha.example", "t").ws_url == "wss://ha.example/api/websocket"


def test_is_tls():
    assert WSConfig("https://ha", "t").is_tls
    assert not WSConfig("http://ha:8123", "t").is_tls


def test_validation():
    assert WSConfig("", "").validate()
    assert WSConfig("http://ha:8123", "").validate()
    assert WSConfig("http://ha:8123", "token").validate() == []


def test_token_is_not_printed_in_full():
    described = WSConfig("http://ha:8123", "supersecrettoken12345").describe()
    assert "supersecrettoken12345" not in described


# ============================================================
# TLS
# ============================================================

def test_plain_http_needs_no_ssl_context():
    """Локальный http:// — TLS нет вовсе, наладчику ничего проверять не нужно."""
    client = HAWebSocketClient(WSConfig("http://ha:8123", "t"))
    assert client._ssl_context() is None


def test_https_verifies_by_default():
    """
    По умолчанию сертификат проверяется. True означает: websockets возьмёт
    штатный проверяющий контекст.
    """
    client = HAWebSocketClient(WSConfig("https://ha", "t"))
    assert client._ssl_context() is True


def test_insecure_disables_verification():
    """
    Отключение проверки — ТОЛЬКО по явному insecure=True (для самоподписанного
    https). Молча этого не делаем: тихо отключённая проверка сертификата —
    дыра, которую потом никто не заметит.
    """
    import ssl

    client = HAWebSocketClient(WSConfig("https://ha", "t", insecure=True))
    ctx = client._ssl_context()

    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_insecure_noted_in_describe():
    described = WSConfig("https://ha", "token123", insecure=True).describe()
    assert "без проверки" in described


def test_insecure_ignored_for_plain_http():
    """insecure бессмысленен для http:// — не пугаем словами про TLS."""
    described = WSConfig("http://ha:8123", "token123", insecure=True).describe()
    assert "без проверки" not in described


# ============================================================
# ДИФФ И ИДЕМПОТЕНТНОСТЬ
# ============================================================

@pytest.fixture
def payload() -> dict:
    return {
        "floors": [
            {"level": 1, "name": "1 этаж", "icon": "mdi:home-floor-1"},
            {"level": 2, "name": "2 этаж", "icon": "mdi:home-floor-2"},
        ],
        "areas": [
            {"name": "101_Тамбур", "aliases": ["101_tambur"], "floor": 1},
            {"name": "205_Зал", "aliases": ["205_zal"], "floor": 2},
        ],
    }


def test_everything_on_empty_ha(payload):
    plan = build_areas_plan(payload, existing_areas=[], existing_floors=[])

    assert len(plan.floors_to_create) == 2
    assert len(plan.areas_to_create) == 2
    assert not plan.is_empty


def test_idempotent(payload):
    """Повторный деплой не дублирует: ключ — имя."""
    plan = build_areas_plan(
        payload,
        existing_areas=["101_Тамбур", "205_Зал"],
        existing_floors=["1 этаж", "2 этаж"],
    )

    assert plan.is_empty
    assert set(plan.areas_existing) == {"101_Тамбур", "205_Зал"}


def test_partial(payload):
    plan = build_areas_plan(
        payload,
        existing_areas=["101_Тамбур"],
        existing_floors=["1 этаж"],
    )

    assert [f["name"] for f in plan.floors_to_create] == ["2 этаж"]
    assert [a["name"] for a in plan.areas_to_create] == ["205_Зал"]


def test_load_areas_file(tmp_path):
    path = tmp_path / "areas.yaml"
    path.write_text(
        "floors:\n  - level: 1\n    name: \"1 этаж\"\n    icon: mdi:home-floor-1\n"
        "areas:\n  - name: \"101_Тамбур\"\n    aliases: [\"101_tambur\"]\n    floor: 1\n",
        encoding="utf-8",
    )

    payload = load_areas_file(path)
    assert len(payload["floors"]) == 1
    assert len(payload["areas"]) == 1


def test_load_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="generate_areas.py"):
        load_areas_file(tmp_path / "нет.yaml")


def test_load_empty_file(tmp_path):
    path = tmp_path / "areas.yaml"
    path.write_text("# нет данных\n", encoding="utf-8")

    assert load_areas_file(path) == {"floors": [], "areas": []}


# ============================================================
# ПРИВЯЗКА ЭТАЖ → ПРОСТРАНСТВО (на моке транспорта)
# ============================================================

class FakeWS:
    """
    Мок WebSocket: отвечает на команды реестров, записывает отправленное.
    Позволяет проверить логику apply() без сети — порядок, привязку floor_id,
    идемпотентность существующих этажей.
    """

    def __init__(self, existing_floors=None):
        # existing_floors: список {"floor_id", "level", "name"}
        self._floors = list(existing_floors or [])
        self._areas = []
        self.sent = []
        self._next_floor = 100

    async def send(self, raw):
        import json
        self.sent.append(json.loads(raw))

    async def recv(self):
        import json
        cmd = self.sent[-1]
        cmd_id = cmd["id"]
        t = cmd["type"]

        if t == "config/floor_registry/list":
            result = self._floors
        elif t == "config/area_registry/list":
            result = self._areas
        elif t == "config/floor_registry/create":
            self._next_floor += 1
            fid = f"floor_{self._next_floor}"
            self._floors.append({"floor_id": fid, "level": cmd["level"], "name": cmd["name"]})
            result = {"floor_id": fid}
        elif t == "config/area_registry/create":
            self._areas.append(cmd)
            result = {"area_id": f"area_{len(self._areas)}"}
        else:
            result = None

        return json.dumps({"id": cmd_id, "type": "result", "success": True, "result": result})

    async def close(self):
        pass


def _client_with(fake: FakeWS) -> HAWebSocketClient:
    client = HAWebSocketClient(WSConfig("http://ha:8123", "t"))

    async def fake_connect():
        client._ws = fake

    client._connect = fake_connect
    return client


def test_apply_creates_floors_before_areas():
    """
    Порядок обязателен: floor_id этажа выдаёт HA при создании, и он нужен,
    чтобы привязать к нему пространство.
    """
    fake = FakeWS()
    client = _client_with(fake)

    plan = AreasPlan(
        floors_to_create=[{"level": 1, "name": "1 этаж", "icon": "mdi:home-floor-1"}],
        areas_to_create=[{"name": "101_Тамбур", "aliases": ["101_tambur"], "floor": 1}],
    )

    stats = client.apply(plan)

    assert stats == {"floors_created": 1, "areas_created": 1}

    creates = [c for c in fake.sent if c["type"].endswith("/create")]
    assert creates[0]["type"] == "config/floor_registry/create"
    assert creates[1]["type"] == "config/area_registry/create"

    # Пространство привязано к floor_id созданного этажа.
    assert creates[1]["floor_id"] == "floor_101"


def test_apply_binds_area_to_existing_floor():
    """
    Повторный деплой: этаж уже есть, новое пространство привязывается к его
    floor_id, а не создаёт этаж заново.
    """
    fake = FakeWS(existing_floors=[{"floor_id": "floor_7", "level": 2, "name": "2 этаж"}])
    client = _client_with(fake)

    plan = AreasPlan(
        floors_to_create=[],  # этаж уже существует
        areas_to_create=[{"name": "205_Зал", "aliases": [], "floor": 2}],
    )

    client.apply(plan)

    area_create = [c for c in fake.sent if c["type"] == "config/area_registry/create"][0]
    assert area_create["floor_id"] == "floor_7"


def test_apply_area_without_floor():
    """Помещение без этажа создаётся без floor_id, а не падает."""
    fake = FakeWS()
    client = _client_with(fake)

    plan = AreasPlan(
        areas_to_create=[{"name": "Без этажа", "aliases": []}],
    )

    client.apply(plan)

    area_create = [c for c in fake.sent if c["type"] == "config/area_registry/create"][0]
    assert "floor_id" not in area_create


def test_command_raises_on_ha_error():
    """
    Ошибку от HA пробрасываем с текстом: если поле команды названо не так,
    это будет видно сразу, а не превратится в молчаливый пропуск.
    """
    import asyncio
    import json

    class FailingWS:
        def __init__(self):
            self.sent = []

        async def send(self, raw):
            self.sent.append(json.loads(raw))

        async def recv(self):
            return json.dumps({
                "id": self.sent[-1]["id"], "type": "result", "success": False,
                "error": {"code": "invalid_format", "message": "unknown field 'level'"},
            })

        async def close(self):
            pass

    client = HAWebSocketClient(WSConfig("http://ha:8123", "t"))

    async def run():
        client._ws = FailingWS()
        await client._command({"type": "config/floor_registry/create"})

    with pytest.raises(WSTransportError, match="unknown field"):
        asyncio.run(run())


# ============================================================
# ОТКАЗЫ
# ============================================================

def test_unreachable_host():
    client = HAWebSocketClient(WSConfig("http://127.0.0.1:1", "t"))

    with pytest.raises(WSTransportError, match="не могу подключиться"):
        client.fetch_existing()


def test_bad_config_refused():
    client = HAWebSocketClient(WSConfig("", ""))

    with pytest.raises(WSNotConfigured):
        client.fetch_existing()
