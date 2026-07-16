# -*- coding: utf-8 -*-
"""
Клонирование шаблонных скриптов по единицам обслуживания.

Один экземпляр скрипта в HA — одна очередь. Клоны нужны, чтобы единицы
не ждали друг друга. Тела одинаковы; отличается только корневой ключ,
из которого HA делает entity_id.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

import pandas as pd
import pytest
import yaml

import generate_scripts as SCRIPTS
import normalize_excel as N
from conftest import make_book
from scripts._lib.canon import SCRIPTS_BY_FAMILY
from scripts._lib.filters import Filters
from scripts._lib.normalized import load_dataset

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "scripts"


def row(space=None, stype=None, block=None, floor=1, group="101_1",
        lamp="1.1.1", sensor=None, panel=None) -> Dict:
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


def generate(tmp_path: Path, rows: List[Dict], filters: Filters = None) -> dict:
    """Прогнать таблицу через normalize + generate_scripts, вернуть разобранный YAML."""
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)

    units = load_dataset(out, "units")
    text = SCRIPTS.build_yaml(units, TEMPLATES, filters or Filters())

    return yaml.safe_load(text) or {}


# ============================================================
# ШАБЛОНЫ
# ============================================================

@pytest.mark.parametrize("filename", sorted({
    f for roles in SCRIPTS_BY_FAMILY.values() for f in roles.values()
}))
def test_every_referenced_template_exists(filename):
    """Канон ссылается на файл — файл обязан быть в репозитории."""
    key, body = SCRIPTS.load_template(TEMPLATES, filename)

    assert key.startswith("shablon_")
    assert body[0] == f"{key}:"


def test_missing_template_is_explained(tmp_path):
    with pytest.raises(SCRIPTS.TemplateError, match="не найден"):
        SCRIPTS.load_template(tmp_path, "нет.yaml")


def test_template_without_root_key(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("# только комментарий\n", encoding="utf-8")

    with pytest.raises(SCRIPTS.TemplateError, match="корневой ключ"):
        SCRIPTS.load_template(tmp_path, "bad.yaml")


# ============================================================
# КЛОНИРОВАНИЕ
# ============================================================

def test_clone_replaces_root_key():
    _, body = SCRIPTS.load_template(TEMPLATES, "motion_on.yaml")
    lines = SCRIPTS.clone_script(body, "103_vestibiul", "on")

    assert lines[0] == "103_vestibiul_on:"
    assert not any("shablon_script" in line for line in lines)


def test_clone_sets_alias():
    """Без этого в UI Home Assistant было бы двести «Шаблон скрипта»."""
    _, body = SCRIPTS.load_template(TEMPLATES, "motion_on.yaml")
    lines = SCRIPTS.clone_script(body, "ladder_1", "on")

    assert any('alias: "ladder_1 — включение"' in line for line in lines)


def test_clone_keeps_body_intact():
    """Тело не трогаем: имён в нём нет, конфигурацию скрипт получает параметрами."""
    _, body = SCRIPTS.load_template(TEMPLATES, "motion_near_off_json.yaml")
    lines = SCRIPTS.clone_script(body, "u1", "near_off")

    original = [l for l in body[1:] if not l.strip().startswith("alias:")]
    cloned = [l for l in lines[1:] if not l.strip().startswith("alias:")]

    assert cloned == original


def test_clone_is_valid_yaml():
    _, body = SCRIPTS.load_template(TEMPLATES, "motion_on.yaml")
    text = "\n".join(SCRIPTS.clone_script(body, "u1", "on")) + "\n"

    doc = yaml.safe_load(text)
    assert "u1_on" in doc
    assert doc["u1_on"]["mode"] == "queued"


# ============================================================
# СОСТАВ НАБОРА ПО СЕМЕЙСТВАМ
# ============================================================

def test_default_family_gets_three_scripts(tmp_path):
    doc = generate(tmp_path, [
        row("101_Коридор", "Korridor", sensor="1.1.1", panel="None"),
    ])

    assert set(doc) == {
        "101_koridor_on", "101_koridor_off", "101_koridor_near_off",
    }


def test_special_family_gets_two_scripts(tmp_path):
    doc = generate(tmp_path, [
        row("110_Санузел", "Special", sensor="1.1.1", panel="None"),
    ])

    assert set(doc) == {"110_sanuzel_on", "110_sanuzel_off"}


def test_hall_family_gets_hall_near(tmp_path):
    doc = generate(tmp_path, [
        row("130_Холл", "Hall", sensor="1.1.1", panel="None"),
    ])

    assert "130_kholl_hall_near" in doc
    assert "130_kholl_near_off" not in doc


def test_class_and_zal_get_nothing(tmp_path):
    """Класс управляется панелью и поддержанием освещённости — вне охвата."""
    doc = generate(tmp_path, [
        row("101_Класс", "Class", group="101_1", lamp="1.1.1",
            sensor="1.1.1", panel="None"),
        row("102_Зал", "Zal", group="102_1", lamp="1.1.2",
            sensor="None", panel="1.1.1"),
    ])

    assert doc == {}


# ============================================================
# БЛОКИ
# ============================================================

def test_block_gets_one_set_for_all_its_spaces(tmp_path):
    """Два санузла в блоке — один набор скриптов, а не два."""
    doc = generate(tmp_path, [
        row("110_Санузел_Ж", "Special", block="wc_1", group="110_1",
            lamp="1.1.1", sensor="1.1.1", panel="None"),
        row("111_Санузел_М", "Special", block="wc_1", group="111_1",
            lamp="1.1.2", sensor="1.1.2", panel="None"),
    ])

    assert set(doc) == {"wc_1_on", "wc_1_off"}


def test_corridors_get_separate_sets(tmp_path):
    """Коридоры не склеиваются: у каждого своя очередь."""
    doc = generate(tmp_path, [
        row("101_Коридор", "Korridor", group="101_1", lamp="1.1.1",
            sensor="1.1.1", panel="None"),
        row("102_Коридор", "Korridor", group="102_1", lamp="1.1.2",
            sensor="1.1.2", panel="None"),
    ])

    assert "101_koridor_on" in doc
    assert "102_koridor_on" in doc


# ============================================================
# ПРИЁМОЧНЫЙ ТЕСТ
# ============================================================

@pytest.fixture
def object_layer(tmp_path, object_example) -> Path:
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


def test_object_example(object_layer):
    units = load_dataset(object_layer, "units")
    text = SCRIPTS.build_yaml(units, TEMPLATES, Filters())
    doc = yaml.safe_load(text)

    assert set(doc) == {
        "hl_1_on", "hl_1_off",                                            # special
        "103_vestibiul_on", "103_vestibiul_off", "103_vestibiul_near_off",
        "ladder_1_on", "ladder_1_off", "ladder_1_near_off",
        # рекреация — то же семейство default, что и коридор
        "107_rekreatsiia_on", "107_rekreatsiia_off", "107_rekreatsiia_near_off",
        # холл — своё семейство: вместо near_off у него hall_near
        "208_vkhodnoi_tambur_on", "208_vkhodnoi_tambur_off",
        "208_vkhodnoi_tambur_hall_near",
    }


def test_no_duplicate_keys(object_layer):
    """
    YAML молча затирает дубликат ключа: два скрипта с одним именем дали бы
    один рабочий и один потерянный. Проверяем по тексту, а не по разобранному
    документу — тот дубликаты уже проглотил.
    """
    units = load_dataset(object_layer, "units")
    text = SCRIPTS.build_yaml(units, TEMPLATES, Filters())

    keys = re.findall(r"^([a-z0-9_]+):$", text, re.M)
    assert len(keys) == len(set(keys))


def test_names_match_units_parquet(object_layer):
    """Имена скриптов должны совпадать с тем, что обещал normalize:
    на них будут ссылаться автоматизации."""
    units = load_dataset(object_layer, "units")
    text = SCRIPTS.build_yaml(units, TEMPLATES, Filters())
    doc = yaml.safe_load(text)

    promised = {s.replace("script.", "") for lst in units["scripts"] for s in lst}
    assert set(doc) == promised


# ============================================================
# ФИЛЬТРЫ И CLI
# ============================================================

def test_filter_by_space(object_layer):
    units = load_dataset(object_layer, "units")
    text = SCRIPTS.build_yaml(units, TEMPLATES, Filters(spaces=["103_Вестибюль"]))
    doc = yaml.safe_load(text)

    assert set(doc) == {
        "103_vestibiul_on", "103_vestibiul_off", "103_vestibiul_near_off",
    }


def test_filter_keeps_whole_block(object_layer):
    """
    Блок нельзя разорвать фильтром: скрипты клонируются на единицу целиком.
    Фильтр по одному из тамбуров оставляет весь блок hl_1.
    """
    units = load_dataset(object_layer, "units")
    text = SCRIPTS.build_yaml(units, TEMPLATES, Filters(spaces=["101_Тамбур"]))
    doc = yaml.safe_load(text)

    assert set(doc) == {"hl_1_on", "hl_1_off"}


def test_empty_result_is_commented(object_layer):
    units = load_dataset(object_layer, "units")
    text = SCRIPTS.build_yaml(units, TEMPLATES, Filters(spaces=["нет такого"]))

    assert text.startswith("#")
    assert yaml.safe_load(text) is None


def test_cli(monkeypatch, tmp_path, object_layer):
    out = tmp_path / "scripts.yaml"
    monkeypatch.setattr("sys.argv", [
        "generate_scripts.py",
        "--normalized", str(object_layer),
        "--templates", str(TEMPLATES),
        "--out", str(out),
    ])

    assert SCRIPTS.main() == 0

    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(doc) == 14   # special 2 + default 3×3 + hall 3


def test_cli_without_normalized_layer(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", [
        "generate_scripts.py",
        "--normalized", str(tmp_path / "нет"),
        "--out", str(tmp_path / "o.yaml"),
    ])

    assert SCRIPTS.main() == 2


def test_cli_without_templates(monkeypatch, tmp_path, object_layer):
    monkeypatch.setattr("sys.argv", [
        "generate_scripts.py",
        "--normalized", str(object_layer),
        "--templates", str(tmp_path / "нет"),
        "--out", str(tmp_path / "o.yaml"),
    ])

    assert SCRIPTS.main() == 2
