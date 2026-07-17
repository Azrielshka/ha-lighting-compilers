# -*- coding: utf-8 -*-
"""
Единицы обслуживания: колонка «Блок», семейства, клонирование скриптов.

Один экземпляр скрипта в HA — это одна очередь. При тысяче датчиков вызовы
копятся и свет отстаёт от человека, поэтому шаблонные скрипты клонируются:
у каждой единицы свой набор.

Единица = помещение (если «Блок» пуст) либо все помещения одного «Блока».
Что склеивать, решает проектировщик, глядя на план: вывести стояк лестниц
или «ближайшие санузлы» из номеров помещений нельзя.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd
import pytest

import normalize_excel as N
import validate_excel as V
from conftest import make_book
from scripts._lib.canon import (
    FAMILY_BY_SPACE_TYPE,
    MAX_SENSORS_PER_UNIT,
    SCRIPTS_BY_FAMILY,
    family_for_space_type,
    script_entity,
)
from scripts._lib.normalized import load_dataset


def row(space=None, stype=None, block=None, floor=1, group="101_1",
        lamp="1.1.1", sensor=None, panel=None) -> Dict:
    """Строка таблицы. Помещение/тип/блок — только на первой строке помещения."""
    r: Dict = {"Этаж": floor, "Шина DALI": 1, "Группа": group, "Лампа": lamp}
    if space:
        r["Название помещения"] = space
        r["Тип помещения"] = stype
        if block:
            r["Блок"] = block
    if sensor:
        r["Датчик"] = sensor
    if panel:
        r["Панель"] = panel
    return r


def units_of(tmp_path: Path, rows: List[Dict]) -> pd.DataFrame:
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)
    return load_dataset(out, "units")


def codes(findings) -> set:
    return {f.code for f in findings}


# ============================================================
# КАНОН СЕМЕЙСТВ
# ============================================================

def test_families():
    assert family_for_space_type("korridor") == "default"
    assert family_for_space_type("recreation") == "default"
    assert family_for_space_type("hall") == "hall"
    assert family_for_space_type("special") == "special"


def test_class_and_zal_have_no_family():
    """Класс управляется панелью и поддержанием освещённости (вне охвата),
    зал — только панелями. Скрипты и автоматизации им не создаются."""
    assert family_for_space_type("class") is None
    assert family_for_space_type("zal") is None
    assert family_for_space_type(None) is None


def test_script_counts_per_family():
    assert set(SCRIPTS_BY_FAMILY["default"]) == {"on", "off", "near_off"}
    assert set(SCRIPTS_BY_FAMILY["hall"]) == {"on", "off", "hall_near"}
    assert set(SCRIPTS_BY_FAMILY["special"]) == {"on", "off"}


def test_script_naming():
    assert script_entity("103_vestibiul", "on") == "script.103_vestibiul_on"
    assert script_entity("ladder_1", "near_off") == "script.ladder_1_near_off"


def test_every_allowed_type_has_family_decision():
    """Новый тип помещения обязан получить решение: семейство или явный None."""
    from scripts._lib.canon import ALLOWED_SPACE_TYPES

    assert set(FAMILY_BY_SPACE_TYPE) == ALLOWED_SPACE_TYPES


# ============================================================
# ЕДИНИЦА = ПОМЕЩЕНИЕ (БЛОК ПУСТ)
# ============================================================

def test_space_without_block_is_its_own_unit(tmp_path):
    units = units_of(tmp_path, [
        row("101_Коридор", "Korridor", sensor="1.1.1", panel="None"),
    ])

    assert len(units) == 1
    u = units.iloc[0]
    assert u["unit_id"] == "101_koridor"
    assert list(u["spaces"]) == ["101_Коридор"]
    assert list(u["scripts"]) == [
        "script.101_koridor_on",
        "script.101_koridor_off",
        "script.101_koridor_near_off",
    ]


def test_corridors_are_never_merged(tmp_path):
    """Коридоры и рекреации самостоятельны: у каждого своя очередь скриптов."""
    units = units_of(tmp_path, [
        row("101_Коридор", "Korridor", group="101_1", lamp="1.1.1",
            sensor="1.1.1", panel="None"),
        row("102_Коридор", "Korridor", group="102_1", lamp="1.1.2",
            sensor="1.1.2", panel="None"),
    ])

    assert len(units) == 2
    assert set(units["unit_id"]) == {"101_koridor", "102_koridor"}


# ============================================================
# ЕДИНИЦА = БЛОК
# ============================================================

def test_block_merges_spaces(tmp_path):
    """Два санузла рядом — один блок, одна очередь скриптов."""
    units = units_of(tmp_path, [
        row("110_Санузел_Ж", "Special", block="wc_1", group="110_1",
            lamp="1.1.1", sensor="1.1.1", panel="None"),
        row("111_Санузел_М", "Special", block="wc_1", group="111_1",
            lamp="1.1.2", sensor="1.1.2", panel="None"),
    ])

    assert len(units) == 1
    u = units.iloc[0]
    assert u["unit_id"] == "wc_1"
    assert list(u["spaces"]) == ["110_Санузел_Ж", "111_Санузел_М"]
    assert u["sensor_count"] == 2
    assert list(u["scripts"]) == ["script.wc_1_on", "script.wc_1_off"]


def test_block_spans_floors(tmp_path):
    """
    Лестничный стояк: одна единица на несколько этажей.
    Вывести это из номеров помещений нельзя — только из «Блока».
    """
    units = units_of(tmp_path, [
        row("120_Лестница", "Korridor", block="stoyak_a", floor=1,
            group="120_1", lamp="1.1.1", sensor="1.1.1", panel="None"),
        row("220_Лестница", "Korridor", block="stoyak_a", floor=2,
            group="220_1", lamp="2.1.1", sensor="2.1.1", panel="None"),
    ])

    assert len(units) == 1
    u = units.iloc[0]
    assert list(u["floors"]) == [1, 2]
    assert u["sensor_count"] == 2


def test_hall_family(tmp_path):
    units = units_of(tmp_path, [
        row("130_Холл", "Hall", sensor="1.1.1", panel="None"),
    ])

    u = units.iloc[0]
    assert u["family"] == "hall"
    assert u["blueprint_on"] == "zm_hall_on.yaml"
    assert u["blueprint_off"] == "zm_hall_off.yaml"
    assert "script.130_kholl_hall_near" in list(u["scripts"])


def test_class_and_zal_are_not_units(tmp_path):
    """У них нет автоматизаций — в units они не попадают."""
    units = units_of(tmp_path, [
        row("101_Класс", "Class", group="101_1", lamp="1.1.1",
            sensor="1.1.1", panel="None"),
        row("102_Зал", "Zal", group="102_1", lamp="1.1.2",
            sensor="None", panel="1.1.1"),
        row("103_Коридор", "Korridor", group="103_1", lamp="1.1.3",
            sensor="1.1.2", panel="None"),
    ])

    assert list(units["unit_id"]) == ["103_koridor"]


# ============================================================
# ПРИЁМОЧНЫЙ ТЕСТ НА РЕАЛЬНОЙ ФИКСТУРЕ
# ============================================================

def test_object_example_units(tmp_path, object_example):
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    units = load_dataset(out, "units")

    by_id = {u["unit_id"]: u for _, u in units.iterrows()}

    assert set(by_id) == {"hl_1", "103_vestibiul", "ladder_1",
                          "107_rekreatsiia", "208_vkhodnoi_tambur"}

    # Два тамбура склеены в один блок.
    assert list(by_id["hl_1"]["spaces"]) == ["101_Тамбур", "102_Тамбур"]
    assert by_id["hl_1"]["family"] == "special"
    assert by_id["hl_1"]["sensor_count"] == 3
    assert len(by_id["hl_1"]["scripts"]) == 2

    # Коридор сам по себе.
    assert by_id["103_vestibiul"]["family"] == "default"
    assert len(by_id["103_vestibiul"]["scripts"]) == 3

    # Рекреация — тоже default (korridor и recreation одного семейства).
    assert by_id["107_rekreatsiia"]["family"] == "default"
    assert len(by_id["107_rekreatsiia"]["scripts"]) == 3

    # Холл — своё семейство: on, off, hall_near.
    assert by_id["208_vkhodnoi_tambur"]["family"] == "hall"
    assert len(by_id["208_vkhodnoi_tambur"]["scripts"]) == 3


# ============================================================
# ВАЛИДАЦИЯ
# ============================================================

def test_e15_block_mixes_families(tmp_path):
    """Санузел и коридор в одном блоке: им нужны разные blueprint'ы."""
    path = make_book(tmp_path / "t.xlsx", [
        row("110_Санузел", "Special", block="mix", group="110_1",
            lamp="1.1.1", sensor="1.1.1", panel="None"),
        row("111_Коридор", "Korridor", block="mix", group="111_1",
            lamp="1.1.2", sensor="1.1.2", panel="None"),
    ])

    findings, _ = V.validate(path, V.SHEET_NAME)
    assert "E15" in codes(findings)


