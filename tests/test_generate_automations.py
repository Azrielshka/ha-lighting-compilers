# -*- coding: utf-8 -*-
"""
Автоматизации — экземпляры blueprint'ов.

Главная проверка: иерархия замкнута. Каждая автоматизация ссылается на
скрипт, который реально создан generate_scripts, и на blueprint, который
реально лежит в репозитории. Ссылка в пустоту не падает — автоматизация
просто не загрузится, и свет не включится.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd
import pytest
import yaml

import generate_automations as AUTO
import generate_scripts as SCRIPTS
import normalize_excel as N
from conftest import make_book
from scripts._lib.canon import (
    BLUEPRINT_INPUTS_BY_FAMILY,
    BLUEPRINTS_BY_FAMILY,
    SCRIPTS_BY_FAMILY,
    VACANT_DELAY_ENTITY,
    ba_gate_entity,
)
from scripts._lib.filters import Filters
from scripts._lib.normalized import load_dataset

REPO = Path(__file__).resolve().parent.parent
BLUEPRINTS = REPO / "templates" / "blueprints"
SCRIPT_TEMPLATES = REPO / "templates" / "scripts"


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


def automations(tmp_path: Path, rows: List[Dict], filters: Filters = None) -> List[dict]:
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)

    units = load_dataset(out, "units")
    text = AUTO.build_yaml(units, filters or Filters(), AUTO.BLUEPRINT_DIR)
    doc = yaml.safe_load(text)

    # Файл — голый список: !include_dir_merge_list ждёт именно его.
    return doc if doc else []


def test_unit_without_sensors_yields_comment_not_empty_list(tmp_path):
    """
    Пустой `automation:` без списка YAML разбирает как None, и HA спотыкается
    о пакет. Отдаём комментарий, а не сломанную структуру.
    """
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", [
        row("101_Коридор", "Korridor", sensor="None", panel="None"),
    ]), out)

    text = AUTO.build_yaml(load_dataset(out, "units"), Filters(), AUTO.BLUEPRINT_DIR)

    assert text.startswith("#")
    assert yaml.safe_load(text) is None


@pytest.fixture
def object_layer(tmp_path, object_example) -> Path:
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


def inputs_of(auto: dict) -> dict:
    return auto["use_blueprint"]["input"]


class BlueprintLoader(yaml.SafeLoader):
    """
    Blueprint'ы держатся на теге !input, которого safe_load не знает.
    Для наших проверок содержимое тега не нужно — достаточно не падать.
    """


BlueprintLoader.add_constructor(
    "!input", lambda loader, node: f"!input {node.value}"
)


def load_blueprint(filename: str) -> dict:
    return yaml.load((BLUEPRINTS / filename).read_text(encoding="utf-8"), BlueprintLoader)


# ============================================================
# ФОРМАТ ФАЙЛА
# ============================================================

def test_file_is_a_bare_list(object_layer):
    """
    Файл кладётся в includes/automations/, подключённую через
    !include_dir_merge_list — она ждёт СПИСОК. Домен automation: в Home
    Assistant списком и является.

    Обёртка вида `zm_automations:` / `automation:` здесь недопустима:
    с ней HA файл не подхватит.
    """
    units = load_dataset(object_layer, "units")
    doc = yaml.safe_load(AUTO.build_yaml(units, Filters(), AUTO.BLUEPRINT_DIR))

    assert isinstance(doc, list)
    assert all("id" in a and "use_blueprint" in a for a in doc)


def test_scripts_file_is_a_mapping(object_layer):
    """
    Зеркальная проверка: scripts.yaml идёт в includes/scripts/ через
    !include_dir_merge_named — там, наоборот, нужен СЛОВАРЬ
    `object_id -> скрипт`. Перепутать эти два формата — значит получить
    конфигурацию, которую HA не загрузит.
    """
    units = load_dataset(object_layer, "units")
    doc = yaml.safe_load(SCRIPTS.build_yaml(units, SCRIPT_TEMPLATES, Filters()))

    assert isinstance(doc, dict)


# ============================================================
# КАНОН
# ============================================================

@pytest.mark.parametrize("family", sorted(BLUEPRINTS_BY_FAMILY))
def test_every_blueprint_file_exists(family):
    """Канон ссылается на файл — файл обязан лежать в репозитории."""
    for role, filename in BLUEPRINTS_BY_FAMILY[family].items():
        assert (BLUEPRINTS / filename).exists(), f"{family}/{role}: {filename}"


@pytest.mark.parametrize("family", sorted(BLUEPRINT_INPUTS_BY_FAMILY))
def test_blueprint_inputs_match_actual_blueprint(family):
    """
    Входы, которые мы подставляем, должны существовать в самом blueprint'е.
    Опечатка в имени входа не уронит генерацию — HA просто проигнорирует
    вход, и автоматизация окажется без скрипта.
    """
    for role, our_inputs in BLUEPRINT_INPUTS_BY_FAMILY[family].items():
        filename = BLUEPRINTS_BY_FAMILY[family][role]
        declared = set(load_blueprint(filename)["blueprint"]["input"])

        for name in our_inputs:
            assert name in declared, f"{filename}: нет входа {name!r}"


@pytest.mark.parametrize("family", sorted(BLUEPRINT_INPUTS_BY_FAMILY))
def test_referenced_script_roles_exist(family):
    """Вход требует роль скрипта — эта роль должна клонироваться для семейства."""
    roles = set(SCRIPTS_BY_FAMILY[family])

    for role_inputs in BLUEPRINT_INPUTS_BY_FAMILY[family].values():
        for source in role_inputs.values():
            # Спец-источники — не роли скриптов: sensors (список датчиков),
            # vacant_delay (общий helper), gate (гейт Оркестратора по этажу).
            if source in ("sensors", "vacant_delay", "gate"):
                continue
            assert source in roles, f"{family}: роль {source!r} не клонируется"


def test_special_off_takes_one_script():
    """
    У special OFF вход ОДИН (off_script), у default и hall — два
    (off_script_1 + off_script_2). Имена входов различаются.
    """
    special = BLUEPRINT_INPUTS_BY_FAMILY["special"]["off"]
    default = BLUEPRINT_INPUTS_BY_FAMILY["default"]["off"]

    assert [k for k in special if k.startswith("off_script")] == ["off_script"]
    assert [k for k in default if k.startswith("off_script")] == [
        "off_script_1", "off_script_2",
    ]


# ============================================================
# СТРУКТУРА АВТОМАТИЗАЦИИ
# ============================================================

def test_two_automations_per_unit(tmp_path):
    auto = automations(tmp_path, [
        row("101_Коридор", "Korridor", sensor="1.1.1", panel="None"),
    ])

    assert [a["id"] for a in auto] == ["zm_101_koridor_on", "zm_101_koridor_off"]


def test_on_automation(tmp_path):
    auto = automations(tmp_path, [
        row("101_Коридор", "Korridor", sensor="1.1.1", panel="None"),
    ])
    on = auto[0]

    assert on["use_blueprint"]["path"] == "zone_manager/zm_default_on.yaml"
    assert inputs_of(on)["motion_sensors"] == ["sensor.ms_1_1_1"]
    assert inputs_of(on)["on_script"] == "script.101_koridor_on"


def test_off_automation_default(tmp_path):
    auto = automations(tmp_path, [
        row("101_Коридор", "Korridor", sensor="1.1.1", panel="None"),
    ])
    off = auto[1]
    inp = inputs_of(off)

    assert inp["vacant_delay_input"] == VACANT_DELAY_ENTITY
    assert inp["off_script_1"] == "script.101_koridor_off"
    assert inp["off_script_2"] == "script.101_koridor_near_off"


def test_off_automation_special_has_single_script(tmp_path):
    auto = automations(tmp_path, [
        row("110_Санузел", "Special", sensor="1.1.1", panel="None"),
    ])
    inp = inputs_of(auto[1])

    assert inp["off_script"] == "script.110_sanuzel_off"
    assert "off_script_1" not in inp


def test_off_automation_hall_uses_hall_near(tmp_path):
    auto = automations(tmp_path, [
        row("130_Холл", "Hall", sensor="1.1.1", panel="None"),
    ])
    inp = inputs_of(auto[1])

    assert inp["off_script_2"] == "script.130_kholl_hall_near"


def test_block_gets_one_pair_of_automations(tmp_path):
    """Блок из двух санузлов — одна пара автоматизаций, а не две."""
    auto = automations(tmp_path, [
        row("110_Санузел_Ж", "Special", block="wc_1", group="110_1",
            lamp="1.1.1", sensor="1.1.1", panel="None"),
        row("111_Санузел_М", "Special", block="wc_1", group="111_1",
            lamp="1.1.2", sensor="1.1.2", panel="None"),
    ])

    assert [a["id"] for a in auto] == ["zm_wc_1_on", "zm_wc_1_off"]
    # Датчики обоих помещений — в одной автоматизации.
    assert inputs_of(auto[0])["motion_sensors"] == [
        "sensor.ms_1_1_1", "sensor.ms_1_1_2",
    ]


def test_class_and_zal_get_no_automations(tmp_path):
    auto = automations(tmp_path, [
        row("101_Класс", "Class", group="101_1", lamp="1.1.1",
            sensor="1.1.1", panel="None"),
        row("102_Зал", "Zal", group="102_1", lamp="1.1.2",
            sensor="None", panel="1.1.1"),
    ])

    assert auto == []


def test_unit_without_sensors_is_skipped(tmp_path):
    """Автоматизация без датчиков не имеет триггеров — она мертва."""
    auto = automations(tmp_path, [
        row("101_Коридор", "Korridor", sensor="None", panel="None"),
    ])

    assert auto == []


# ============================================================
# ЗАМКНУТОСТЬ ИЕРАРХИИ
# ============================================================

def test_no_dangling_script_references(object_layer):
    """
    Каждая ссылка на скрипт ведёт на скрипт, который реально создаст
    generate_scripts. Ссылка в пустоту не падает: HA просто не вызовет
    ничего, и свет не включится.
    """
    units = load_dataset(object_layer, "units")

    auto_doc = yaml.safe_load(AUTO.build_yaml(units, Filters(), AUTO.BLUEPRINT_DIR))
    scripts_doc = yaml.safe_load(SCRIPTS.build_yaml(units, SCRIPT_TEMPLATES, Filters()))

    created = {f"script.{key}" for key in scripts_doc}

    referenced = {
        value
        for a in auto_doc
        for value in inputs_of(a).values()
        if isinstance(value, str) and value.startswith("script.")
    }

    assert referenced <= created
    assert referenced == created  # и наоборот: лишних скриптов не клонируем


def test_blueprint_paths_point_at_real_files(object_layer):
    units = load_dataset(object_layer, "units")
    doc = yaml.safe_load(AUTO.build_yaml(units, Filters(), AUTO.BLUEPRINT_DIR))

    for a in doc:
        filename = a["use_blueprint"]["path"].split("/")[-1]
        assert (BLUEPRINTS / filename).exists()


def test_sensors_match_units_parquet(object_layer):
    units = load_dataset(object_layer, "units")
    doc = yaml.safe_load(AUTO.build_yaml(units, Filters(), AUTO.BLUEPRINT_DIR))

    by_id = {a["id"]: a for a in doc}

    for _, unit in units.iterrows():
        on = by_id[f"zm_{unit['unit_id']}_on"]
        assert inputs_of(on)["motion_sensors"] == list(unit["sensors_ms"])


def test_ids_are_unique(object_layer):
    units = load_dataset(object_layer, "units")
    doc = yaml.safe_load(AUTO.build_yaml(units, Filters(), AUTO.BLUEPRINT_DIR))

    ids = [a["id"] for a in doc]
    assert len(ids) == len(set(ids))


def test_object_example(object_layer):
    units = load_dataset(object_layer, "units")
    doc = yaml.safe_load(AUTO.build_yaml(units, Filters(), AUTO.BLUEPRINT_DIR))

    ids = {a["id"] for a in doc}
    assert ids == {
        "zm_hl_1_on", "zm_hl_1_off",
        "zm_103_vestibiul_on", "zm_103_vestibiul_off",
        "zm_ladder_1_on", "zm_ladder_1_off",
        "zm_107_rekreatsiia_on", "zm_107_rekreatsiia_off",
        "zm_208_vkhodnoi_tambur_on", "zm_208_vkhodnoi_tambur_off",
    }


# ============================================================
# КОПИИ BLUEPRINT'ОВ ДЛЯ ДЕПЛОЯ
# ============================================================

def test_blueprints_are_copied(tmp_path):
    """Без файлов на HA автоматизации не загрузятся вовсе."""
    out = tmp_path / "blueprints"
    copied = AUTO.copy_blueprints(BLUEPRINTS, out)

    assert len(copied) == 6
    for filename in copied:
        assert (out / filename).exists()


def test_blueprints_copied_verbatim(tmp_path):
    """Копируем как есть: blueprint'ы одинаковы на всех объектах."""
    out = tmp_path / "blueprints"
    AUTO.copy_blueprints(BLUEPRINTS, out)

    original = (BLUEPRINTS / "zm_default_on.yaml").read_bytes()
    assert (out / "zm_default_on.yaml").read_bytes() == original


