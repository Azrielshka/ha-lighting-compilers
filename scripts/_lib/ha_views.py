# -*- coding: utf-8 -*-
"""
ha_views.py
Чистая логика views дашборда: как называются, как упорядочены, как сливаются
с тем, что уже есть на объекте.

Вынесено отдельно от деплоя специально: слияние — самая опасная часть (мы
переписываем конфиг дашборда целиком), и его надо проверять тестами без
живого Home Assistant.

Раскладка (согласовано с владельцем 2026-07-16):
- view на каждый этаж (`zm-floor-<N>`) с компактными карточками помещений;
- subview на каждое пространство (`zm-space-<room_slug>`) с полной карточкой;
- наши views опознаются по префиксу пути `zm-` — всё остальное на дашборде
  (Главная, Энергомониторинг, Ошибки…) принадлежит владельцу и не трогается.
"""

from __future__ import annotations

from typing import Dict, List


# Префикс пути наших views. Аналог префикса `zm_` у файлов деплоя: по нему
# и только по нему деплой отличает своё от чужого.
VIEW_PREFIX = "zm-"

MAIN_PATH = f"{VIEW_PREFIX}main"
FLOOR_PREFIX = f"{VIEW_PREFIX}floor-"
SPACE_PREFIX = f"{VIEW_PREFIX}space-"

# Наши views встают В НАЧАЛО дашборда, а не после первого.
#
# Раньше было INSERT_AT = 1: Главная принадлежала владельцу и всегда шла первой,
# наши этажи вставлялись сразу за ней. С 2026-07-17 Главную генерируем мы
# (zm-main), и она сама должна быть первой — иначе дашборд откроется на чужом
# view, а кнопка «назад» с этажа (она ведёт на корень дашборда, то есть на
# первый view) уведёт не на Главную.
#
# Позиция фиксированная: регенерация не должна двигать порядок.
INSERT_AT = 0

# Раскладка subview помещения (согласовано с владельцем 2026-07-16).
# max_columns — «максимальное число разделов в ширину» у view;
# column_span — сколько колонок занимает секция внутри view.
#
# Этажный view здесь НЕ описан: он целиком собирается из редактируемого
# шаблона templates/lovelace/floor/view.yaml (там же шапка и бейджи).
SPACE_MAX_COLUMNS = 2

# Ширина секции в subview: широким раскладкам — 2 колонки, остальным 1.
# korridor — пары «свет|датчик» тройками, zal — группы + сетка пресетов:
# в одну колонку они жмутся.
SPACE_COLUMN_SPAN: Dict[str, int] = {
    "korridor": 2,
    "zal": 2,
}
SPACE_COLUMN_SPAN_DEFAULT = 1


def space_column_span(space_type: str) -> int:
    return SPACE_COLUMN_SPAN.get(space_type, SPACE_COLUMN_SPAN_DEFAULT)


def floor_view_path(floor: int) -> str:
    return f"{FLOOR_PREFIX}{floor}"


def space_view_path(room_slug: str) -> str:
    return f"{SPACE_PREFIX}{room_slug}"


def is_ours(view: dict) -> bool:
    return str(view.get("path", "")).startswith(VIEW_PREFIX)


def build_space_subview(title: str, room_slug: str, card: dict,
                        space_type: str = "") -> dict:
    """Subview пространства: полная карточка. Скрыт из вкладок (subview)."""
    return {
        "title": title,
        "path": space_view_path(room_slug),
        "subview": True,
        "type": "sections",
        "max_columns": SPACE_MAX_COLUMNS,
        "sections": [{
            "type": "grid",
            "column_span": space_column_span(space_type),
            "cards": [card],
        }],
    }


def order_views(views: List[dict]) -> List[dict]:
    """Главная, следом этажи по возрастанию номера, следом subview по алфавиту.

    Главная обязана быть первой: дашборд открывается на первом view, и на него
    же ведёт кнопка «назад» с этажей. Порядок детерминированный — генератор и
    деплой должны собирать одно и то же.
    """
    def key(v: dict):
        path = str(v.get("path", ""))
        if path == MAIN_PATH:
            return (0, 0, "")
        if path.startswith(FLOOR_PREFIX):
            tail = path[len(FLOOR_PREFIX):]
            return (1, int(tail) if tail.isdigit() else 0, "")
        return (2, 0, path)

    return sorted(views, key=key)


def merge_views(existing: List[dict], ours: List[dict],
                insert_at: int = INSERT_AT) -> List[dict]:
    """Слить наши views в конфиг дашборда, сохранив views владельца.

    Свои (по префиксу пути) выкидываем целиком и вставляем свежие на
    фиксированную позицию — поэтому повторный деплой даёт тот же результат,
    а ручной порядок владельца не разъезжается.
    """
    keep = [v for v in existing if not is_ours(v)]
    pos = max(0, min(insert_at, len(keep)))
    return keep[:pos] + list(ours) + keep[pos:]


def diff_summary(existing: List[dict], ours: List[dict]) -> Dict[str, int]:
    """Что покажет dry-run до всякой записи."""
    old_ours = [v for v in existing if is_ours(v)]
    old_paths = {str(v.get("path", "")) for v in old_ours}
    new_paths = {str(v.get("path", "")) for v in ours}
    return {
        "keep_foreign": len([v for v in existing if not is_ours(v)]),
        "replace": len(old_paths & new_paths),
        "add": len(new_paths - old_paths),
        "remove": len(old_paths - new_paths),
    }
