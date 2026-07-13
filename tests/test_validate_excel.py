# -*- coding: utf-8 -*-
"""
Валидатор входной таблицы: по кейсу на каждое правило.

Коды правил описаны в docs/ROADMAP.md, этап 2.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Set

import pytest

import validate_excel as V
from conftest import HEADERS, base_rows, make_book


def codes(findings) -> Set[str]:
    return {f.code for f in findings}


def errors(findings) -> List:
    return [f for f in findings if f.severity == "error"]


def run(path: Path, sheet: str = V.SHEET_NAME):
    return V.validate(path, sheet)


def build(tmp_path: Path, rows, **kw) -> Path:
    return make_book(tmp_path / "t.xlsx", rows, **kw)


# ============================================================
# ВАЛИДНЫЕ ТАБЛИЦЫ
# ============================================================

def test_valid_table_has_no_findings(valid_xlsx):
    findings, stats = run(valid_xlsx)
    assert findings == []
    assert stats == {
        "rows": 2, "spaces": 1, "groups": 1,
        "lamps": 2, "sensors": 1, "panels": 0, "units": 1,
    }


def test_object_example_passes(object_example):
    """Реальная фикстура v2 должна проходить без единой ошибки."""
    findings, stats = run(object_example)

    assert errors(findings) == [], [f.message for f in errors(findings)]
    assert stats == {
        "rows": 75, "spaces": 6, "groups": 12,
        "lamps": 75, "sensors": 11, "panels": 5,
        # hl_1 (два тамбура), 103_vestibiul (сам по себе), ladder_1
        "units": 3,
    }


@pytest.mark.parametrize("token", ["None", "нет", "-", "none"])
def test_none_tokens_accepted(tmp_path, token):
    """Наладчик может написать 'нет' или '-' вместо None."""
    rows = base_rows()
    rows[0]["Панель"] = token
    findings, _ = run(build(tmp_path, rows))
    assert findings == []


def test_group_may_have_several_sensors(tmp_path):
    """Ключевое послабление v2: у группы может быть больше одного датчика."""
    rows = base_rows()
    rows[1]["Датчик"] = "1.1.2"
    findings, stats = run(build(tmp_path, rows))
    assert findings == []
    assert stats["sensors"] == 2


def test_space_level_declaration_is_enough(tmp_path):
    """
    Правило «либо датчик, либо None» проверяется на уровне помещения:
    достаточно одной непустой ячейки, остальные строки свободны.
    """
    rows = base_rows()
    rows.append({"Этаж": 1, "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.3"})
    findings, _ = run(build(tmp_path, rows))
    assert findings == []


# ============================================================
# БЛОКИРУЮЩИЕ ОШИБКИ
# ============================================================

def test_e01_missing_sheet(tmp_path):
    path = build(tmp_path, base_rows(), sheet_name="Не та БД")
    findings, stats = run(path)
    assert codes(findings) == {"E01"}
    assert stats == {}


def test_e02_missing_column(tmp_path):
    headers = [h for h in HEADERS if h != "Датчик"]
    path = build(tmp_path, base_rows(), headers=headers)
    findings, stats = run(path)
    assert codes(findings) == {"E02"}
    assert stats == {}


def test_e03_lamp_address_malformed(tmp_path):
    rows = base_rows()
    rows[1]["Лампа"] = "1.1"
    findings, _ = run(build(tmp_path, rows))
    assert "E03" in codes(findings)


def test_e03_lamp_cannot_be_absent(tmp_path):
    """'None' в колонке «Лампа» бессмысленно: строка существует ради лампы."""
    rows = base_rows()
    rows[1]["Лампа"] = "None"
    findings, _ = run(build(tmp_path, rows))
    assert "E03" in codes(findings)


def test_e04_duplicate_lamp(tmp_path):
    rows = base_rows()
    rows[1]["Лампа"] = "1.1.1"
    findings, _ = run(build(tmp_path, rows))
    assert "E04" in codes(findings)


def test_e05_duplicate_sensor_in_same_group(tmp_path):
    rows = base_rows()
    rows[1]["Датчик"] = "1.1.1"
    findings, _ = run(build(tmp_path, rows))
    assert "E05" in codes(findings)
    assert "E07" not in codes(findings)  # группа одна — разъезда нет


def test_e06_duplicate_panel(tmp_path):
    rows = base_rows()
    rows[0]["Панель"] = "1.1.1"
    rows[1]["Панель"] = "1.1.1"
    findings, _ = run(build(tmp_path, rows))
    assert "E06" in codes(findings)


def test_e07_sensor_in_two_groups(tmp_path):
    rows = base_rows()
    rows[1]["Группа"] = "101_2"
    rows[1]["Датчик"] = "1.1.1"
    findings, _ = run(build(tmp_path, rows))
    assert {"E05", "E07"} <= codes(findings)


def test_e08_group_without_lamps(tmp_path):
    rows = base_rows()
    rows.append({"Этаж": 1, "Шина DALI": 1, "Группа": "101_2", "Датчик": "1.1.9"})
    findings, _ = run(build(tmp_path, rows))
    assert "E08" in codes(findings)


def test_e09_space_without_lamps(tmp_path):
    rows = [{
        "Этаж": 1, "Название помещения": "101_Тамбур", "Тип помещения": "Special",
        "Шина DALI": 1, "Группа": "101_1", "Датчик": "1.1.1", "Панель": "None",
    }]
    findings, _ = run(build(tmp_path, rows))
    assert "E09" in codes(findings)


def test_e10_space_without_sensor_declaration(tmp_path):
    rows = base_rows()
    del rows[0]["Датчик"]
    findings, _ = run(build(tmp_path, rows))
    assert "E10" in codes(findings)


def test_e11_space_without_panel_declaration(tmp_path):
    rows = base_rows()
    del rows[0]["Панель"]
    findings, _ = run(build(tmp_path, rows))
    assert "E11" in codes(findings)


def test_e12_device_without_group(tmp_path):
    rows = base_rows()
    rows.append({"Этаж": 1, "Шина DALI": 1, "Лампа": "1.1.3"})
    findings, _ = run(build(tmp_path, rows))
    assert "E12" in codes(findings)


def test_e13_group_in_two_spaces(tmp_path):
    """light.<group_id> перестаёт быть уникальным — это ловим до генерации."""
    rows = base_rows()
    rows.append({
        "Этаж": 1, "Название помещения": "102_Тамбур", "Тип помещения": "Special",
        "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.5",
        "Датчик": "None", "Панель": "None",
    })
    findings, _ = run(build(tmp_path, rows))
    assert "E13" in codes(findings)


def test_e14_unrecognised_sensor_token(tmp_path):
    rows = base_rows()
    rows[1]["Датчик"] = "поставить позже"
    findings, _ = run(build(tmp_path, rows))
    assert "E14" in codes(findings)


# ============================================================
# ПРЕДУПРЕЖДЕНИЯ
# ============================================================

def test_w01_space_without_type(tmp_path):
    rows = base_rows()
    del rows[0]["Тип помещения"]
    findings, _ = run(build(tmp_path, rows))
    assert codes(findings) == {"W01"}
    assert errors(findings) == []  # помещение остаётся в группах света


def test_w02_unknown_type(tmp_path):
    rows = base_rows()
    rows[0]["Тип помещения"] = "Corridor"  # опечатка: канон — Korridor
    findings, _ = run(build(tmp_path, rows))
    assert codes(findings) == {"W02"}


def test_w03_floor_mismatch(tmp_path):
    """Истина в адресе, колонка «Этаж» — справочная. Предупреждаем, но не блокируем."""
    rows = base_rows()
    rows[1]["Лампа"] = "2.1.2"
    findings, _ = run(build(tmp_path, rows))
    assert codes(findings) == {"W03"}
    assert errors(findings) == []


def test_w04_bus_mismatch(tmp_path):
    rows = base_rows()
    rows[1]["Лампа"] = "1.5.2"
    findings, _ = run(build(tmp_path, rows))
    assert codes(findings) == {"W04"}


def test_w03_reported_once_per_row(tmp_path):
    """Одна строка — одно сообщение, иначе отчёт утонет."""
    rows = base_rows()
    rows[0]["Лампа"] = "9.1.1"
    rows[0]["Датчик"] = "9.1.1"
    rows[0]["Панель"] = "9.1.1"
    findings, _ = run(build(tmp_path, rows))
    assert len([f for f in findings if f.code == "W03"]) == 1


def test_w05_group_without_sensors(tmp_path):
    rows = base_rows()
    rows[0]["Тип помещения"] = "Class"
    rows[0]["Датчик"] = "None"
    findings, _ = run(build(tmp_path, rows))
    assert "W05" in codes(findings)


def test_w05_not_reported_for_zal(tmp_path):
    """У зала датчиков нет по определению — это не повод шуметь."""
    rows = base_rows()
    rows[0]["Тип помещения"] = "Zal"
    rows[0]["Датчик"] = "None"
    findings, _ = run(build(tmp_path, rows))
    assert "W05" not in codes(findings)


def test_w06_blank_row_inside_data(tmp_path):
    rows: List = base_rows()
    rows.insert(1, None)
    findings, _ = run(build(tmp_path, rows))
    assert codes(findings) == {"W06"}


def test_trailing_blank_rows_are_silent(tmp_path):
    """Хвост пустых строк — норма Excel, а не проблема таблицы."""
    rows: List = base_rows() + [None, None, None]
    findings, _ = run(build(tmp_path, rows))
    assert findings == []


# ============================================================
# КОД ВОЗВРАТА
# ============================================================

def _main(monkeypatch, path: Path, report: Path, *extra: str) -> int:
    argv = ["validate_excel.py", "--excel", str(path), "--report", str(report), *extra]
    monkeypatch.setattr("sys.argv", argv)
    return V.main()


def test_exit_code_zero_on_valid(monkeypatch, tmp_path, valid_xlsx):
    assert _main(monkeypatch, valid_xlsx, tmp_path / "r.json") == 0


def test_exit_code_one_on_error(monkeypatch, tmp_path):
    rows = base_rows()
    rows[1]["Лампа"] = "1.1.1"
    path = build(tmp_path, rows)
    assert _main(monkeypatch, path, tmp_path / "r.json") == 1


def test_warnings_do_not_fail_by_default(monkeypatch, tmp_path):
    rows = base_rows()
    del rows[0]["Тип помещения"]
    path = build(tmp_path, rows)
    assert _main(monkeypatch, path, tmp_path / "r.json") == 0


def test_strict_turns_warnings_into_failure(monkeypatch, tmp_path):
    rows = base_rows()
    del rows[0]["Тип помещения"]
    path = build(tmp_path, rows)
    assert _main(monkeypatch, path, tmp_path / "r.json", "--strict") == 1


def test_missing_file_returns_two(monkeypatch, tmp_path):
    assert _main(monkeypatch, tmp_path / "нет.xlsx", tmp_path / "r.json") == 2


def test_report_written(monkeypatch, tmp_path, valid_xlsx):
    import json

    report = tmp_path / "r.json"
    _main(monkeypatch, valid_xlsx, report)

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["sheet_name"] == V.SHEET_NAME
    assert payload["errors"] == []
    assert payload["stats"]["lamps"] == 2
