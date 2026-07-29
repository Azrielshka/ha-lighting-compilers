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
    ALLOWED_SPACE_TYPES,
    NAV_PLACEHOLDER,
    ZAL_PRESETS,
    floor_auto_mode_entity,
    floor_nav_entity,
    vacant_delay_id,
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
# vacant_delay — задержка гашения ПО ТИПУ помещения
# ============================================================

def test_vacant_delay_created_per_type_without_initial(object_layer):
    """
    Правка 2026-07-23: один input_number на КАЖДЫЙ из 6 канонических типов,
    БЕЗ initial.

    ⚠ Отсутствие initial критично: с ним значение сбрасывалось при каждом
    старте HA. Без — принадлежит объекту. Тест стережёт, чтобы initial не
    вернулся случайно (например, копипастом из старого помощника).
    """
    numbers = _package(object_layer)["input_number"]

    assert len(numbers) == len(ALLOWED_SPACE_TYPES) == 6

    for space_type in ALLOWED_SPACE_TYPES:
        key = vacant_delay_id(space_type)
        assert key in numbers, f"нет задержки для типа {space_type}"

        number = numbers[key]
        assert "initial" not in number, f"{key}: initial вернулся"
        assert number["mode"] == "box"          # поле ввода, а не ползунок
        assert number["min"] == 0 and number["max"] == 300


# Прежний test_vacant_delay_has_initial_on_purpose удалён (2026-07-23): initial
# снят по решению владельца, значение теперь принадлежит объекту. Отсутствие
# initial стережёт test_vacant_delay_created_per_type_without_initial выше.
# «unknown → for ломается» не возвращается: сущность создаётся всегда (просто
# без initial), значение при первом старте = min (0), а не unknown.


# ============================================================
# Навигация: опции = помещения этажа
# ============================================================

def test_floor_type_filter_per_floor_present_types(object_layer):
    """Фильтр групп по типу — по одному select на этаж, опции = заглушка +
    только присутствующие на этаже типы (в порядке NAV_TYPE_LABELS).
    """
    from scripts._lib.canon import (
        floor_type_filter_id, FLOOR_TYPE_FILTER_PLACEHOLDER,
    )

    selects = _package(object_layer)["input_select"]

    # этаж 1: korridor, class, zal, special, recreation (без hall)
    assert selects[floor_type_filter_id(1)]["options"] == [
        FLOOR_TYPE_FILTER_PLACEHOLDER,
        "Коридоры", "Классы", "Залы", "Санузлы и тамбуры", "Рекреации",
    ]
    # этаж 2: только hall
    assert selects[floor_type_filter_id(2)]["options"] == [
        FLOOR_TYPE_FILTER_PLACEHOLDER, "Холлы",
    ]
    # заглушка — initial (ничего доп. не показано)
    assert selects[floor_type_filter_id(1)]["initial"] == FLOOR_TYPE_FILTER_PLACEHOLDER


def test_nav_select_per_floor_with_room_options(object_layer):
    selects = _floor_navs(_package(object_layer))

    assert set(selects) == {"nav_floor_1", "nav_floor_2"}
    assert selects["nav_floor_2"]["options"] == [NAV_PLACEHOLDER, "208 Входной тамбур"]
    # порядок помещений — по номеру возрастанием, следом за заглушкой
    assert selects["nav_floor_1"]["options"][:4] == [
        NAV_PLACEHOLDER, "101 Тамбур", "102 Тамбур", "103 Вестибюль",
    ]


def test_nav_options_sorted_by_number_ascending(tmp_path):
    """
    Правило: опции нумерованы по возрастанию (space_sort_key), а не в порядке
    таблицы. Проверяем на данных, где табличный и числовой порядок РАЗОШЛИСЬ:
    таблица даёт 110, 9, 101 — селект обязан выдать 9, 101, 110.
    """
    def r(space, group, lamp, sensor):
        return {"Этаж": 1, "Название помещения": space, "Тип помещения": "Korridor",
                "Шина DALI": 1, "Группа": group, "Лампа": lamp,
                "Датчик": sensor, "Панель": "None"}

    rows = [
        r("110_Санузел", "110_1", "1.1.1", "1.1.1"),
        r("9_Подвал", "9_1", "1.1.2", "1.1.2"),
        r("101_Тамбур", "101_1", "1.1.3", "1.1.3"),
    ]
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)
    opts = _payload(out)["input_select"]["nav_floor_1"]["options"]

    assert opts == [NAV_PLACEHOLDER, "9 Подвал", "101 Тамбур", "110 Санузел"]


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

def test_regim_auto_is_no_longer_generated(object_layer):
    """
    Правка 5 (2026-07-23): regim_auto больше НЕ создаётся — бейдж режима
    переключён на switch/гейт Оркестратора. Билдер floor_auto_mode_entity
    сохранён (для истории/отката), но в пакете его сущностей быть не должно.
    """
    booleans = _package(object_layer)["input_boolean"]

    for floor in (1, 2):
        # Формула билдера жива на случай отката...
        assert floor_auto_mode_entity(floor) == f"input_boolean.regim_auto_{floor}"
        # ...но сама сущность не генерируется.
        assert f"regim_auto_{floor}" not in booleans

    assert not any(k.startswith("regim_auto_") for k in booleans)


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
