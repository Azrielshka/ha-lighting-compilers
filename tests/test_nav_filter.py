# -*- coding: utf-8 -*-
"""
Фильтр навигации по типу помещения.

Фильтр держится на сцепке трёх вещей, и все три разъезжаются молча:

  1. помощник в пакете              (generate_helpers)
  2. плитка в панели                (templates/_blocks/nav_filter*.yaml)
  3. условие видимости у карточки   (build_compact_card)

Разойдись любые две — оператор не увидит ошибки. Он увидит помещение, которое
не показывается ни при каком фильтре, или плитку «сущность недоступна». Ровно
этот класс дефекта уже стоил нам плитки тех.помещений, висевшей в пустоте.

Поэтому здесь почти нет проверок «поле равно строке»: почти всё сверяется с
ДРУГИМ концом сцепки — с фактическим выходом соседнего генератора или с
исходными данными в parquet.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pandas as pd
import pytest
import yaml

import generate_helpers as H
import generate_lovelace_cards as G
import normalize_excel as N
from scripts._lib import canon as C
from scripts._lib.filters import Filters
from scripts._lib.normalized import load_dataset

DASHBOARD = "dash-test"


# ============================================================
# Вычислитель visibility по правилам Home Assistant
# ============================================================

def visible(card: dict, state: dict) -> bool:
    """Показал бы HA эту карточку при таком состоянии помощников.

    Правила, которые здесь воспроизведены (проверены по исходнику
    frontend/src/panels/lovelace/common/validate-condition.ts):

    - условия ВЕРХНЕГО уровня складываются по И — карточка видна, только если
      прошли все;
    - внутри `condition: or` достаточно одного;
    - `state` может быть строкой ИЛИ списком: список означает «любое из».

    Без этого пришлось бы проверять фильтр глазами на живом HA, а он на
    объекте, и каждая проверка — деплой с рестартом.
    """
    def one(cond: dict) -> bool:
        kind = cond["condition"]
        if kind == "or":
            return any(one(c) for c in cond["conditions"])
        if kind == "and":
            return all(one(c) for c in cond["conditions"])
        if kind == "state":
            want = cond["state"]
            want = want if isinstance(want, list) else [want]
            return state.get(cond["entity"]) in want
        raise AssertionError(f"неизвестное условие: {kind}")

    return all(one(c) for c in card.get("visibility", []))


def _all_off() -> dict:
    """Все булевы выключены, список нейтрален. База для сборки состояний."""
    st = {C.nav_type_all_entity(): "off"}
    st.update({C.nav_type_entity(t): "off" for t in C.NAV_TYPE_LABELS})
    st[C.nav_pick_entity()] = C.NAV_TYPE_ALL_LABEL
    return st


def _default() -> dict:
    """Состояние сразу после создания помощников: initial у «Все» = on."""
    return {**_all_off(), C.nav_type_all_entity(): "on"}


# ============================================================
# Фикстуры
# ============================================================

@pytest.fixture
def object_layer(tmp_path, object_example) -> Path:
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


@pytest.fixture
def views(object_layer, tmp_path) -> dict:
    out_dir = tmp_path / "lovelace"
    G.generate_cards(
        spaces_parquet=object_layer / "spaces.parquet",
        templates_dir=G.DEFAULT_TEMPLATES_DIR,
        out_dir=out_dir,
        report_json=tmp_path / "report.json",
        filters=Filters(),
        dashboard=DASHBOARD,
        title="Объект-тест",
    )
    return {yaml.safe_load(f.read_text(encoding="utf-8"))["path"]:
            yaml.safe_load(f.read_text(encoding="utf-8"))
            for f in sorted(out_dir.glob("*.yaml"))}


@pytest.fixture
def helpers(object_layer) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        return H.build_payload(load_dataset(object_layer, "spaces"), Filters())


def _rooms(view: dict) -> list:
    """Карточки помещений — по содержимому, а не по индексу секции."""
    out = []
    for section in view.get("sections", []):
        for card in section.get("cards", []):
            inner = card.get("cards") or []
            if inner and "zm-space-" in str(
                    (inner[-1].get("tap_action") or {}).get("navigation_path", "")):
                out.append(card)
    return out


def _heading(card: dict) -> str:
    return card["cards"][0]["heading"]


# ============================================================
# Сцепка: канон -> помощники -> панель -> условия
# ============================================================

def test_every_space_type_has_a_label():
    """Новый тип помещения обязан получить подпись фильтра.

    Иначе он тихо выпадет: помощника нет, условия у карточки нет, и помещение
    показывается всегда — фильтр его просто не касается. Заметят на объекте.
    """
    missing = C.ALLOWED_SPACE_TYPES - set(C.NAV_TYPE_LABELS)
    assert not missing, (
        f"типы без подписи в NAV_TYPE_LABELS: {sorted(missing)}. "
        f"Такое помещение не попадёт под фильтр вообще"
    )
    extra = set(C.NAV_TYPE_LABELS) - C.ALLOWED_SPACE_TYPES
    assert not extra, f"подписи для несуществующих типов: {sorted(extra)}"


def test_every_type_has_an_icon():
    """Плитка без иконки в панели выглядит поломкой."""
    need = set(C.NAV_TYPE_LABELS) | {C.NAV_TYPE_ALL_ID}
    assert set(C.NAV_TYPE_ICONS) == need


def test_helpers_created_for_all_types(helpers):
    """Помощники есть на КАЖДЫЙ тип, даже если таких помещений на объекте нет.

    Панель одна на объект и захардкожена: отсутствующий помощник показал бы в
    ней «сущность недоступна».
    """
    booleans = helpers["input_boolean"]

    assert C.NAV_TYPE_ALL_ID in booleans
    for space_type in C.NAV_TYPE_LABELS:
        assert C.nav_type_id(space_type) in booleans, space_type


def test_all_helper_starts_on(helpers):
    """У «Все» обязан быть initial: on.

    Без него после первого старта HA все фильтры выключены, ни одна карточка
    условие не проходит — и этажные страницы оказываются ПУСТЫМИ. Выглядит как
    поломка генератора, а не как «фильтр не настроен».
    """
    assert helpers["input_boolean"][C.NAV_TYPE_ALL_ID].get("initial") is True

    # у типов initial быть НЕ должно: иначе фильтр стартует сужённым
    for space_type in C.NAV_TYPE_LABELS:
        assert "initial" not in helpers["input_boolean"][C.nav_type_id(space_type)]


def test_panel_uses_only_helpers_that_exist(helpers):
    """Каждая плитка панели ссылается на помощника, которого создаёт генератор.

    Сверяем с ФАКТИЧЕСКИМ выходом generate_helpers, а не с каноном: канон
    подтвердил бы имя и у сущности, которую никто не создаёт.
    """
    panel = yaml.safe_load(G.build_nav_filter(G.DEFAULT_TEMPLATES_DIR))[0]

    created = {f"input_boolean.{k}" for k in helpers["input_boolean"]}
    created |= {f"input_select.{k}" for k in helpers["input_select"]}

    used = {c["entity"] for c in panel["cards"] if c.get("type") == "tile"}
    assert used, "в панели нет ни одной плитки"

    missing = used - created
    assert not missing, f"панель ссылается на несозданных помощников: {sorted(missing)}"


def test_panel_starts_with_all(helpers):
    """«Все» первой плиткой: это выключатель фильтра, а не ещё один тип."""
    panel = yaml.safe_load(G.build_nav_filter(G.DEFAULT_TEMPLATES_DIR))[0]
    tiles = [c for c in panel["cards"] if c.get("type") == "tile"]

    assert tiles[0]["entity"] == C.nav_type_all_entity()
    assert tiles[0]["name"] == C.NAV_TYPE_ALL_LABEL


# ============================================================
# Условия у карточек помещений
# ============================================================

def test_each_room_filters_by_its_own_type(views, object_layer):
    """Условие карточки ссылается на ТОТ ЖЕ тип, что у помещения в данных.

    Сверяем с parquet, а не с тем, что сам же сгенерировал: иначе тест
    подтвердит любую ошибку, лишь бы она была одинаковой в обоих местах.
    """
    spaces = load_dataset(object_layer, "spaces")
    real = {C.space_label(s): t for s, t in zip(spaces["space"], spaces["space_type"])}

    checked = 0
    for path, view in views.items():
        if not path.startswith("zm-floor-"):
            continue
        for card in _rooms(view):
            name = _heading(card)
            expected = real[name]

            entities = [
                c["entity"]
                for cond in card["visibility"] if cond["condition"] == "or"
                for c in cond["conditions"]
            ]
            own = [e for e in entities if e != C.nav_type_all_entity()]
            assert own == [C.nav_type_entity(expected)], (
                f"{name}: тип в данных {expected}, а условие на {own}"
            )
            checked += 1

    assert checked, "не проверено ни одной карточки"


def test_select_condition_labels_match_helper_options(views, helpers):
    """Строки в условии = опции input_select, символ в символ.

    Сверка идёт по строке состояния. Разъедутся на пробел — помещение молча
    перестанет показываться при выборе своего типа, и причину будут искать в
    карточках.
    """
    options = set(helpers["input_select"][C.NAV_PICK_ID]["options"])

    used = set()
    for path, view in views.items():
        if not path.startswith("zm-floor-"):
            continue
        for card in _rooms(view):
            for cond in card["visibility"]:
                if cond.get("entity") == C.nav_pick_entity():
                    used |= set(cond["state"])

    assert used, "ни одно условие не ссылается на список"
    assert used <= options, f"в условиях есть строки, которых нет в опциях: {sorted(used - options)}"


# ============================================================
# Поведение: что увидит оператор
# ============================================================

def test_default_state_shows_everything(views):
    """Сразу после деплоя видно всё. Это и есть смысл initial: on у «Все»."""
    floor = views["zm-floor-1"]
    rooms = _rooms(floor)

    shown = [r for r in rooms if visible(r, _default())]
    assert len(shown) == len(rooms), "по умолчанию должно быть видно всё"


def test_single_type_shows_only_that_type(views, object_layer):
    """Отметили один тип — видно только помещения этого типа."""
    spaces = load_dataset(object_layer, "spaces")
    floor1 = spaces[spaces["floor"] == 1]
    korridors = {C.space_label(s) for s, t in
                 zip(floor1["space"], floor1["space_type"]) if t == "korridor"}

    state = {**_all_off(), C.nav_type_entity("korridor"): "on"}
    shown = {_heading(r) for r in _rooms(views["zm-floor-1"]) if visible(r, state)}

    assert shown == korridors, f"ожидали {korridors}, увидели {shown}"


def test_multiselect_shows_union(views, object_layer):
    """Два типа сразу — объединение. Ради этого и заводили шесть булевых.

    Списком так нельзя: он однозначен. Это и есть предмет сравнения двух
    фильтров.
    """
    spaces = load_dataset(object_layer, "spaces")
    floor1 = spaces[spaces["floor"] == 1]
    expected = {C.space_label(s) for s, t in
                zip(floor1["space"], floor1["space_type"]) if t in ("korridor", "zal")}

    state = {**_all_off(),
             C.nav_type_entity("korridor"): "on",
             C.nav_type_entity("zal"): "on"}
    shown = {_heading(r) for r in _rooms(views["zm-floor-1"]) if visible(r, state)}

    assert shown == expected
    assert len(shown) > len(
        {_heading(r) for r in _rooms(views["zm-floor-1"])
         if visible(r, {**_all_off(), C.nav_type_entity("zal"): "on"})}
    ), "мультивыбор обязан показывать больше, чем один тип"


def test_all_wins_over_narrower_choice(views):
    """«Все» включён — видно всё, что бы ни было отмечено ещё.

    Прощающее поведение: гасить остальные «Все» не умеет (за помощниками мы
    логики не пишем), поэтому он просто перекрывает их условием ИЛИ.
    """
    rooms = _rooms(views["zm-floor-1"])
    state = {**_default(), C.nav_type_entity("zal"): "on"}

    assert len([r for r in rooms if visible(r, state)]) == len(rooms)


def test_nothing_selected_hides_everything(views):
    """Сняли всё — пусто. Состояние достижимо руками, и это не поломка.

    Панель фильтра при этом остаётся: она в своей секции, без условий
    видимости, — значит выход из пустого экрана всегда на виду.
    """
    rooms = _rooms(views["zm-floor-1"])

    shown = [r for r in rooms if visible(r, _all_off())]
    assert shown == [], "при всех выключенных булевых помещений быть не должно"

    # а панель — на месте
    panel_section = views["zm-floor-1"]["sections"][0]
    assert "visibility" not in panel_section
    assert all("visibility" not in c for c in panel_section["cards"])


# ============================================================
# Два фильтра сразу (временный режим сравнения)
# ============================================================

def test_two_filters_intersect(views, object_layer):
    """Условия верхнего уровня складываются по И — на выходе пересечение.

    Это осознанная механика режима сравнения: каждый фильтр глушится своим
    «Все». Уберём проигравший вариант — уйдёт и это.
    """
    rooms = _rooms(views["zm-floor-1"])

    # плитки: коридоры + залы; список: только залы -> остаются залы
    state = {**_all_off(),
             C.nav_type_entity("korridor"): "on",
             C.nav_type_entity("zal"): "on",
             C.nav_pick_entity(): C.NAV_TYPE_LABELS["zal"]}
    shown = {_heading(r) for r in rooms if visible(r, state)}

    spaces = load_dataset(object_layer, "spaces")
    floor1 = spaces[spaces["floor"] == 1]
    zals = {C.space_label(s) for s, t in zip(floor1["space"], floor1["space_type"]) if t == "zal"}
    assert shown == zals


def test_each_filter_is_neutralised_by_its_own_all(views):
    """Режим сравнения: один фильтр на «Все» — рулит другой.

    Без этого свойства сравнить их было бы нельзя: они бы всё время мешали
    друг другу.
    """
    rooms = _rooms(views["zm-floor-1"])

    # булевы нейтральны -> рулит список
    by_select = {_heading(r) for r in rooms
                 if visible(r, {**_default(), C.nav_pick_entity(): C.NAV_TYPE_LABELS["zal"]})}

    # список нейтрален -> рулят плитки
    by_tiles = {_heading(r) for r in rooms
                if visible(r, {**_all_off(), C.nav_type_entity("zal"): "on"})}

    assert by_select == by_tiles, "оба фильтра должны давать одинаковый результат на одном типе"
    assert by_select, "фильтр по залам не должен быть пустым — зал на этаже есть"