def test_missing_blueprints_are_explained(tmp_path):
    with pytest.raises(AUTO.BlueprintError, match="не найдены"):
        AUTO.copy_blueprints(tmp_path / "нет", tmp_path / "out")


# ============================================================
# ФИЛЬТРЫ И CLI
# ============================================================

def test_filter_keeps_whole_block(object_layer):
    units = load_dataset(object_layer, "units")
    text = AUTO.build_yaml(units, Filters(spaces=["101_Тамбур"]), AUTO.BLUEPRINT_DIR)
    doc = yaml.safe_load(text)

    ids = {a["id"] for a in doc}
    assert ids == {"zm_hl_1_on", "zm_hl_1_off"}


def test_empty_result_is_commented(object_layer):
    units = load_dataset(object_layer, "units")
    text = AUTO.build_yaml(units, Filters(spaces=["нет такого"]), AUTO.BLUEPRINT_DIR)

    assert text.startswith("#")
    assert yaml.safe_load(text) is None


def test_custom_blueprint_dir(object_layer):
    units = load_dataset(object_layer, "units")
    doc = yaml.safe_load(AUTO.build_yaml(units, Filters(), "my_dir"))

    paths = {a["use_blueprint"]["path"] for a in doc}
    assert all(p.startswith("my_dir/") for p in paths)


