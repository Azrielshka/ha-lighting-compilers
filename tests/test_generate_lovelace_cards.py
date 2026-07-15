# -*- coding: utf-8 -*-
"""
Генератор карточек Lovelace (v3). У каждого space_type своя раскладка.

Шаг офлайновый: к HA не подключается, собирает текст карточек для дашборда.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import generate_lovelace_cards as G
import normalize_excel as N
from conftest import make_book
from scripts._lib.filters import Filters


# ============================================================
# Блоки-плитки (реальные из templates/lovelace/_blocks)
# ============================================================

@pytest.fixture(scope="module")
def blocks() -> dict:
    return {name: G._load_block(G.DEFAULT_TEMPLATES_DIR, name) for name in G.BLOCK_NAMES}


def _lights(n):
    return [f"light.z_{i}" for i in range(n)]


def _one_sensor_each(n):
    return [[f"sensor.ms_{i}"] for i in range(n)]


# ============================================================
# balanced_sizes — балансная нарезка (без одинокого хвоста)
# ============================================================

@pytest.mark.parametrize("n,expected", [
    (1, [1]),
    (3, [3]),
    (4, [2, 2]),      # не [3, 1]
    (5, [3, 2]),
    (6, [3, 3]),
    (7, [3, 2, 2]),   # не [3, 3, 1]
    (8, [3, 3, 2]),
    (9, [3, 3, 3]),
])
def test_balanced_sizes(n, expected):
    assert G.balanced_sizes(n) == expected
    assert sum(G.balanced_sizes(n)) == n
    assert all(s <= G.ZONES_PER_GRID for s in G.balanced_sizes(n))


# ============================================================
# korridor — сетки-тройки, пары свет|датчик, перенос по рядам
# ============================================================

def test_korridor_single_grid_no_stack(blocks):
    """≤3 зон → одна сетка, без horizontal-stack (во всю ширину, как эталон)."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(3), _one_sensor_each(3))
    assert len(res) == 1
    assert res[0]["type"] == "grid"
    # 2 заголовка + 3 пары = 8 карточек
    assert len(res[0]["cards"]) == 2 + 3 * 2


def test_korridor_4_zones_balanced(blocks):
    """4 зоны → [2,2]: две сетки в одном horizontal-stack."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(4), _one_sensor_each(4))
    assert len(res) == 1                       # один ряд
    assert res[0]["type"] == "horizontal-stack"
    grids = res[0]["cards"]
    assert len(grids) == 2
    # каждая сетка: 2 заголовка + 2 пары
    assert all(len(g["cards"]) == 2 + 2 * 2 for g in grids)


def test_korridor_9_zones_wraps_and_pads(blocks):
    """9 зон → 3 сетки [3,3,3], макс 2 в ряд → 2 ряда, добор пустой карточкой."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(9), _one_sensor_each(9))
    assert len(res) == 2                        # два ряда
    assert res[0]["cards"][0]["type"] == "grid"
    assert len(res[0]["cards"]) == 2            # первый ряд — 2 сетки
    # второй ряд: сетка + заглушка-добор (чтобы не растягивалась)
    assert len(res[1]["cards"]) == 2
    assert res[1]["cards"][0]["type"] == "grid"
    assert res[1]["cards"][1]["type"] == "markdown"


def test_korridor_zero_sensor_is_spacer(blocks):
    """Зона без датчика → пустая ячейка (пары не сбиваются)."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(1), [[]])
    cards = res[0]["cards"]
    sensor_cell = cards[3]                       # [заг, заг, свет, датчик]
    assert sensor_cell["type"] == "markdown"
    assert sensor_cell["content"] == ""


def test_korridor_multi_sensor_stacked(blocks):
    """Зона с >1 датчиком → датчики стопкой в одной ячейке (пара сохраняется)."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(1), [["sensor.a", "sensor.b"]])
    sensor_cell = res[0]["cards"][3]
    assert sensor_cell["type"] == "vertical-stack"
    assert len(sensor_cell["cards"]) == 2


# ============================================================
# special / class / recreation / zal — специфика типов
# ============================================================

def test_special_pairs(blocks):
    res = G.build_special(blocks["light_tile"], blocks["sensor_tile"],
                          _lights(2), [["sensor.a", "sensor.b"], ["sensor.c"]])
    assert all(r["type"] == "horizontal-stack" for r in res)
    # первая зона: свет + 2 датчика
    assert len(res[0]["cards"]) == 3
    assert len(res[1]["cards"]) == 2


def test_class_columns_order_and_placeholder(blocks):
    res = G.build_class_columns(blocks["light_tile"], blocks["sensor_tile"],
                                blocks["class_label"], _lights(2), _one_sensor_each(2))
    # порядок: свет, свет, датчик, датчик, подпись, подпись
    assert [c["type"] for c in res] == ["tile", "tile", "tile", "tile", "markdown", "markdown"]
    assert res[-1]["content"] == G.LABEL_PLACEHOLDER


def test_recreation_groups_are_mushroom(blocks):
    res = G.build_recreation_groups(blocks["recreation_group"], _lights(2))
    assert all(c["type"] == "custom:mushroom-light-card" for c in res)
    assert res[0]["entity"] == "light.z_0"


def test_zal_lights_have_toggle_and_vertical():
    res = G.build_zal_lights(["light.a", "light.b"])
    assert all(c["vertical"] is True for c in res)
    assert all({"type": "toggle"} in c["features"] for c in res)


# ============================================================
# Интеграция на объектной фикстуре: всё собирается и валидно
# ============================================================

@pytest.fixture
def object_layer(tmp_path, object_example) -> Path:
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


def _generate(object_layer, tmp_path) -> str:
    txt = tmp_path / "cards.txt"
    G.generate_cards(
        spaces_parquet=object_layer / "spaces.parquet",
        templates_dir=G.DEFAULT_TEMPLATES_DIR,
        output_txt=txt,
        report_json=tmp_path / "report.json",
        filters=Filters(),
    )
    return txt.read_text(encoding="utf-8")


def test_all_cards_are_valid_yaml(object_layer, tmp_path):
    text = _generate(object_layer, tmp_path)
    blocks = text.split("# ─── ")[1:]
    assert blocks, "ни одной карточки не собрано"
    for b in blocks:
        body = b.split("\n", 1)[1]
        yaml.safe_load(body)          # упадёт, если YAML битый


def test_zal_presets_survive_generation(object_layer, tmp_path):
    """Хардкод-пресеты зала не теряются при сборке."""
    text = _generate(object_layer, tmp_path)
    assert "input_boolean.rezhim_tetra" in text
    assert "custom:mushroom-template-card" in text


def test_space_without_valid_type_skipped(tmp_path):
    """Помещение без валидного типа карточку не получает (W01)."""
    rows = [
        {"Этаж": 1, "Название помещения": "201_Никакой", "Тип помещения": "None",
         "Шина DALI": 1, "Группа": "201_1", "Лампа": "1.1.1",
         "Датчик": "1.1.1", "Панель": "None"},
    ]
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)
    text = _generate(out, tmp_path)
    assert text.strip() == ""          # карточек нет
