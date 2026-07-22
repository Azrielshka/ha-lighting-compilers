# -*- coding: utf-8 -*-
"""
Вспомогательные объекты (helpers) — один пакет на объект.

Раньше их заводил наладчик руками, и забытый всплывал уже на объекте: без
`input_number.vacant_delay` свет не гаснет, без `input_select` не работает
навигация с Главной. Здесь проверяем, что пайплайн создаёт ровно то, на что
сам же и ссылается.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import generate_helpers as H
import normalize_excel as N
from conftest import make_book
from scripts._lib.canon import (
    NAV_PLACEHOLDER,
    VACANT_DELAY_DEFAULT,
    VACANT_DELAY_ENTITY,
    ZAL_PRESETS,
    floor_auto_mode_entity,
    floor_nav_entity,
)
from scripts._lib.filters import Filters
from scripts._lib.normalized import load_dataset

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "lovelace"


@pytest.fixture
def object_layer(tmp_path, object_example) -> Path:
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


def _payload(layer: Path, filters: Filters = None) -> dict:
    return H.build_payload(load_dataset(layer, "spaces"), filters or Filters())


def _floor_navs(package: dict) -> dict:
    """Списки навигации по этажам — только они.

    ⚠ Не «все input_select». В пакете теперь есть и nav_type_pick — фильтр по
    типу помещения, заведённый для сравнения с плитками. Он не про этажи, у
    него другие опции и другой initial. Тесты, проверявшие «все селекты»,
    упали именно на нём: интересовали их всегда только этажные.
    """
    return {k: v for k, v in package["input_select"].items()
            if k.startswith("nav_floor_")}


def _package(layer: Path) -> dict:
    """Пакет так, как его увидит Home Assistant: после разбора YAML."""
    doc = yaml.safe_load(H.render_yaml(_payload(layer)))
    return doc[H.PACKAGE_KEY]


# ============================================================
# vacant_delay — главный известный долг
# ============================================================

def test_vacant_delay_is_created_with_default(object_layer):
    """Тот самый помощник, без которого свет не гаснет."""
    number = _package(object_layer)["input_number"]["vacant_delay"]

    assert number["initial"] == VACANT_DELAY_DEFAULT == 10
    assert number["mode"] == "box"          # поле ввода, а не ползунок
    assert number["min"] == 0 and number["max"] == 300


def test_vacant_delay_entity_matches_what_automations_reference(object_layer):
    """Имя выводится из ключа — оно обязано совпасть с тем, что ждут автоматизации.

    entity_id у YAML-помощника берётся из КЛЮЧА (`vacant_delay:`), а не из
    отображаемого имени. Если ключ разойдётся с canon.VACANT_DELAY_ENTITY,
    OFF-автоматизации будут ссылаться в пустоту.
    """
    keys = _package(object_layer)["input_number"].keys()

    assert VACANT_DELAY_ENTITY == f"input_number.{list(keys)[0]}"


def test_vacant_delay_has_initial_on_purpose(object_layer):
    """`initial` обязан быть: без него на чистом объекте состояние unknown.

    Тогда `for: seconds: {{ states(...) }}` ломается и свет не гаснет — это и
    есть баг, ради которого шаг helpers затевался. Цена осознанная: значение
    принадлежит пайплайну и восстанавливается при каждом старте HA.
    """
    assert "initial" in _package(object_layer)["input_number"]["vacant_delay"]


# ============================================================
# Навигация: опции = помещения этажа
# ============================================================

def test_nav_select_per_floor_with_room_options(object_layer):
    selects = _floor_navs(_package(object_layer))

    assert set(selects) == {"nav_floor_1", "nav_floor_2"}
    assert selects["nav_floor_2"]["options"] == [NAV_PLACEHOLDER, "208 Входной тамбур"]
    # порядок помещений — как в таблице, следом за заглушкой
    assert selects["nav_floor_1"]["options"][:4] == [
        NAV_PLACEHOLDER, "101 Тамбур", "102 Тамбур", "103 Вестибюль",
    ]


def test_nav_starts_with_nothing_selected(object_layer):
    """При загрузке ничего не выбрано — кнопка перехода показывает подсказку.

    У input_select пустого состояния не бывает: оно всегда одна из options.
    Поэтому «ничего не выбрано» = заглушка первой опцией, она же initial.
    """
    for select in _floor_navs(_package(object_layer)).values():
        assert select["options"][0] == NAV_PLACEHOLDER
        assert select["initial"] == NAV_PLACEHOLDER


def test_placeholder_is_not_a_room_name(object_layer):
    """Заглушка не должна совпасть с именем помещения — оно стало бы недостижимо."""
    for select in _floor_navs(_package(object_layer)).values():
        rooms = select["options"][1:]
        assert NAV_PLACEHOLDER not in rooms


def test_nav_options_use_same_label_as_card_heading(object_layer):
    """Опции списка и заголовок карточки строятся одним правилом.

    Карта «имя → слаг» в markdown-кнопке перехода сверяется с состоянием
    input_select по строке. Разъедутся правила — навигация молча перестанет
    работать: выбрал помещение, а кнопка показывает «выберите помещение».
    """
    import generate_lovelace_cards as CARDS

    options = _package(object_layer)["input_select"]["nav_floor_1"]["options"]
    assert "103 Вестибюль" in options
    assert CARDS.build_heading("103_Вестибюль") == "103 Вестибюль"
    assert H.space_label("103_Вестибюль") == CARDS.build_heading("103_Вестибюль")


# ============================================================
# Режимы этажей и пресеты зала
# ============================================================

def test_auto_mode_boolean_per_floor(object_layer):
    booleans = _package(object_layer)["input_boolean"]

    for floor in (1, 2):
        assert floor_auto_mode_entity(floor) == f"input_boolean.regim_auto_{floor}"
        assert f"regim_auto_{floor}" in booleans


def test_zal_presets_are_created(object_layer):
    booleans = _package(object_layer)["input_boolean"]

    for preset_id in ZAL_PRESETS:
        assert preset_id in booleans


# ============================================================
# Шаблоны ссылаются только на то, что мы создаём
# ============================================================

def _referenced_helpers(text: str) -> set:
    """Помощники, на которых висит шаблон. [[FLOOR]] подставляем как 1.

    Строки-комментарии выбрасываем: в шапках шаблонов помощники описаны с
    плейсхолдерами вида `regim_auto_<этаж>`, и они дали бы ложные срабатывания.
    Нас интересуют ссылки в конфиге, а не в документации.
    """
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(lines).replace("[[FLOOR]]", "1")
    return set(re.findall(r"input_(?:boolean|number|button|select)\.[a-z0-9_]+", body))


def test_templates_reference_only_generated_helpers(object_layer):
    """Ни одна карточка не должна ссылаться на помощника, которого нет.

    Это и был исходный дефект: шаблоны ссылались на input_boolean, которых
    пайплайн не создавал, и на объекте бейдж показывал «недоступно» без
    единой подсказки почему.
    """
    package = _package(object_layer)
    created = {
        f"{domain}.{obj_id}"
        for domain, items in package.items()
        for obj_id in items
    }

    referenced = set()
    for path in sorted(TEMPLATES.rglob("*.yaml")):
        referenced |= _referenced_helpers(path.read_text(encoding="utf-8"))

    missing = referenced - created
    assert not missing, (
        f"шаблоны ссылаются на несуществующих помощников: {sorted(missing)}. "
        f"Создаются: {sorted(created)}"
    )


def test_zal_presets_match_template():
    """Список пресетов в каноне не должен разъехаться с шаблоном зала.

    Пресеты захардкожены в zal/wrapper.yaml (зал один на объект), а канон их
    дублирует, чтобы helpers их создал. Правка одного места без другого =
    кнопка сценария в пустоту.
    """
    text = (TEMPLATES / "zal" / "wrapper.yaml").read_text(encoding="utf-8")
    in_template = {
        e.split(".", 1)[1]
        for e in re.findall(r"input_boolean\.[a-z0-9_]+", text)
    }

    assert in_template == set(ZAL_PRESETS), (
        f"в шаблоне {sorted(in_template)}, в каноне {sorted(ZAL_PRESETS)}"
    )


# ============================================================
# Края
# ============================================================

def test_no_helpers_without_floors(tmp_path):
    """Нет этажей — нет списков навигации и режимов: пустышек не плодим."""
    rows = [{
        "Название помещения": "101_Тамбур", "Тип помещения": "Special",
        "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.1",
        "Датчик": "1.1.1", "Панель": "None",
    }]
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)

    payload = _payload(out)
    # Списков ПО ЭТАЖАМ нет. Фильтр типов (nav_type_pick) остаётся: он от
    # этажей не зависит и нужен панели, которая одна на объект.
    assert not any(k.startswith("nav_floor_") for k in payload["input_select"])
    assert not any(k.startswith("regim_auto_") for k in payload["input_boolean"])


def test_package_has_root_key(object_layer):
    """merge_named требует корневой ключ: файл в includes/packages/ — пакет."""
    doc = yaml.safe_load(H.render_yaml(_payload(object_layer)))

    assert list(doc) == [H.PACKAGE_KEY]
    assert set(doc[H.PACKAGE_KEY]) == {
        "input_number", "input_button", "input_boolean", "input_select",
    }