def test_cli(monkeypatch, tmp_path, object_layer):
    out = tmp_path / "automations.yaml"
    bp_out = tmp_path / "blueprints"

    monkeypatch.setattr("sys.argv", [
        "generate_automations.py",
        "--normalized", str(object_layer),
        "--templates", str(BLUEPRINTS),
        "--out", str(out),
        "--blueprints-out", str(bp_out),
    ])

    assert AUTO.main() == 0

    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(doc) == 10   # ON + OFF на каждую из 5 единиц
    assert (bp_out / "zm_default_on.yaml").exists()


def test_cli_without_normalized_layer(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", [
        "generate_automations.py",
        "--normalized", str(tmp_path / "нет"),
        "--out", str(tmp_path / "o.yaml"),
    ])

    assert AUTO.main() == 2


# ============================================================
# ГЕЙТ ОРКЕСТРАТОРА ЗДАНИЯ
# ============================================================
#
# Гейт разрешает работу датчиков на этаже. Разбор поведения HA и согласование
# конструкции — docs/internal/contract-answer-01-gate.md. Здесь проверяем ровно
# то, что ломается молча: fail-open именно шаблоном, гейт в обоих ролях,
# правильный этаж у многоэтажной единицы.

ALL_BLUEPRINTS = sorted(f.name for f in BLUEPRINTS.glob("zm_*.yaml"))


