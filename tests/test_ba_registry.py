# -*- coding: utf-8 -*-
"""
Разметка реестра HA для Оркестратора здания: метки и назначение света в Areas.

Контракт — docs/internal/contract-ha-lighting-compilers.md. Проверяем три
вещи, каждая из которых при поломке молчит:

  • инвариант «ровно одна световая сущность в Area» — иначе каждая лампа
    получит по две команды и трафик на шине DALI удвоится;
  • идемпотентность разметки — повторный деплой не должен переназначать
    и, главное, не должен сносить метки, навешенные владельцем руками;
  • отсутствующая сущность — не ошибка, а нормальный первый деплой.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts._lib.canon import (
    BA_FLOOR_AREA_LABEL,
    BA_TYPE_LABEL_PREFIX,
    ALLOWED_SPACE_TYPES,
    ba_labels,
    ba_type_label,
    floor_light_entity,
    general_light_entity,
    tech_light_entity,
)
from scripts._lib.ha_ws import (
    AreasPlan,
    HAWebSocketClient,
    WSConfig,
    build_areas_plan,
)


# ============================================================
# КАНОН МЕТОК
# ============================================================

def test_label_names_are_ascii():
    """
    label_id HA выводит из имени через slugify. От кириллицы он был бы
    непредсказуем, а имена жёстко зашиты в Оркестраторе — разъедутся молча.
    """
    for label in ba_labels():
        assert label.isascii(), f"метка {label} не ASCII"
        assert label == label.lower()
        assert " " not in label


def test_ba_labels_cover_all_space_types():
    """Метка типа нужна каждому типу помещения: профиль задаётся по типу."""
    labels = set(ba_labels())

    assert BA_FLOOR_AREA_LABEL in labels
    for space_type in ALLOWED_SPACE_TYPES:
        assert ba_type_label(space_type) in labels


def test_ba_labels_order_is_stable():
    """Порядок фиксирован, иначе дифф деплоя пляшет между запусками."""
    assert ba_labels() == ba_labels()
    assert ba_labels()[0] == BA_FLOOR_AREA_LABEL


def test_floor_label_is_not_a_type_label():
    """
    Агрегатная Area не должна попасть под профиль типа помещения: она не
    помещение, а контейнер этажа.
    """
    assert not BA_FLOOR_AREA_LABEL.startswith(BA_TYPE_LABEL_PREFIX)


# ============================================================
# ЗАДАНИЕ: generate_areas.py
# ============================================================

@pytest.fixture(scope="module")
def areas_doc() -> dict:
    """Реальный areas.yaml, собранный генератором из тестовой таблицы."""
    path = Path(__file__).resolve().parent.parent / "data" / "areas" / "areas.yaml"
    if not path.exists():
        pytest.skip("нет data/areas/areas.yaml — сначала generate_areas.py")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _room_areas(doc: dict) -> list:
    return [a for a in doc["areas"] if BA_FLOOR_AREA_LABEL not in (a.get("labels") or [])]


def _floor_areas(doc: dict) -> list:
    return [a for a in doc["areas"] if BA_FLOOR_AREA_LABEL in (a.get("labels") or [])]


def test_every_area_has_exactly_one_light(areas_doc):
    """Тот самый инвариант. Поле одно — значит и сущность одна."""
    for area in areas_doc["areas"]:
        light = area.get("light")
        assert light, f"у Area {area['name']} нет света"
        assert isinstance(light, str)
        assert light.startswith("light.")


def test_room_area_gets_general_light(areas_doc):
    """
    В Area помещения — общий свет помещения, а не зонная группа и не лампа.
    Зонные группы (light.<room>_<n>) и лампы (light.l_*) в Areas не попадают
    никогда: их назначение удвоило бы команды на шине.
    """
    for area in _room_areas(areas_doc):
        assert area["light"].endswith("_obshchii"), area["name"]


def test_floor_area_gets_floor_light(areas_doc):
    """В агрегатной Area этажа — групповой светильник этажа."""
    for area in _floor_areas(areas_doc):
        level = area["floor"]
        assert area["light"] == floor_light_entity(level)


def test_tech_group_is_never_assigned(areas_doc):
    """
    Решение владельца 2026-07-22: группа тех.помещений остаётся БЕЗ Area.
    Положить её в Area этажа нельзя — там уже лежит группа этажа, и инвариант
    «одна световая сущность» сломается.

    ⚠ Тест намеренно строгий: без него «починка» вида «а давайте и тех.
    помещения назначим» пройдёт незамеченной.
    """
    assigned = {a["light"] for a in areas_doc["areas"]}
    floors = {f["level"] for f in areas_doc["floors"]}

    for floor in floors:
        assert tech_light_entity(floor) not in assigned


def test_room_areas_carry_exactly_one_type_label(areas_doc):
    """У помещения ровно одна метка типа — профиль не должен быть двойственным."""
    for area in _room_areas(areas_doc):
        labels = area.get("labels") or []
        type_labels = [lab for lab in labels if lab.startswith(BA_TYPE_LABEL_PREFIX)]
        assert len(type_labels) == 1, f"{area['name']}: {labels}"


def test_floor_areas_carry_no_type_label(areas_doc):
    """Агрегатная Area несёт только ba_floor_area."""
    for area in _floor_areas(areas_doc):
        assert area.get("labels") == [BA_FLOOR_AREA_LABEL]


def test_lights_are_unique_across_areas(areas_doc):
    """
    Одна сущность не может лежать в двух Areas — HA этого и не позволит,
    но задание с дублем означало бы ошибку в билдерах канона.
    """
    lights = [a["light"] for a in areas_doc["areas"]]
    assert len(lights) == len(set(lights))


def test_general_light_matches_canon(areas_doc):
    """Сущность строится билдером канона, а не из unique_id группы."""
    for area in _room_areas(areas_doc):
        slug = (area.get("aliases") or [None])[0]
        if slug:
            assert area["light"] == general_light_entity(slug)


# ============================================================
# ДИФФ РАЗМЕТКИ — чистая логика, без сети
# ============================================================

@pytest.fixture
def payload() -> dict:
    return {
        "floors": [{"level": 1, "name": "1 этаж", "icon": "mdi:home-floor-1"}],
        "areas": [
            {
                "name": "101_Тамбур",
                "aliases": ["101_tambur"],
                "floor": 1,
                "light": "light.101_tambur_obshchii",
                "labels": ["ba_type_special"],
            },
            {
                "name": "Весь 1 этаж",
                "aliases": ["ves_1_etazh"],
                "floor": 1,
                "light": "light.ves_1_i_etazh",
                "labels": [BA_FLOOR_AREA_LABEL],
            },
        ],
    }


def test_labels_planned_once(payload):
    """Метка нужна многим Areas, а создаётся один раз."""
    payload["areas"].append({
        "name": "102_Тамбур",
        "light": "light.102_tambur_obshchii",
        "labels": ["ba_type_special"],
    })

    plan = build_areas_plan(payload, existing_areas=[], existing_floors=[])

    assert plan.labels_to_create.count("ba_type_special") == 1


def test_existing_labels_not_recreated(payload):
    plan = build_areas_plan(
        payload,
        existing_areas=[],
        existing_floors=[],
        existing_labels=["ba_type_special", BA_FLOOR_AREA_LABEL],
    )

    assert plan.labels_to_create == []


def test_area_already_labeled_is_skipped(payload):
    """Повторный деплой не переставляет уже стоящие метки."""
    plan = build_areas_plan(
        payload,
        existing_areas=["101_Тамбур", "Весь 1 этаж"],
        existing_floors=["1 этаж"],
        existing_labels=["ba_type_special", BA_FLOOR_AREA_LABEL],
        existing_area_labels={
            "101_Тамбур": ["ba_type_special"],
            "Весь 1 этаж": [BA_FLOOR_AREA_LABEL],
        },
        entity_areas={
            "light.101_tambur_obshchii": "101_Тамбур",
            "light.ves_1_i_etazh": "Весь 1 этаж",
        },
    )

    assert plan.areas_to_label == []
    assert plan.assignments == []
    assert plan.is_empty


def test_foreign_labels_do_not_block_ours(payload):
    """
    У Area может быть метка владельца. Наша к ней добавляется, а не заменяет
    её — в плане это видно как «поставить недостающие».
    """
    plan = build_areas_plan(
        payload,
        existing_areas=["101_Тамбур"],
        existing_floors=["1 этаж"],
        existing_labels=["ba_type_special"],
        existing_area_labels={"101_Тамбур": ["этаж_переделан"]},
    )

    item = [i for i in plan.areas_to_label if i["area"] == "101_Тамбур"][0]
    assert item["labels"] == ["ba_type_special"]


def test_entity_in_wrong_area_is_reassigned(payload):
    plan = build_areas_plan(
        payload,
        existing_areas=["101_Тамбур", "Весь 1 этаж"],
        existing_floors=["1 этаж"],
        entity_areas={
            "light.101_tambur_obshchii": "205_Зал",     # не туда
            "light.ves_1_i_etazh": "Весь 1 этаж",
        },
    )

    assert plan.assignments == [
        {"entity": "light.101_tambur_obshchii", "area": "101_Тамбур"}
    ]


def test_missing_entity_is_not_an_error(payload):
    """
    Первый деплой: пакеты групп только положены на диск, HA не перезапущен,
    сущностей в реестре нет. Назначать нечего — но и падать не за что.
    """
    plan = build_areas_plan(
        payload,
        existing_areas=["101_Тамбур", "Весь 1 этаж"],
        existing_floors=["1 этаж"],
        entity_areas={},   # реестр прочитан, света в нём нет
    )

    assert plan.assignments == []
    assert set(plan.entities_missing) == {
        "light.101_tambur_obshchii",
        "light.ves_1_i_etazh",
    }


def test_unknown_registry_plans_everything(payload):
    """
    entity_areas=None — «мы не спрашивали реестр» (dry-run). Тогда планируем
    все назначения и НИЧЕГО не объявляем отсутствующим: пугать наладчика
    списком «сущность не найдена» там, где мы не смотрели, нельзя.
    """
    plan = build_areas_plan(payload, existing_areas=[], existing_floors=[])

    assert len(plan.assignments) == 2
    assert plan.entities_missing == []


def test_marks_alone_are_not_empty(payload):
    """
    ⚠ Ключевой тест второго прохода: Areas созданы, а свет ещё не назначен.
    Сочти план пустым — деплой молча пропустит назначения, и ради чего тогда
    его повторяли после рестарта HA.
    """
    plan = build_areas_plan(
        payload,
        existing_areas=["101_Тамбур", "Весь 1 этаж"],
        existing_floors=["1 этаж"],
        existing_labels=["ba_type_special", BA_FLOOR_AREA_LABEL],
        existing_area_labels={
            "101_Тамбур": ["ba_type_special"],
            "Весь 1 этаж": [BA_FLOOR_AREA_LABEL],
        },
        entity_areas={
            "light.101_tambur_obshchii": None,
            "light.ves_1_i_etazh": None,
        },
    )

    assert not plan.is_empty
    assert len(plan.assignments) == 2


def test_area_without_light_is_fine(payload):
    """Поле необязательное: Area без света просто не размечается."""
    payload["areas"].append({"name": "Без света", "labels": []})

    plan = build_areas_plan(payload, existing_areas=[], existing_floors=[])

    assert all(a["area"] != "Без света" for a in plan.assignments)


# ============================================================
# ПРИМЕНЕНИЕ — на моке транспорта
# ============================================================

class FakeWS:
    """
    Мок WebSocket с реестрами меток и сущностей. Отвечает как HA и хранит
    состояние, чтобы можно было проверить именно результат, а не порядок
    отправленных команд.
    """

    def __init__(self, areas=None, labels=None, entities=None):
        self._floors = []
        self._areas = list(areas or [])       # {"area_id", "name", "labels"}
        self._labels = list(labels or [])     # {"label_id", "name"}
        self._entities = list(entities or []) # {"entity_id", "area_id"}
        self.sent = []
        self._seq = 0

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        cmd = self.sent[-1]
        t = cmd["type"]
        result = None

        if t == "config/floor_registry/list":
            result = self._floors
        elif t == "config/area_registry/list":
            result = self._areas
        elif t == "config/label_registry/list":
            result = self._labels
        elif t == "config/entity_registry/list":
            result = self._entities
        elif t == "config/floor_registry/create":
            self._seq += 1
            fid = f"floor_{self._seq}"
            self._floors.append({"floor_id": fid, "level": cmd["level"], "name": cmd["name"]})
            result = {"floor_id": fid}
        elif t == "config/area_registry/create":
            self._seq += 1
            aid = f"area_{self._seq}"
            self._areas.append({"area_id": aid, "name": cmd["name"], "labels": []})
            result = {"area_id": aid, "name": cmd["name"]}
        elif t == "config/label_registry/create":
            self._seq += 1
            lid = f"label_{self._seq}"
            self._labels.append({"label_id": lid, "name": cmd["name"]})
            result = {"label_id": lid, "name": cmd["name"]}
        elif t == "config/area_registry/update":
            for area in self._areas:
                if area["area_id"] == cmd["area_id"]:
                    area["labels"] = list(cmd["labels"])
                    result = area
        elif t == "config/entity_registry/update":
            for ent in self._entities:
                if ent["entity_id"] == cmd["entity_id"]:
                    ent["area_id"] = cmd["area_id"]
                    result = ent

        return json.dumps({"id": cmd["id"], "type": "result", "success": True, "result": result})

    async def close(self):
        pass

    # --- удобные проверки ---

    def label_names(self):
        return [lab["name"] for lab in self._labels]

    def labels_of(self, area_name):
        by_id = {lab["label_id"]: lab["name"] for lab in self._labels}
        for area in self._areas:
            if area["name"] == area_name:
                return [by_id.get(lid, lid) for lid in area.get("labels") or []]
        return []

    def area_of(self, entity_id):
        by_id = {a["area_id"]: a["name"] for a in self._areas}
        for ent in self._entities:
            if ent["entity_id"] == entity_id:
                return by_id.get(ent.get("area_id"))
        return None


def _client_with(fake: FakeWS) -> HAWebSocketClient:
    client = HAWebSocketClient(WSConfig("http://ha:8123", "t"))

    async def fake_connect():
        client._ws = fake

    client._connect = fake_connect
    return client


def test_apply_creates_labels_and_assigns_light():
    fake = FakeWS(entities=[{"entity_id": "light.101_tambur_obshchii", "area_id": None}])
    client = _client_with(fake)

    plan = AreasPlan(
        areas_to_create=[{"name": "101_Тамбур", "aliases": []}],
        labels_to_create=["ba_type_special"],
        areas_to_label=[{"area": "101_Тамбур", "labels": ["ba_type_special"]}],
        assignments=[{"entity": "light.101_tambur_obshchii", "area": "101_Тамбур"}],
    )

    stats = client.apply(plan)

    assert stats["labels_created"] == 1
    assert stats["areas_labeled"] == 1
    assert stats["entities_assigned"] == 1

    assert fake.labels_of("101_Тамбур") == ["ba_type_special"]
    assert fake.area_of("light.101_tambur_obshchii") == "101_Тамбур"


def test_apply_uses_existing_area_on_repeat_deploy():
    """
    Второй проход после рестарта HA: Area создана прошлым разом, id её мы не
    помним — берём из реестра. Без этого назначение молча не состоялось бы.
    """
    fake = FakeWS(
        areas=[{"area_id": "area_77", "name": "101_Тамбур", "labels": []}],
        entities=[{"entity_id": "light.101_tambur_obshchii", "area_id": None}],
    )
    client = _client_with(fake)

    plan = AreasPlan(
        assignments=[{"entity": "light.101_tambur_obshchii", "area": "101_Тамбур"}],
    )

    stats = client.apply(plan)

    assert stats["entities_assigned"] == 1
    assert fake.area_of("light.101_tambur_obshchii") == "101_Тамбур"


def test_apply_keeps_foreign_labels():
    """
    ⚠ area_registry/update заменяет СПИСОК меток целиком. Значит наша метка
    обязана дописываться к существующим: иначе деплой снесёт всё, что владелец
    навесил в интерфейсе HA, и заметит он это нескоро.
    """
    fake = FakeWS(
        areas=[{"area_id": "area_5", "name": "101_Тамбур", "labels": ["label_own"]}],
        labels=[{"label_id": "label_own", "name": "переделан"}],
    )
    client = _client_with(fake)

    plan = AreasPlan(
        labels_to_create=["ba_type_special"],
        areas_to_label=[{"area": "101_Тамбур", "labels": ["ba_type_special"]}],
    )

    client.apply(plan)

    assert set(fake.labels_of("101_Тамбур")) == {"переделан", "ba_type_special"}


def test_apply_does_not_recreate_existing_label():
    """Метка уже есть в реестре — переиспользуем, а не плодим тёзку."""
    fake = FakeWS(
        areas=[{"area_id": "area_5", "name": "101_Тамбур", "labels": []}],
        labels=[{"label_id": "lbl_1", "name": "ba_type_special"}],
    )
    client = _client_with(fake)

    plan = AreasPlan(
        areas_to_label=[{"area": "101_Тамбур", "labels": ["ba_type_special"]}],
    )

    client.apply(plan)

    assert fake.label_names().count("ba_type_special") == 1
    assert fake.labels_of("101_Тамбур") == ["ba_type_special"]


def test_apply_is_idempotent_on_labels():
    """Повторный прогон того же плана не шлёт лишний update."""
    fake = FakeWS(
        areas=[{"area_id": "area_5", "name": "101_Тамбур", "labels": ["lbl_1"]}],
        labels=[{"label_id": "lbl_1", "name": "ba_type_special"}],
    )
    client = _client_with(fake)

    plan = AreasPlan(
        areas_to_label=[{"area": "101_Тамбур", "labels": ["ba_type_special"]}],
    )

    stats = client.apply(plan)

    assert stats["areas_labeled"] == 0
    updates = [c for c in fake.sent if c["type"] == "config/area_registry/update"]
    assert updates == []


def test_fetch_existing_resolves_names():
    """
    Наружу отдаём имена, а не id: дифф не должен зависеть от того, как HA
    нарезал идентификаторы.
    """
    fake = FakeWS(
        areas=[{"area_id": "area_5", "name": "101_Тамбур", "labels": ["lbl_1"]}],
        labels=[{"label_id": "lbl_1", "name": "ba_type_special"}],
        entities=[{"entity_id": "light.101_tambur_obshchii", "area_id": "area_5"}],
    )
    client = _client_with(fake)

    existing = client.fetch_existing()

    assert existing["areas"] == ["101_Тамбур"]
    assert existing["labels"] == {"ba_type_special": "lbl_1"}
    assert existing["area_labels"] == {"101_Тамбур": ["ba_type_special"]}
    assert existing["entity_areas"] == {"light.101_tambur_obshchii": "101_Тамбур"}
