# -*- coding: utf-8 -*-
"""
Генератор zone_manager.json и сборка зон из листа «Группы соседей».

Проверяем то, что при поломке молчит: правило группы света, forward-fill,
заглушки, различение «пусто vs маркер», битые ссылки, структуру JSON.

План и обоснования — docs/internal/plan-zone-manager.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import normalize_excel as N
import generate_zone_manager as ZM
from conftest import make_book
from scripts._lib.canon import (
    ZAGLUSHKA_LIGHT,
    ZAGLUSHKA_SENSOR,
    ZONE_MANAGER_VERSION,
    light_group_from_cell,
)
from scripts._lib.excel_schema import NEIGHBORS_COLUMNS

MAIN, GRP, NB, NBG, FAR = NEIGHBORS_COLUMNS


# ============================================================
# ПРАВИЛО ГРУППЫ СВЕТА (канон)
# ============================================================

def test_group_id_becomes_zone_light():
    assert light_group_from_cell("103_1") == "light.103_1"
    assert light_group_from_cell("208_2") == "light.208_2"


def test_room_name_becomes_general_light():
    """Имя помещения (не group_id) -> общая группа помещения."""
    assert light_group_from_cell("101_Тамбур") == "light.101_tambur_obshchii"


def test_group_rule_matches_generated_groups():
    """
    ⚠ Ключевое: правило обязано давать те же имена, что generate_*_groups,
    иначе zone_manager сошлётся на несуществующую сущность. group_id -> зонная,
    имя -> общая, обе строятся теми же билдерами канона.
    """
    from scripts._lib.canon import zone_light_entity, general_light_entity, slugify_room
    assert light_group_from_cell("103_2") == zone_light_entity("103_2")
    assert light_group_from_cell("Зал 5") == general_light_entity(slugify_room("Зал 5"))


# ============================================================
# СБОРКА ЗОН: forward-fill, заглушки, валидация
# ============================================================

def _devices(sensors):
    """Мини-devices: только датчики с их помещениями."""
    return pd.DataFrame([
        {"entity_id": e, "kind": "sensor", "space": sp} for e, sp in sensors
    ])


def _sheet(rows):
    return pd.DataFrame(rows, columns=list(NEIGHBORS_COLUMNS))


def test_forward_fill_groups_neighbors_into_one_zone():
    """
    Строки с пустым «Основной датчик» продолжают предыдущий блок: у датчика
    накапливается несколько соседей.
    """
    devices = _devices([("sensor.ms_1_1_5", "103")])
    df, _ = N.build_neighbors(_sheet([
        {MAIN: "1.1.5", GRP: "103_2", NB: "1.1.4", NBG: "103_1", FAR: "1.1.6"},
        {MAIN: "",      GRP: "",      NB: "1.1.6", NBG: "103_3", FAR: "1.1.7"},
    ]), devices)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["sensor"] == "sensor.ms_1_1_5"
    assert list(row["neighbors"]) == ["sensor.ms_1_1_4", "sensor.ms_1_1_6"]
    assert list(row["neighbor_groups"]) == ["light.103_1", "light.103_3"]
    assert list(row["far_neighbors"]) == ["sensor.ms_1_1_6", "sensor.ms_1_1_7"]


def test_zone_without_neighbors_gets_stubs():
    """Тамбур: соседей нет вообще -> заглушки, БЕЗ предупреждения."""
    devices = _devices([("sensor.ms_1_1_1", "101_Тамбур")])
    df, warns = N.build_neighbors(_sheet([
        {MAIN: "1.1.1", GRP: "101_Тамбур", NB: "", NBG: "", FAR: ""},
    ]), devices)

    row = df.iloc[0]
    assert list(row["neighbors"]) == [ZAGLUSHKA_SENSOR]
    assert list(row["neighbor_groups"]) == [ZAGLUSHKA_LIGHT]
    assert list(row["far_neighbors"]) == [ZAGLUSHKA_SENSOR]
    assert list(row["light_group"]) == ["light.101_tambur_obshchii"]
    assert warns == []   # это норма, не пропуск


def test_marker_dash_is_silent_stub():
    """Явный «-» в дальнем -> заглушка ТИХО (наладчик сказал «нет»)."""
    devices = _devices([("sensor.ms_1_1_4", "103")])
    df, warns = N.build_neighbors(_sheet([
        {MAIN: "1.1.4", GRP: "103_1", NB: "1.1.5", NBG: "103_2", FAR: "-"},
    ]), devices)

    assert list(df.iloc[0]["far_neighbors"]) == [ZAGLUSHKA_SENSOR]
    assert warns == []


def test_empty_cell_warns():
    """Пустая ячейка дальнего при заполненной строке -> заглушка + ПРЕДУПРЕЖДЕНИЕ."""
    devices = _devices([("sensor.ms_1_1_4", "103")])
    df, warns = N.build_neighbors(_sheet([
        {MAIN: "1.1.4", GRP: "103_1", NB: "1.1.5", NBG: "103_2", FAR: ""},
    ]), devices)

    assert list(df.iloc[0]["far_neighbors"]) == [ZAGLUSHKA_SENSOR]
    assert len(warns) == 1
    assert "пустая ячейка" in warns[0].lower()


def test_unknown_sensor_warns_and_has_no_space():
    """Основной датчик не в «Проектной БД» -> предупреждение, space пустой."""
    devices = _devices([("sensor.ms_9_9_9", "прочее")])
    df, warns = N.build_neighbors(_sheet([
        {MAIN: "1.1.1", GRP: "101_1", NB: "", NBG: "", FAR: ""},
    ]), devices)

    assert df.iloc[0]["space"] == ""
    assert any("не найден в «Проектной БД»" in w for w in warns)


# ============================================================
# СТРУКТУРА JSON
# ============================================================

def _payload(df):
    return ZM.build_zone_manager(df)


def test_version_and_name_space_first():
    df, _ = N.build_neighbors(_sheet([
        {MAIN: "1.1.4", GRP: "103_1", NB: "-", NBG: "-", FAR: "-"},
    ]), _devices([("sensor.ms_1_1_4", "103_Вестибюль")]))
    p = _payload(df)

    assert p["version"] == ZONE_MANAGER_VERSION
    assert list(p["spaces"])[0] == "NAME SPACE"   # эталон первым


def test_name_space_matches_reference():
    """NAME SPACE в выходе совпадает с эталоном templates/json (если он есть)."""
    ref_path = Path(__file__).resolve().parent.parent / "templates" / "json" / "zone_manager.json"
    if not ref_path.exists():
        pytest.skip("нет эталона templates/json/zone_manager.json")

    ref = json.loads(ref_path.read_text(encoding="utf-8"))["spaces"]["NAME SPACE"]
    assert ZM.NAME_SPACE_BLOCK == ref


def test_zone_key_order_matches_reference():
    """Порядок ключей зоны — как ждёт интеграция: neighbors, far, groups, light."""
    df, _ = N.build_neighbors(_sheet([
        {MAIN: "1.1.4", GRP: "103_1", NB: "1.1.5", NBG: "103_2", FAR: "1.1.6"},
    ]), _devices([("sensor.ms_1_1_4", "103_Вестибюль")]))
    zone = _payload(df)["spaces"]["103_Вестибюль"]["zones"]["sensor.ms_1_1_4"]

    assert list(zone) == ["neighbors", "far_neighbors", "neighbor_groups", "light_group"]


def test_no_light_group_single_in_file():
    """light_group_single НЕ кладём: интеграция вычисляет его сама."""
    df, _ = N.build_neighbors(_sheet([
        {MAIN: "1.1.4", GRP: "103_1", NB: "-", NBG: "-", FAR: "-"},
    ]), _devices([("sensor.ms_1_1_4", "103_Вестибюль")]))
    zone = _payload(df)["spaces"]["103_Вестибюль"]["zones"]["sensor.ms_1_1_4"]

    assert "light_group_single" not in zone


def test_grouped_by_space():
    """Зоны группируются по помещению основного датчика."""
    devices = _devices([
        ("sensor.ms_1_1_4", "103_Вестибюль"),
        ("sensor.ms_1_2_1", "106_Лестница"),
    ])
    df, _ = N.build_neighbors(_sheet([
        {MAIN: "1.1.4", GRP: "103_1", NB: "-", NBG: "-", FAR: "-"},
        {MAIN: "1.2.1", GRP: "106_1", NB: "-", NBG: "-", FAR: "-"},
    ]), devices)
    p = _payload(df)

    assert "sensor.ms_1_1_4" in p["spaces"]["103_Вестибюль"]["zones"]
    assert "sensor.ms_1_2_1" in p["spaces"]["106_Лестница"]["zones"]


# ============================================================
# БИТЫЕ ССЫЛКИ
# ============================================================

def test_check_references_flags_unknown_but_not_stubs():
    df, _ = N.build_neighbors(_sheet([
        {MAIN: "1.1.4", GRP: "103_1", NB: "9.9.9", NBG: "103_2", FAR: "-"},
    ]), _devices([("sensor.ms_1_1_4", "103_Вестибюль")]))
    p = _payload(df)

    broken = ZM.check_references(
        p,
        known_sensors={"sensor.ms_1_1_4"},          # 9.9.9 отсутствует
        known_lights={"light.103_1", "light.103_2"},
    )

    # заглушка far (-) не считается битой; неизвестный сосед 9_9_9 — считается
    assert any("sensor.ms_9_9_9" in b for b in broken)
    assert all(ZAGLUSHKA_SENSOR not in b for b in broken)


# ============================================================
# СКВОЗНОЙ ПРОГОН НА ФИКСТУРЕ
# ============================================================

@pytest.fixture
def normalized(tmp_path, object_example):
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


def test_end_to_end_from_object_example(normalized):
    from scripts._lib.normalized import load_dataset
    df = load_dataset(normalized, "neighbors")
    p = _payload(df)

    assert p["version"] == "v0.1"
    real = [s for s in p["spaces"] if s != "NAME SPACE"]
    assert real, "на фикстуре есть зоны"

    # каждая зона непустая по всем четырём полям (заглушки считаются)
    for space in real:
        for sensor, zone in p["spaces"][space]["zones"].items():
            for field in ("neighbors", "far_neighbors", "neighbor_groups", "light_group"):
                assert zone[field], f"{sensor}.{field} пуст"