@pytest.mark.parametrize("filename", ALL_BLUEPRINTS)
def test_blueprint_gate_condition_is_failopen_template(filename):
    """
    ⚠ Сердце правки. Условие обязано быть шаблоном `states(...) != 'off'`:

      • condition:state на отсутствующей сущности бросает ошибку, not её не
        глотает, автоматизация падает в fail-closed — гасит весь объект;
      • has_value() даёт False на unavailable/unknown — тоже fail-closed.

    Тест ловит обе ловушки: разрешает только голый states(...) != 'off'.
    """
    bp = load_blueprint(filename)

    conditions = bp.get("condition")
    assert conditions, f"{filename}: у blueprint пропал верхнеуровневый condition"

    first = conditions[0]
    assert first["condition"] == "template", f"{filename}: гейт не template"

    tmpl = first["value_template"]
    assert "states(ba_gate_entity)" in tmpl
    assert "!= 'off'" in tmpl
    assert "has_value" not in tmpl, f"{filename}: has_value ломает fail-open"
    assert "== 'on'" not in tmpl, f"{filename}: == 'on' ломает fail-open"


@pytest.mark.parametrize("filename", ALL_BLUEPRINTS)
def test_blueprint_declares_gate_input(filename):
    """Вход есть, домен — binary_sensor, и он БЕЗ default: значение всегда даёт генератор."""
    bp = load_blueprint(filename)
    inp = bp["blueprint"]["input"]

    assert "ba_gate_entity" in inp, f"{filename}: нет входа ba_gate_entity"
    assert "default" not in inp["ba_gate_entity"], \
        f"{filename}: у гейта не должно быть default"

    selector = inp["ba_gate_entity"]["selector"]["entity"]
    assert selector["filter"]["domain"] == "binary_sensor"


