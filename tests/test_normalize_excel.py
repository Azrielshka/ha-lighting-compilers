# -*- coding: utf-8 -*-
"""
Нормализация Excel -> parquet.

Модель: docs/internal/data_model.md
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import normalize_excel as N
from conftest import base_rows, make_book


def build(tmp_path: Path, rows, **kw) -> Path:
    return make_book(tmp_path / "t.xlsx", rows, **kw)


def frames(tmp_path: Path, rows, **kw):
    """Прогнать таблицу через нормализацию и вернуть три датасета."""
    df = N.read_sheet(build(tmp_path, rows, **kw))
    devices = N.build_devices(df)
    groups = N.build_groups(devices)
    spaces = N.build_spaces(devices, groups)
    return devices, groups, spaces


# ============================================================
# ЧТЕНИЕ EXCEL
# ============================================================

def test_none_survives_read(tmp_path):
    """
    Главная ловушка pandas: строка "None" входит в na_values по умолчанию
    и молча превращается в NaN. Тогда "устройства нет" и "ячейка пуста"
    становятся неразличимы — а на этом различии держится вся модель.
    """
    df = N.read_sheet(build(tmp_path, base_rows()))
    assert df[N.COLUMNS.panel].iloc[0] == "None"


def test_missing_sheet_raises(tmp_path):
    with pytest.raises(ValueError, match="нет листа"):
        N.read_sheet(build(tmp_path, base_rows(), sheet_name="Другой"))


def test_missing_column_raises(tmp_path):
    from conftest import HEADERS

    headers = [h for h in HEADERS if h != "Группа"]
    with pytest.raises(ValueError, match="обязательных колонок"):
        N.read_sheet(build(tmp_path, base_rows(), headers=headers))


# ============================================================
# DEVICES
# ============================================================

def test_row_expands_into_several_devices(tmp_path):
    """Одна строка Excel = до трёх устройств, и все — в своей группе."""
    rows = base_rows()
    rows[0]["Панель"] = "1.1.1"

    devices, _, _ = frames(tmp_path, rows)
    first = devices[devices.row_id == 2]

    assert set(first["kind"]) == {"lamp", "sensor", "panel"}
    assert set(first["group_id"]) == {"101_1"}


def test_sensor_yields_two_entities(tmp_path):
    devices, _, _ = frames(tmp_path, base_rows())
    sensor = devices[devices.kind == "sensor"].iloc[0]

    assert sensor["entity_id"] == "sensor.ms_1_1_1"
    assert sensor["entity_id_2"] == "sensor.il_1_1_1"


def test_lamp_has_no_second_entity(tmp_path):
    devices, _, _ = frames(tmp_path, base_rows())
    lamp = devices[devices.kind == "lamp"].iloc[0]

    assert lamp["entity_id"] == "light.l_1_1_1"
    assert pd.isna(lamp["entity_id_2"])


def test_absent_devices_are_not_rows(tmp_path):
    """None в ячейке — это отсутствие устройства, а не устройство."""
    devices, _, _ = frames(tmp_path, base_rows())
    assert (devices.kind == "panel").sum() == 0


def test_addr_is_split(tmp_path):
    rows = base_rows()
    rows[0]["Лампа"] = "2.13.7"

    devices, _, _ = frames(tmp_path, rows)
    lamp = devices[devices.addr == "2.13.7"].iloc[0]

    assert (lamp["addr_floor"], lamp["addr_bus"], lamp["addr_num"]) == (2, 13, 7)


def test_space_and_type_are_filled_down(tmp_path):
    """Помещение объявляется один раз, а принадлежат ему все строки до следующего."""
    devices, _, _ = frames(tmp_path, base_rows())

    assert set(devices["space"]) == {"101_Тамбур"}
    assert set(devices["space_type"]) == {"special"}


def test_group_is_not_filled_down(tmp_path):
    """
    В v2 «Группа» заполнена в каждой строке. Строка без группы — это не
    продолжение предыдущей, а ошибка: привязать устройство не к чему.
    """
    rows = base_rows()
    rows.append({"Этаж": 1, "Шина DALI": 1, "Лампа": "1.1.9"})  # группы нет

    devices, _, _ = frames(tmp_path, rows)
    assert "1.1.9" not in set(devices["addr"])


def test_row_id_points_at_excel_row(tmp_path):
    """row_id должен вести наладчика в ту же строку, что он видит в Excel."""
    devices, _, _ = frames(tmp_path, base_rows())
    assert devices["row_id"].tolist()[:2] == [2, 2]  # лампа и датчик из строки 2


def test_malformed_address_is_skipped(tmp_path):
    """Мусор в ячейке ловит валидатор; normalize просто его не тащит."""
    rows = base_rows()
    rows[1]["Лампа"] = "поставить позже"

    devices, _, _ = frames(tmp_path, rows)
    assert len(devices[devices.kind == "lamp"]) == 1


# ============================================================
# GROUPS
# ============================================================

def test_group_holds_several_sensors(tmp_path):
    """
    Ключевое послабление v2: у группы может быть больше одного датчика.
    Старая модель второй датчик молча теряла.
    """
    rows = base_rows()
    rows[1]["Датчик"] = "1.1.2"

    _, groups, _ = frames(tmp_path, rows)
    g = groups.iloc[0]

    assert g["sensor_count"] == 2
    assert list(g["sensors_ms"]) == ["sensor.ms_1_1_1", "sensor.ms_1_1_2"]
    assert list(g["sensors_il"]) == ["sensor.il_1_1_1", "sensor.il_1_1_2"]


def test_group_without_sensors(tmp_path):
    """Зал: датчиков нет по проекту — списки пустые, но группа существует."""
    rows = base_rows()
    rows[0]["Тип помещения"] = "Zal"
    rows[0]["Датчик"] = "None"

    _, groups, _ = frames(tmp_path, rows)
    g = groups.iloc[0]

    assert g["sensor_count"] == 0
    assert list(g["sensors_ms"]) == []


def test_zone_light_entity(tmp_path):
    _, groups, _ = frames(tmp_path, base_rows())
    assert groups.iloc[0]["zone_light_entity"] == "light.101_1"


def test_group_order_follows_table(tmp_path):
    """Порядок групп — как в таблице: наладчик сверяет отчёт со своим Excel."""
    rows = base_rows()
    rows.append({
        "Этаж": 1, "Шина DALI": 1, "Группа": "101_9", "Лампа": "1.1.8",
    })
    rows.append({
        "Этаж": 1, "Шина DALI": 1, "Группа": "101_3", "Лампа": "1.1.9",
    })

    _, groups, _ = frames(tmp_path, rows)
    assert groups["group_id"].tolist() == ["101_1", "101_9", "101_3"]


# ============================================================
# SPACES
# ============================================================

def test_general_light_entity_from_russian_name(tmp_path):
    rows = base_rows()
    rows[0]["Название помещения"] = "104_Методический кабинет"

    _, _, spaces = frames(tmp_path, rows)
    s = spaces.iloc[0]

    assert s["room_slug"] == "104_metodicheskii_kabinet"
    assert s["general_light_entity"] == "light.104_metodicheskii_kabinet_obshchii"


def test_sensors_by_group_is_aligned_with_groups(tmp_path):
    """
    sensors_by_group[i] относится к groups[i]. Пустой вложенный список —
    это группа без датчиков, а не пропуск.
    """
    rows = base_rows()
    rows.append({
        "Этаж": 1, "Шина DALI": 1, "Группа": "101_2", "Лампа": "1.1.8",
    })

    _, _, spaces = frames(tmp_path, rows)
    s = spaces.iloc[0]

    assert list(s["groups"]) == ["101_1", "101_2"]
    assert [list(x) for x in s["sensors_by_group"]] == [["sensor.ms_1_1_1"], []]


def test_space_without_type_is_kept(tmp_path):
    """
    Помещение без типа выпадает из карточек, но остаётся в parquet:
    лампы в нём физически существуют и должны попасть в группы света.
    """
    rows = base_rows()
    del rows[0]["Тип помещения"]

    devices, _, spaces = frames(tmp_path, rows)
    s = spaces.iloc[0]

    assert not s["has_valid_type"]
    assert "missing_space_type" in list(s["warnings"])
    assert len(devices[devices.kind == "lamp"]) == 2  # лампы на месте


def test_unknown_type_is_flagged(tmp_path):
    rows = base_rows()
    rows[0]["Тип помещения"] = "Corridor"  # опечатка: канон — Korridor

    _, _, spaces = frames(tmp_path, rows)
    s = spaces.iloc[0]

    assert not s["has_valid_type"]
    assert list(s["warnings"]) == ["unknown_space_type:corridor"]


# ============================================================
# ЗАПИСЬ НА ДИСК
# ============================================================

def test_normalize_writes_all_parquets(tmp_path, valid_xlsx):
    out = tmp_path / "normalized"
    meta = N.normalize(valid_xlsx, out)

    for name in ("devices", "groups", "spaces", "units"):
        assert (out / f"{name}.parquet").exists()

    assert meta["schema_version"] == 3
    assert meta["stats"]["lamps"] == 2


def test_stale_device_rows_is_removed(tmp_path, valid_xlsx):
    """
    device_rows.parquet — артефакт схемы v1. Если он останется, генератор
    может прочитать устаревшие данные и не заметить этого.
    """
    out = tmp_path / "normalized"
    out.mkdir()
    stale = out / "device_rows.parquet"
    stale.write_bytes(b"legacy")

    N.normalize(valid_xlsx, out)
    assert not stale.exists()


def test_meta_is_readable(tmp_path, valid_xlsx):
    out = tmp_path / "normalized"
    N.normalize(valid_xlsx, out)

    meta = json.loads((out / "normalized_meta.json").read_text(encoding="utf-8"))
    assert meta["sheet_name"] == N.SHEET_NAME
    assert meta["columns"]["devices"][:2] == ["row_id", "kind"]


# ============================================================
# ПРИЁМОЧНЫЙ ТЕСТ НА РЕАЛЬНОЙ ФИКСТУРЕ
# ============================================================

def test_object_example(tmp_path, object_example):
    meta = N.normalize(object_example, tmp_path / "normalized")
    s = meta["stats"]

    assert s == {
        "excel_rows": 91,
        "devices": 111,      # 91 лампа + 15 датчиков + 5 панелей
        "lamps": 91,
        "sensors": 15,
        "panels": 5,
        "groups": 16,
        "spaces": 8,
        "spaces_without_valid_type": 0,
        # hl_1 (2 тамбура, special) + 103_vestibiul + ladder_1 + 107_rekreatsiia
        # (все default) + 208_vkhodnoi_tambur (hall).
        # class и zal не автоматизируются — единиц не получают.
        "units": 5,
        # special=2; default=3 ×3 (103, ladder_1, 107); hall=3
        "scripts": 14,
        "automations": 10,   # ON + OFF на каждую единицу
    }


def test_object_example_group_102_keeps_both_sensors(tmp_path, object_example):
    """Регрессия на главный дефект v1: второй датчик группы терялся."""
    N.normalize(object_example, tmp_path / "normalized")
    groups = pd.read_parquet(tmp_path / "normalized" / "groups.parquet")

    g = groups[groups.group_id == "102_1"].iloc[0]
    assert list(g["sensors_ms"]) == ["sensor.ms_1_1_2", "sensor.ms_1_1_3"]


def test_object_example_zal_has_panels_but_no_sensors(tmp_path, object_example):
    N.normalize(object_example, tmp_path / "normalized")
    spaces = pd.read_parquet(tmp_path / "normalized" / "spaces.parquet")

    zal = spaces[spaces.space == "105_Актовый зал"].iloc[0]
    assert [list(x) for x in zal["sensors_by_group"]] == [[], []]
    assert [list(x) for x in zal["panels_by_group"]] == [["event.kp_1_2_1"], ["event.kp_1_2_2"]]


# ============================================================
# CLI
# ============================================================

def _main(monkeypatch, excel: Path, out: Path, *extra: str) -> int:
    argv = ["normalize_excel.py", "--excel", str(excel), "--out", str(out), *extra]
    monkeypatch.setattr("sys.argv", argv)
    return N.main()


def test_cli_ok(monkeypatch, tmp_path, valid_xlsx):
    assert _main(monkeypatch, valid_xlsx, tmp_path / "out") == 0


def test_cli_refuses_broken_table(monkeypatch, tmp_path):
    """
    Нормализовать таблицу с блокирующими ошибками нельзя: пайплайн не должен
    тихо врать — ошибки всплывут уже в Home Assistant.
    """
    rows = base_rows()
    rows[1]["Лампа"] = "1.1.1"  # дубликат адреса
    excel = build(tmp_path, rows)
    out = tmp_path / "out"

    assert _main(monkeypatch, excel, out) == 1
    assert not (out / "devices.parquet").exists()


def test_cli_force_overrides(monkeypatch, tmp_path):
    rows = base_rows()
    rows[1]["Лампа"] = "1.1.1"
    excel = build(tmp_path, rows)
    out = tmp_path / "out"

    assert _main(monkeypatch, excel, out, "--force") == 0
    assert (out / "devices.parquet").exists()


def test_cli_warnings_do_not_block(monkeypatch, tmp_path):
    rows = base_rows()
    del rows[0]["Тип помещения"]  # W01
    excel = build(tmp_path, rows)

    assert _main(monkeypatch, excel, tmp_path / "out") == 0


def test_cli_missing_file(monkeypatch, tmp_path):
    assert _main(monkeypatch, tmp_path / "нет.xlsx", tmp_path / "out") == 2
