# -*- coding: utf-8 -*-
"""
Схема parquet не должна зависеть от того, что оказалось в таблице.

Регрессия на реальный баг: pa.Table.from_pandas() выводил типы из данных,
и на объекте без единой панели panels_by_group получал тип list<list<null>>
вместо list<list<string>>. Сломалось бы это не у нас, а у наладчика.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import normalize_excel as N
from conftest import base_rows, make_book
from scripts._lib.normalized import (
    NormalizedLayerError,
    load_dataset,
    load_normalized,
)
from scripts._lib.schemas import DATASET_NAMES, SCHEMAS


def _rich_rows():
    """Таблица, где есть всё: панели, датчики, корректные типы."""
    return [
        {
            "Этаж": 1, "Название помещения": "101_Тамбур", "Тип помещения": "Class",
            "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.1",
            "Датчик": "1.1.1", "Панель": "1.1.1",
        },
        {"Этаж": 1, "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.2", "Датчик": "1.1.2"},
    ]


def _bare_rows():
    """Голый минимум: ни панелей, ни датчиков, ни типа помещения."""
    rows = base_rows()
    del rows[0]["Тип помещения"]
    rows[0]["Датчик"] = "None"
    return rows


@pytest.fixture
def rich(tmp_path) -> Path:
    out = tmp_path / "rich"
    N.normalize(make_book(tmp_path / "rich.xlsx", _rich_rows()), out)
    return out


@pytest.fixture
def bare(tmp_path) -> Path:
    out = tmp_path / "bare"
    N.normalize(make_book(tmp_path / "bare.xlsx", _bare_rows()), out)
    return out


# ============================================================
# СТАБИЛЬНОСТЬ СХЕМЫ
# ============================================================

@pytest.mark.parametrize("name", DATASET_NAMES)
def test_schema_identical_across_tables(name, rich, bare):
    """Богатая и бедная таблицы должны дать побайтово одинаковую схему."""
    a = pq.read_schema(rich / f"{name}.parquet")
    b = pq.read_schema(bare / f"{name}.parquet")

    assert a.names == b.names
    for field in a.names:
        assert a.field(field).type == b.field(field).type, f"{name}.{field} разъехался"


@pytest.mark.parametrize("name", DATASET_NAMES)
def test_written_schema_matches_declared(name, bare):
    """Файл на диске соответствует schemas.py — единственному источнику правды."""
    actual = pq.read_schema(bare / f"{name}.parquet")
    declared = SCHEMAS[name]

    assert actual.names == declared.names
    for field in declared.names:
        assert actual.field(field).type == declared.field(field).type


def test_empty_panels_stay_strings(bare):
    """
    Тот самый баг: без единой панели тип был list<list<null>>.
    Генератор автоматизаций получил бы список пустот вместо списка строк.
    """
    schema = pq.read_schema(bare / "spaces.parquet")

    assert schema.field("panels_by_group").type == pa.list_(pa.list_(pa.string()))
    assert schema.field("sensors_by_group").type == pa.list_(pa.list_(pa.string()))


def test_empty_warnings_stay_strings(rich):
    """Без предупреждений тип был list<null>."""
    schema = pq.read_schema(rich / "spaces.parquet")
    assert schema.field("warnings").type == pa.list_(pa.string())


def test_absent_space_type_stays_string(bare):
    """Когда тип не указан ни у одного помещения, колонка была null."""
    schema = pq.read_schema(bare / "spaces.parquet")
    assert schema.field("space_type").type == pa.string()


def test_lamp_entity_id_2_is_null_but_typed(rich):
    """У лампы нет второй сущности — значение null, но тип по-прежнему string."""
    schema = pq.read_schema(rich / "devices.parquet")
    assert schema.field("entity_id_2").type == pa.string()

    devices = pd.read_parquet(rich / "devices.parquet")
    lamp = devices[devices.kind == "lamp"].iloc[0]
    assert pd.isna(lamp["entity_id_2"])


# ============================================================
# ЧТЕНИЕ СЛОЯ
# ============================================================

def test_load_normalized(rich):
    layer = load_normalized(rich)

    assert len(layer.devices) == 5   # 2 лампы + 2 датчика + 1 панель
    assert len(layer.groups) == 1
    assert len(layer.spaces) == 1


def test_load_missing_layer_explains_what_to_do(tmp_path):
    with pytest.raises(NormalizedLayerError, match="normalize_excel.py"):
        load_normalized(tmp_path / "нет")


def test_load_rejects_stale_schema(tmp_path, rich):
    """
    Parquet от старой версии normalize должен быть отвергнут внятно,
    а не приводить к странному поведению генератора.
    """
    stale = tmp_path / "stale"
    stale.mkdir()

    # Файл со старой схемой: колонки те же, но panels_by_group — список чисел.
    bad = pa.table({"space": ["101"], "panels_by_group": [[[1, 2]]]})
    pq.write_table(bad, stale / "spaces.parquet")

    with pytest.raises(NormalizedLayerError, match="нет колонок|не совпадают"):
        load_dataset(stale, "spaces")


def test_unknown_dataset_name(rich):
    with pytest.raises(ValueError, match="неизвестный датасет"):
        load_dataset(rich, "lamps")
