# -*- coding: utf-8 -*-
"""
Слияние views дашборда — самая опасная часть деплоя карточек.

`lovelace/config/save` перезаписывает дашборд ЦЕЛИКОМ, поэтому цена ошибки в
merge — снесённые вручную сделанные views владельца (Главная, Энергомониторинг,
Ошибки). Логика вынесена в чистый модуль именно затем, чтобы проверяться здесь,
без живого Home Assistant.
"""

from __future__ import annotations

import pytest

from scripts._lib import ha_views as V


def _foreign():
    """Дашборд владельца: наших views ещё нет."""
    return [
        {"title": "Главная", "path": "home"},
        {"title": "Энергомониторинг", "path": "energy"},
        {"title": "Ошибки", "path": "errors"},
    ]


def _ours():
    return [
        {"title": "Этаж 1", "path": V.floor_view_path(1)},
        {"title": "103 Вестибюль", "path": V.space_view_path("103_vestibiul")},
    ]


# ============================================================
# Пути и опознание своего
# ============================================================

def test_paths_have_prefix():
    assert V.floor_view_path(2) == "zm-floor-2"
    assert V.space_view_path("103_x") == "zm-space-103_x"
    assert V.floor_view_path(2).startswith(V.VIEW_PREFIX)


def test_is_ours_only_by_prefix():
    assert V.is_ours({"path": "zm-floor-1"})
    assert not V.is_ours({"path": "energy"})
    assert not V.is_ours({})            # view без path — чужой, не трогаем


# ============================================================
# Предустановки раскладки subview (согласованы с владельцем)
#
# Этажный view здесь не проверяем: он собирается из шаблона
# templates/lovelace/floor/view.yaml — его тесты в test_generate_lovelace_cards.
# ============================================================

@pytest.mark.parametrize("space_type,expected", [
    ("korridor", 2),      # пары тройками — в одну колонку жмётся
    ("zal", 2),           # группы + сетка пресетов
    ("class", 1),
    ("special", 1),
    ("recreation", 1),
    ("hall", 1),
    ("", 1),              # тип не указан — узкая по умолчанию
])
def test_space_subview_column_span_by_type(space_type, expected):
    view = V.build_space_subview("X", "x", {"type": "grid"}, space_type=space_type)
    assert view["sections"][0]["column_span"] == expected
    assert view["max_columns"] == 2


# ============================================================
# Слияние
# ============================================================

def test_merge_puts_ours_first():
    """Наши views встают в НАЧАЛО дашборда, а не в хвост и не после чужого.

    Раньше было «сразу после первого view»: Главная принадлежала владельцу и
    шла первой. Теперь Главную генерируем мы, и первой обязана быть она —
    дашборд открывается на первом view, и туда же ведёт кнопка «назад» с этажа.
    """
    merged = V.merge_views(_foreign(), _ours())
    paths = [v["path"] for v in merged]
    assert paths == ["zm-floor-1", "zm-space-103_vestibiul",
                     "home", "energy", "errors"]


def test_merge_keeps_foreign_views_untouched():
    foreign = _foreign()
    merged = V.merge_views(foreign, _ours())
    kept = [v for v in merged if not V.is_ours(v)]
    assert kept == foreign               # чужие сохранены как есть, в порядке


def test_merge_is_idempotent():
    """Повторный деплой не плодит дубли и не двигает порядок."""
    once = V.merge_views(_foreign(), _ours())
    twice = V.merge_views(once, _ours())
    assert once == twice


def test_merge_replaces_our_old_views():
    """Наши старые views выкидываются целиком, а не накапливаются."""
    existing = V.merge_views(_foreign(), [
        {"title": "Этаж 9", "path": V.floor_view_path(9)},
    ])
    merged = V.merge_views(existing, _ours())
    paths = [v["path"] for v in merged]
    assert "zm-floor-9" not in paths     # помещение исчезло из таблицы — view ушёл
    assert "zm-floor-1" in paths


def test_merge_into_empty_dashboard():
    merged = V.merge_views([], _ours())
    assert [v["path"] for v in merged] == ["zm-floor-1", "zm-space-103_vestibiul"]


def test_merge_when_only_one_foreign_view():
    """Единственный чужой view уезжает за наши, а не наоборот."""
    merged = V.merge_views([{"path": "home"}], _ours())
    assert [v["path"] for v in merged] == ["zm-floor-1",
                                           "zm-space-103_vestibiul", "home"]


# ============================================================
# Порядок
# ============================================================

def test_order_floors_numerically_then_subviews():
    views = [
        {"path": V.space_view_path("b")},
        {"path": V.floor_view_path(10)},
        {"path": V.floor_view_path(2)},
        {"path": V.space_view_path("a")},
    ]
    assert [v["path"] for v in V.order_views(views)] == [
        "zm-floor-2", "zm-floor-10",      # именно 2 < 10, не строкой
        "zm-space-a", "zm-space-b",
    ]


# ============================================================
# Сводка для dry-run
# ============================================================

def test_diff_summary_counts():
    existing = V.merge_views(_foreign(), [
        {"path": V.floor_view_path(1)},          # останется -> replace
        {"path": V.floor_view_path(9)},          # исчезнет  -> remove
    ])
    s = V.diff_summary(existing, _ours())
    assert s == {"keep_foreign": 3, "replace": 1, "add": 1, "remove": 1}


# ============================================================
# Главная — наша и первая
# ============================================================

def test_main_view_sorts_first():
    """Порядок: Главная, этажи по номеру, subview. Главная строго первая."""
    views = [
        {"path": V.space_view_path("a")},
        {"path": V.floor_view_path(2)},
        {"path": V.MAIN_PATH},
        {"path": V.floor_view_path(1)},
    ]
    assert [v["path"] for v in V.order_views(views)] == [
        "zm-main", "zm-floor-1", "zm-floor-2", "zm-space-a",
    ]


def test_main_view_is_ours():
    assert V.is_ours({"path": V.MAIN_PATH})
    assert V.MAIN_PATH.startswith(V.VIEW_PREFIX)


def test_merge_keeps_main_first_on_regeneration():
    """Повторный деплой не уводит Главную с первого места."""
    ours = V.order_views([
        {"path": V.MAIN_PATH},
        {"path": V.floor_view_path(1)},
    ])
    once = V.merge_views(_foreign(), ours)
    twice = V.merge_views(once, ours)

    assert once == twice
    assert twice[0]["path"] == V.MAIN_PATH