@pytest.mark.parametrize("filename", ALL_BLUEPRINTS)
def test_blueprint_forwards_input_through_variables(filename):
    """
    !input внутри value_template не разворачивается — обязателен проброс через
    variables. Без него шаблон читал бы states по несуществующей переменной.
    """
    bp = load_blueprint(filename)
    variables = bp.get("variables") or {}

    # BlueprintLoader подменяет тег на строку "!input ba_gate_entity".
    assert variables.get("ba_gate_entity") == "!input ba_gate_entity", \
        f"{filename}: variables не пробрасывает !input ba_gate_entity"


def test_gate_present_in_both_roles(tmp_path):
    """
    ⚠ Гейт нужен и в ON, и в OFF. Иначе в режиме «датчики запрещены, свет
    статически на 100 %» OFF по таймауту вакансии всё равно погасил бы его.
    """
    auto = automations(tmp_path, [
        row("101_Коридор", "Korridor", sensor="1.1.1", panel="None"),
    ])

    on, off = auto[0], auto[1]
    assert inputs_of(on)["ba_gate_entity"] == ba_gate_entity(1)
    assert inputs_of(off)["ba_gate_entity"] == ba_gate_entity(1)


def test_gate_uses_unit_floor(tmp_path):
    """Гейт указывает на этаж единицы, а не на объект целиком."""
    auto = automations(tmp_path, [
        row("205_Зал", "Korridor", floor=2, group="205_1", lamp="1.2.1",
            sensor="1.2.1", panel="None"),
    ])

    assert inputs_of(auto[0])["ba_gate_entity"] == \
        "binary_sensor.building_automation_sensors_allowed_floor_2"


def test_gate_multifloor_unit_takes_min_floor(tmp_path):
    """
    Единица через лестничный стояк живёт на двух этажах, а гейт один. Берём
    минимальный этаж — детерминированно.
    """
    auto = automations(tmp_path, [
        row("101_Лестница", "Korridor", block="stair", floor=1,
            group="101_1", lamp="1.1.1", sensor="1.1.1", panel="None"),
        row("201_Лестница", "Korridor", block="stair", floor=2,
            group="201_1", lamp="1.2.1", sensor="1.2.1", panel="None"),
    ])

    # Одна единица (блок) → одна пара автоматизаций.
    assert len(auto) == 2
    for a in auto:
        assert inputs_of(a)["ba_gate_entity"] == ba_gate_entity(1)


def test_gate_multifloor_warns(tmp_path, capsys):
    """О многоэтажной единице генератор обязан предупредить — молча выбирать
    этаж нельзя, наладчик должен проверить."""
    automations(tmp_path, [
        row("101_Лестница", "Korridor", block="stair", floor=1,
            group="101_1", lamp="1.1.1", sensor="1.1.1", panel="None"),
        row("201_Лестница", "Korridor", block="stair", floor=2,
            group="201_1", lamp="1.2.1", sensor="1.2.1", panel="None"),
    ])

    out = capsys.readouterr().out
    assert "нескольких этажах" in out
    assert "stair" in out