def test_e16_block_on_non_automated_space(tmp_path):
    """Классу блок не нужен: скрипты ему не создаются."""
    path = make_book(tmp_path / "t.xlsx", [
        row("101_Класс", "Class", block="wc_1", sensor="1.1.1", panel="None"),
    ])

    findings, _ = V.validate(path, V.SHEET_NAME)
    assert "E16" in codes(findings)


def test_w07_too_many_sensors_in_unit(tmp_path):
    """
    Предел 12 зашит в сами blueprint'ы: при большем числе датчиков
    автоматизация в HA останавливается. Предупреждаем заранее, но не блокируем.
    """
    rows = [row("101_Коридор", "Korridor", block="big", group="101_1",
                lamp="1.1.1", sensor="1.1.1", panel="None")]
    for i in range(2, MAX_SENSORS_PER_UNIT + 2):
        rows.append({
            "Этаж": 1, "Шина DALI": 1, "Группа": "101_1",
            "Лампа": f"1.1.{i}", "Датчик": f"1.1.{i}",
        })

    path = make_book(tmp_path / "t.xlsx", rows)
    findings, _ = V.validate(path, V.SHEET_NAME)

    assert "W07" in codes(findings)
    assert not [f for f in findings if f.severity == "error"]  # неломающее


def test_exactly_twelve_sensors_is_ok(tmp_path):
    rows = [row("101_Коридор", "Korridor", group="101_1",
                lamp="1.1.1", sensor="1.1.1", panel="None")]
    for i in range(2, MAX_SENSORS_PER_UNIT + 1):
        rows.append({
            "Этаж": 1, "Шина DALI": 1, "Группа": "101_1",
            "Лампа": f"1.1.{i}", "Датчик": f"1.1.{i}",
        })

    path = make_book(tmp_path / "t.xlsx", rows)
    findings, _ = V.validate(path, V.SHEET_NAME)

    assert "W07" not in codes(findings)


def test_w08_automated_space_without_sensors(tmp_path):
    """Коридор без датчиков: автоматизации по движению работать не будут."""
    path = make_book(tmp_path / "t.xlsx", [
        row("101_Коридор", "Korridor", sensor="None", panel="None"),
    ])

    findings, _ = V.validate(path, V.SHEET_NAME)
    assert "W08" in codes(findings)


def test_zal_without_sensors_is_silent(tmp_path):
    """У зала датчиков нет по определению — это не повод шуметь."""
    path = make_book(tmp_path / "t.xlsx", [
        row("105_Зал", "Zal", sensor="None", panel="1.1.1"),
    ])

    findings, _ = V.validate(path, V.SHEET_NAME)
    assert "W08" not in codes(findings)


def test_object_example_has_no_block_errors(object_example):
    findings, stats = V.validate(object_example, V.SHEET_NAME)

    assert not [f for f in findings if f.code in ("E15", "E16")]
    assert stats["units"] == 5
