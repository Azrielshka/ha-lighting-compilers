# -*- coding: utf-8 -*-
"""
Генераторы групп света: зоны, общие группы помещений, группы этажей.

Ключевая проверка — согласованность иерархии:
    лампы -> зоны -> общая группа помещения -> группа этажа
Каждая ссылка должна вести на сущность, которую кто-то реально создал.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set

import pytest
import yaml

import generate_floor_groups as FLOOR
import generate_general_groups as GENERAL
import generate_lights_groups as LIGHTS
import normalize_excel as N
from conftest import base_rows, make_book
from scripts._lib.filters import Filters


# ============================================================
# ФИКСТУРЫ
# ============================================================

def _two_floors_rows():
    """Два этажа, четыре помещения, разные типы — включая коридор и зал."""
    return [
        # Этаж 1: коридор с двумя зонами
        {
            "Этаж": 1, "Название помещения": "101_Коридор", "Тип помещения": "Korridor",
            "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.1",
            "Датчик": "1.1.1", "Панель": "None",
        },
        {"Этаж": 1, "Шина DALI": 1, "Группа": "101_2", "Лампа": "1.1.2", "Датчик": "1.1.2"},

        # Этаж 1: класс
        {
            "Этаж": 1, "Название помещения": "102_Класс", "Тип помещения": "Class",
            "Шина DALI": 1, "Группа": "102_1", "Лампа": "1.1.3",
            "Датчик": "1.1.3", "Панель": "1.1.1",
        },

        # Этаж 2: зал без датчиков
        {
            "Этаж": 2, "Название помещения": "201_Зал", "Тип помещения": "Zal",
            "Шина DALI": 1, "Группа": "201_1", "Лампа": "2.1.1",
            "Датчик": "None", "Панель": "2.1.1",
        },

        # Этаж 2: помещение БЕЗ типа — должно попасть в группы света
        {
            "Этаж": 2, "Название помещения": "202_Склад",
            "Шина DALI": 1, "Группа": "202_1", "Лампа": "2.1.2",
            "Датчик": "None", "Панель": "None",
        },
    ]


@pytest.fixture
def layer(tmp_path) -> Path:
    """Нормализованный слой на таблице из двух этажей."""
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", _two_floors_rows()), out)
    return out


@pytest.fixture
def simple_layer(tmp_path) -> Path:
    """Минимальный слой: одно помещение, одна группа, две лампы."""
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "s.xlsx", base_rows()), out)
    return out


@pytest.fixture
def object_layer(tmp_path, object_example) -> Path:
    """Слой на реальной фикстуре v2."""
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


# ============================================================
# ПОМОЩНИКИ
# ============================================================

def _run(module, layer: Path, filters: Filters = None, **kw) -> dict:
    """Прогнать генератор и распарсить получившийся YAML."""
    from scripts._lib.normalized import load_dataset

    filters = filters or Filters()
    dataset = "groups" if module is LIGHTS else "spaces"
    df = load_dataset(layer, dataset)

    text = module.build_yaml(df, filters, **kw)
    return yaml.safe_load(text) or {}


def _groups(doc: dict, root_key: str) -> List[dict]:
    return doc.get(root_key, {}).get("light", []) if doc else []


def _created(doc: dict, root_key: str) -> Set[str]:
    """entity_id, которые этот YAML создаёт в Home Assistant."""
    return {f"light.{g['unique_id']}" for g in _groups(doc, root_key)}


def _referenced(doc: dict, root_key: str) -> Set[str]:
    """entity_id, на которые этот YAML ссылается."""
    return {e for g in _groups(doc, root_key) for e in g["entities"]}


# ============================================================
# ПОДГРУППЫ СВЕТА (ЗОНЫ)
# ============================================================

def test_lights_creates_zone_per_group(simple_layer):
    doc = _run(LIGHTS, simple_layer)
    groups = _groups(doc, "lights_group")

    assert len(groups) == 1
    assert groups[0]["unique_id"] == "101_1"
    assert groups[0]["entities"] == ["light.l_1_1_1", "light.l_1_1_2"]


def test_lights_keeps_table_order(object_layer):
    """Порядок зон — как в Excel: наладчик сверяет YAML со своей таблицей."""
    doc = _run(LIGHTS, object_layer)
    ids = [g["unique_id"] for g in _groups(doc, "lights_group")]

    assert ids == ["101_1", "102_1", "103_1", "103_2", "103_3", "103_4",
                   "104_1", "104_2", "105_1", "105_2", "106_1", "106_2"]


def test_lights_platform_is_group(simple_layer):
    doc = _run(LIGHTS, simple_layer)
    assert all(g["platform"] == "group" for g in _groups(doc, "lights_group"))


def test_lights_includes_space_without_type(layer):
    """Помещение без типа: лампы реальны, значит зона нужна."""
    doc = _run(LIGHTS, layer)
    ids = [g["unique_id"] for g in _groups(doc, "lights_group")]

    assert "202_1" in ids


# ============================================================
# ОБЩИЕ ГРУППЫ ПОМЕЩЕНИЙ
# ============================================================

def test_general_name_comes_from_room_name_only(layer):
    """
    Имя собирается из названия помещения, тип в нём не участвует:
        101_Коридор -> 101_koridor -> 101_koridor_obshchii
    """
    doc = _run(GENERAL, layer)
    by_id = {g["unique_id"]: g for g in _groups(doc, "lights_general_group")}

    assert "101_koridor_obshchii" in by_id
    assert by_id["101_koridor_obshchii"]["entities"] == ["light.101_1", "light.101_2"]


def test_general_includes_corridors(layer):
    """
    Коридоры получают общую группу наравне со всеми.
    В v1 они исключались флагом EXCLUDE_SPACE_CONTAINS=["koridor"] —
    это был артефакт отладки перед ПНР, а группа этажа на них всё равно
    ссылалась, порождая висячие сущности.
    """
    doc = _run(GENERAL, layer)
    ids = {g["unique_id"] for g in _groups(doc, "lights_general_group")}

    assert "101_koridor_obshchii" in ids


def test_general_includes_space_without_type(layer):
    doc = _run(GENERAL, layer)
    ids = {g["unique_id"] for g in _groups(doc, "lights_general_group")}

    assert "202_sklad_obshchii" in ids


def test_general_one_group_per_space(object_layer):
    doc = _run(GENERAL, object_layer)
    assert len(_groups(doc, "lights_general_group")) == 6


# ============================================================
# ГРУППЫ ЭТАЖЕЙ
# ============================================================

def test_floor_group_per_floor(layer):
    doc = _run(FLOOR, layer, tech_groups=False)
    groups = _groups(doc, "lights_floor_group")

    assert [g["unique_id"] for g in groups] == ["floor_1_all", "floor_2_all"]
    assert groups[0]["name"] == "Весь 1-й этаж"


def test_floor_contains_general_groups_not_lamps(layer):
    """Группа этажа собирается из общих групп помещений, а не из ламп."""
    doc = _run(FLOOR, layer, tech_groups=False)
    first = _groups(doc, "lights_floor_group")[0]

    assert first["entities"] == ["light.101_koridor_obshchii", "light.102_klass_obshchii"]


def test_floor_uses_excel_floor_column(tmp_path):
    """
    Этаж берётся из колонки «Этаж», а не из адреса: лестница может стоять
    на границе, и в группу этажа она должна попасть туда, куда её отнёс
    проектировщик.
    """
    rows = base_rows()
    rows[0]["Этаж"] = 2          # колонка говорит: 2-й этаж
    rows[0]["Лампа"] = "1.1.1"   # адрес говорит: 1-й (это W03, не ошибка)
    rows[1]["Этаж"] = 2

    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)

    doc = _run(FLOOR, out, tech_groups=False)
    assert [g["unique_id"] for g in _groups(doc, "lights_floor_group")] == ["floor_2_all"]


def test_tech_groups_off_by_default(layer):
    doc = _run(FLOOR, layer, tech_groups=False)
    ids = {g["unique_id"] for g in _groups(doc, "lights_floor_group")}

    assert not any(i.startswith("tex_floor") for i in ids)


def test_tech_groups_on(layer):
    doc = _run(FLOOR, layer, tech_groups=True)
    by_id = {g["unique_id"]: g for g in _groups(doc, "lights_floor_group")}

    assert "tex_floor_1" in by_id
    assert by_id["tex_floor_1"]["entities"] == ["light.101_koridor_obshchii"]

    # На 2-м этаже только zal и помещение без типа — технических нет,
    # блок не выводим (пустая группа в HA бесполезна).
    assert "tex_floor_2" not in by_id


def test_tech_types_composition(tmp_path):
    """
    Технические = проходные пространства: korridor, special, recreation.
    За рамками: class (люди сидят за партами) и zal (только с панелей).
    Согласовано с владельцем 2026-07-13.
    """
    rows = []
    for i, (name, stype) in enumerate([
        ("101_Коридор", "Korridor"),
        ("102_Тамбур", "Special"),
        ("103_Рекреация", "Recreation"),
        ("104_Класс", "Class"),
        ("105_Зал", "Zal"),
    ], start=1):
        rows.append({
            "Этаж": 1, "Название помещения": name, "Тип помещения": stype,
            "Шина DALI": 1, "Группа": f"10{i}_1", "Лампа": f"1.1.{i}",
            "Датчик": "None", "Панель": "None",
        })

    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)

    doc = _run(FLOOR, out, tech_groups=True)
    by_id = {g["unique_id"]: g for g in _groups(doc, "lights_floor_group")}

    assert by_id["tex_floor_1"]["entities"] == [
        "light.101_koridor_obshchii",
        "light.102_tambur_obshchii",
        "light.103_rekreatsiia_obshchii",
    ]

    # А вот в группу всего этажа попадают все пять.
    assert len(by_id["floor_1_all"]["entities"]) == 5


def test_tech_group_references_existing_entities(tmp_path):
    """Тех.группа ссылается на общие группы — они должны быть созданы."""
    rows = [{
        "Этаж": 1, "Название помещения": "101_Коридор", "Тип помещения": "Korridor",
        "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.1",
        "Датчик": "None", "Панель": "None",
    }]

    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)

    general = _run(GENERAL, out)
    floor = _run(FLOOR, out, tech_groups=True)

    assert _referenced(floor, "lights_floor_group") <= _created(general, "lights_general_group")


# ============================================================
# СОГЛАСОВАННОСТЬ ИЕРАРХИИ
# ============================================================

def test_no_dangling_entities(object_layer):
    """
    Каждая ссылка ведёт на сущность, которую кто-то создал:
        группа этажа -> общие группы -> зоны

    Именно это ломалось в v1: general пропускал коридоры, а floor на них
    ссылался — в HA появлялась группа с несуществующим entity.
    """
    lights = _run(LIGHTS, object_layer)
    general = _run(GENERAL, object_layer)
    floor = _run(FLOOR, object_layer, tech_groups=False)

    zones = _created(lights, "lights_group")
    generals = _created(general, "lights_general_group")

    assert _referenced(general, "lights_general_group") <= zones
    assert _referenced(floor, "lights_floor_group") <= generals


def test_hierarchy_counts(object_layer):
    lights = _run(LIGHTS, object_layer)
    general = _run(GENERAL, object_layer)
    floor = _run(FLOOR, object_layer, tech_groups=False)

    assert len(_groups(lights, "lights_group")) == 12
    assert len(_groups(general, "lights_general_group")) == 6
    assert len(_groups(floor, "lights_floor_group")) == 1

    lamps = _referenced(lights, "lights_group")
    assert len(lamps) == 75


def test_filters_keep_hierarchy_consistent(object_layer):
    """
    Один и тот же фильтр в general и floor не должен разводить файлы:
    иначе группа этажа сошлётся на общую группу, которой нет.
    """
    filters = Filters(exclude_floors=[])
    filters = Filters(spaces=["103_Вестибюль", "104_Методический кабинет"])

    general = _run(GENERAL, object_layer, filters)
    floor = _run(FLOOR, object_layer, filters, tech_groups=False)

    assert _referenced(floor, "lights_floor_group") <= _created(general, "lights_general_group")
    assert len(_groups(general, "lights_general_group")) == 2


# ============================================================
# ФИЛЬТРЫ
# ============================================================

def test_filter_by_room_slug(object_layer):
    doc = _run(LIGHTS, object_layer, Filters(spaces=["102_tambur"]))
    assert [g["unique_id"] for g in _groups(doc, "lights_group")] == ["102_1"]


def test_filter_by_russian_name(object_layer):
    """Наладчику неочевидно, что в фильтр надо писать транслит."""
    doc = _run(LIGHTS, object_layer, Filters(spaces=["102_Тамбур"]))
    assert [g["unique_id"] for g in _groups(doc, "lights_group")] == ["102_1"]


def test_exclude_floors(layer):
    doc = _run(FLOOR, layer, Filters(exclude_floors=[2]), tech_groups=False)
    assert [g["unique_id"] for g in _groups(doc, "lights_floor_group")] == ["floor_1_all"]


def test_include_floors(layer):
    doc = _run(FLOOR, layer, Filters(include_floors=[2]), tech_groups=False)
    assert [g["unique_id"] for g in _groups(doc, "lights_floor_group")] == ["floor_2_all"]


def test_exclude_space_contains_matches_both_spellings(object_layer):
    """Подстрока ищется и в русском имени, и в транслите."""
    ru = _run(LIGHTS, object_layer, Filters(exclude_space_contains=["Тамбур"]))
    en = _run(LIGHTS, object_layer, Filters(exclude_space_contains=["tambur"]))

    ids_ru = {g["unique_id"] for g in _groups(ru, "lights_group")}
    ids_en = {g["unique_id"] for g in _groups(en, "lights_group")}

    assert ids_ru == ids_en
    assert "101_1" not in ids_ru
    assert "103_1" in ids_ru


def test_filters_leaving_nothing_produce_comment(object_layer):
    """Пустой YAML выглядит как поломка — оставляем объяснение."""
    from scripts._lib.normalized import load_dataset

    df = load_dataset(object_layer, "groups")
    text = LIGHTS.build_yaml(df, Filters(spaces=["нет такого"]))

    assert text.startswith("#")
    assert yaml.safe_load(text) is None


# ============================================================
# CLI
# ============================================================

def _main(module, monkeypatch, layer: Path, out: Path, *extra: str) -> int:
    argv = [module.__name__, "--normalized", str(layer), "--out", str(out), *extra]
    monkeypatch.setattr("sys.argv", argv)
    return module.main()


@pytest.mark.parametrize("module,root_key", [
    (LIGHTS, "lights_group"),
    (GENERAL, "lights_general_group"),
    (FLOOR, "lights_floor_group"),
])
def test_cli_writes_yaml(module, root_key, monkeypatch, tmp_path, object_layer):
    out = tmp_path / "out.yaml"

    assert _main(module, monkeypatch, object_layer, out) == 0

    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert root_key in doc


@pytest.mark.parametrize("module", [LIGHTS, GENERAL, FLOOR])
def test_cli_without_normalized_layer(module, monkeypatch, tmp_path):
    """Генератор запускается сам по себе — но без parquet работать не может."""
    code = _main(module, monkeypatch, tmp_path / "нет", tmp_path / "o.yaml")
    assert code == 2


def test_cli_filter_args(monkeypatch, tmp_path, object_layer):
    out = tmp_path / "out.yaml"
    _main(LIGHTS, monkeypatch, object_layer, out, "--spaces", "102_tambur")

    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert [g["unique_id"] for g in doc["lights_group"]["light"]] == ["102_1"]


def test_cli_tech_groups_flag(monkeypatch, tmp_path, layer):
    out = tmp_path / "out.yaml"
    _main(FLOOR, monkeypatch, layer, out, "--generate-tech-groups")

    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    ids = {g["unique_id"] for g in doc["lights_floor_group"]["light"]}
    assert "tex_floor_1" in ids
