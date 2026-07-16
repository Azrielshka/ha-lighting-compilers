# -*- coding: utf-8 -*-
"""
Генератор пространств (Areas) и этажей (Floors) для Home Assistant.

Шаг офлайновый: к HA не подключается, только готовит файл-задание.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import generate_areas as AREAS
import normalize_excel as N
from conftest import base_rows, make_book
from scripts._lib.canon import floor_area_id, floor_area_name, floor_icon, floor_name
from scripts._lib.filters import Filters
from scripts._lib.normalized import load_dataset


def is_floor_area(area: dict) -> bool:
    """Area этажа или помещения. Отличаем по канону, а не по виду имени."""
    return "floor" in area and area["name"] == floor_area_name(area["floor"])


def rooms(areas: list) -> list:
    """Только Areas помещений — Areas этажей идут отдельно, в конце."""
    return [a for a in areas if not is_floor_area(a)]


def floor_areas(areas: list) -> list:
    return [a for a in areas if is_floor_area(a)]


def _rows_two_floors():
    return [
        {
            "Этаж": 1, "Название помещения": "103_Вестибюль", "Тип помещения": "Korridor",
            "Шина DALI": 1, "Группа": "103_1", "Лампа": "1.1.1",
            "Датчик": "1.1.1", "Панель": "None",
        },
        {
            "Этаж": 2, "Название помещения": "205_Актовый зал", "Тип помещения": "Zal",
            "Шина DALI": 1, "Группа": "205_1", "Лампа": "2.1.1",
            "Датчик": "None", "Панель": "2.1.1",
        },
    ]


@pytest.fixture
def layer(tmp_path) -> Path:
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", _rows_two_floors()), out)
    return out


@pytest.fixture
def object_layer(tmp_path, object_example) -> Path:
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


def _build(layer: Path, filters: Filters = None) -> dict:
    df = load_dataset(layer, "spaces")
    return AREAS.build_payload(df, filters or Filters())


def _yaml(layer: Path, filters: Filters = None) -> dict:
    payload = _build(layer, filters)
    return yaml.safe_load(AREAS.render_yaml(payload))


# ============================================================
# ИМЕНА
# ============================================================

def test_area_name_comes_straight_from_table(layer):
    """
    Имя Area — русское название из таблицы, без посредников.

    Auto-area-HA восстанавливал имя из транслита по словарю: room_slug
    "103_vestibiul" превращался в "103_Vestibiul", потому что слова не было
    в словаре. Настоящее имя всё это время лежало в колонке «Название
    помещения» — его и берём.
    """
    payload = _build(layer)
    names = [a["name"] for a in rooms(payload["areas"])]

    assert names == ["103_Вестибюль", "205_Актовый зал"]


def test_transliteration_goes_to_aliases(layer):
    """Транслит не выбрасываем: по нему в HA тоже должно искаться."""
    payload = _build(layer)

    assert payload["areas"][0]["aliases"] == ["103_vestibiul"]


def test_no_latin_in_area_names(object_layer):
    """Регрессия: в имени Area не должно оказаться транслита."""
    payload = _build(object_layer)

    for area in payload["areas"]:
        assert not any("a" <= ch.lower() <= "z" for ch in area["name"]), area["name"]


# ============================================================
# ЭТАЖИ
# ============================================================

def test_floors_are_created_from_spaces(layer):
    payload = _build(layer)

    assert payload["floors"] == [
        {"level": 1, "name": "1 этаж", "icon": "mdi:home-floor-1"},
        {"level": 2, "name": "2 этаж", "icon": "mdi:home-floor-2"},
    ]


def test_areas_are_bound_to_floors(layer):
    payload = _build(layer)

    assert payload["areas"][0]["floor"] == 1
    assert payload["areas"][1]["floor"] == 2


def test_floor_appears_once_per_level(object_layer):
    """Этаж создаётся один раз, сколько бы помещений на нём ни было.

    В фикстуре 7 помещений на первом этаже и 1 на втором → ровно два Floor,
    а не восемь.
    """
    payload = _build(object_layer)

    assert [f["level"] for f in payload["floors"]] == [1, 2]
    assert len(rooms(payload["areas"])) == 8
    # на каждый этаж — своя Area, для карточки type: area на Главной
    assert [a["name"] for a in floor_areas(payload["areas"])] == [
        "Весь 1 этаж", "Весь 2 этаж",
    ]


def test_floors_sorted_by_level(tmp_path):
    rows = [
        {
            "Этаж": 3, "Название помещения": "301_Класс", "Тип помещения": "Class",
            "Шина DALI": 1, "Группа": "301_1", "Лампа": "3.1.1",
            "Датчик": "None", "Панель": "None",
        },
        {
            "Этаж": 1, "Название помещения": "101_Класс", "Тип помещения": "Class",
            "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.1",
            "Датчик": "None", "Панель": "None",
        },
    ]
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)

    payload = _build(out)
    assert [f["level"] for f in payload["floors"]] == [1, 3]


@pytest.mark.parametrize("level,icon", [
    (0, "mdi:home-floor-0"),
    (1, "mdi:home-floor-1"),
    (3, "mdi:home-floor-3"),
    (4, "mdi:home-floor-a"),   # у MDI пронумерованы только 1–3
    (12, "mdi:home-floor-a"),
    (-1, "mdi:home-floor-negative-1"),
])
def test_floor_icons(level, icon):
    assert floor_icon(level) == icon


def test_floor_name():
    assert floor_name(1) == "1 этаж"
    assert floor_name(12) == "12 этаж"


# ============================================================
# YAML
# ============================================================

def test_yaml_is_parseable(object_layer):
    doc = _yaml(object_layer)

    assert len(rooms(doc["areas"])) == 8
    assert len(floor_areas(doc["areas"])) == 2
    assert len(doc["floors"]) == 2
    assert doc["areas"][0]["name"] == "101_Тамбур"


def test_yaml_keeps_table_order(object_layer):
    """Порядок пространств — как в таблице: наладчик сверяет YAML со своим Excel."""
    doc = _yaml(object_layer)
    names = [a["name"] for a in rooms(doc["areas"])]

    assert names[0] == "101_Тамбур"
    assert names[-1] == "208_Входной тамбур"

    # Areas этажей идут ПОСЛЕ помещений и порядок таблицы не сдвигают
    all_names = [a["name"] for a in doc["areas"]]
    assert all_names[-2:] == ["Весь 1 этаж", "Весь 2 этаж"]


def test_empty_result_is_commented(object_layer):
    """Пустой YAML выглядит как поломка — оставляем объяснение."""
    df = load_dataset(object_layer, "spaces")
    payload = AREAS.build_payload(df, Filters(spaces=["нет такого"]))
    text = AREAS.render_yaml(payload)

    assert text.startswith("#")
    assert yaml.safe_load(text) is None


# ============================================================
# ФИЛЬТРЫ И КРАЯ
# ============================================================

def test_filters_apply(object_layer):
    doc = _yaml(object_layer, Filters(spaces=["102_Тамбур"]))

    assert [a["name"] for a in rooms(doc["areas"])] == ["102_Тамбур"]
    # этаж помещения остался в выборке — значит и Area этажа создаётся
    assert [a["name"] for a in floor_areas(doc["areas"])] == ["Весь 1 этаж"]


def test_space_without_type_still_becomes_area(tmp_path):
    """Тип помещения на Areas не влияет: помещение существует физически."""
    rows = base_rows()
    del rows[0]["Тип помещения"]

    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)

    payload = _build(out)
    assert payload["areas"][0]["name"] == "101_Тамбур"


# ============================================================
# CLI
# ============================================================

def test_cli_writes_yaml(monkeypatch, tmp_path, object_layer):
    out = tmp_path / "areas.yaml"
    monkeypatch.setattr("sys.argv", [
        "generate_areas.py", "--normalized", str(object_layer), "--out", str(out),
    ])

    assert AREAS.main() == 0

    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(doc["areas"]) == 10   # 8 помещений + 2 Areas этажей


def test_cli_without_normalized_layer(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", [
        "generate_areas.py", "--normalized", str(tmp_path / "нет"),
        "--out", str(tmp_path / "o.yaml"),
    ])

    assert AREAS.main() == 2


def test_generator_makes_no_network_calls(monkeypatch, tmp_path, object_layer):
    """
    Шаг офлайновый. Если сюда когда-нибудь заедет обращение к HA —
    этот тест упадёт.
    """
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("генератор не должен ходить в сеть")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    out = tmp_path / "areas.yaml"
    monkeypatch.setattr("sys.argv", [
        "generate_areas.py", "--normalized", str(object_layer), "--out", str(out),
    ])

    assert AREAS.main() == 0


# ============================================================
# AREA НА ЭТАЖ
# ============================================================

def test_floor_area_id_comes_from_name():
    """area_id генерирует HA из имени — задать его напрямую нельзя.

    Та же ловушка, что с группами света (unique_id ≠ entity_id): карточка
    `type: area` на Главной ссылается на area_id, и если вычислять его иначе,
    чем это сделает HA, карточка будет пустой.
    """
    from scripts._lib.naming import slugify_room

    assert floor_area_name(1) == "Весь 1 этаж"
    assert floor_area_id(1) == "ves_1_etazh"
    for level in (1, 2, 3, 12):
        assert floor_area_id(level) == slugify_room(floor_area_name(level))


def test_floor_area_is_not_confused_with_floor_or_light_group():
    """На этаж приходятся три разные сущности — их имена не должны совпадать."""
    from scripts._lib.canon import floor_group_name, floor_light_entity

    assert floor_area_name(1) != floor_name(1)              # Area ≠ Floor
    assert floor_area_name(1) != floor_group_name(1)        # Area ≠ группа света
    assert floor_area_id(1) not in floor_light_entity(1)    # ves_1_etazh ≠ ves_1_i_etazh


def test_floor_area_bound_to_its_floor(object_layer):
    payload = _build(object_layer)

    for area in floor_areas(payload["areas"]):
        assert area["name"] == floor_area_name(area["floor"])
        assert area["aliases"] == [floor_area_id(area["floor"])]


def test_no_floor_areas_without_floors(tmp_path):
    """Нет этажей — нет и Areas этажей: пустышек не плодим."""
    rows = base_rows()
    del rows[0]["Этаж"]

    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)

    payload = _build(out)
    assert payload["floors"] == []
    assert floor_areas(payload["areas"]) == []
