# -*- coding: utf-8 -*-
"""
generate_lovelace_cards.py
Генератор карточек Lovelace (v3). У каждого space_type своя раскладка.

Вход:  data/normalized/spaces.parquet
       templates/lovelace/_manifest.yaml     (space_type -> обёртка)
       templates/lovelace/<type>/wrapper.yaml (каркас с маркерами)
       templates/lovelace/_blocks/*.yaml       (атомарные плитки)
Выход: data/lovelace_cards_generated.txt        (карточки для вставки в дашборд)
       data/lovelace_cards_report.json           (что собрано, предупреждения)

Шаг офлайновый: к Home Assistant не подключается. Карточки владелец вставляет
в дашборд вручную (деплой карточек в пайплайн не входит).

Как это устроено: обёртка типа — текст с маркерами. Скалярные маркеры
([[HEADING]], [[GENERAL_LIGHT]], [[ZONE_COUNT]]) подставляются строкой.
Региональные ([[ZONES]], [[ZONE_COLUMNS]], [[SENSORS_2COL]], ...) генератор
собирает как структуру карточек по правилу типа, сериализует в YAML и
вставляет на место маркера с нужным отступом. Хардкод-части обёртки (пресеты
зала) остаются дословно.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml

from scripts._lib import ha_views as V
from scripts._lib.canon import (
    NAV_TYPE_ALL_ID,
    NAV_TYPE_ALL_LABEL,
    NAV_TYPE_ICONS,
    NAV_TYPE_LABELS,
    SERVICE_VIEWS,
    TECHNICAL_SPACE_TYPES,
    floor_area_id,
    floor_icon,
    floor_light_entity,
    floor_nav_entity,
    nav_type_all_entity,
    nav_type_entity,
    space_label,
    tech_light_entity,
)
from scripts._lib.filters import add_filter_args, apply_filters, filters_from_args

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SPACES_PARQUET = PROJECT_ROOT / "data" / "normalized" / "spaces.parquet"
DEFAULT_TEMPLATES_DIR = PROJECT_ROOT / "templates" / "lovelace"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "lovelace"
DEFAULT_REPORT_JSON = PROJECT_ROOT / "data" / "lovelace_cards_report.json"

# url_path дашборда на объекте. Нужен для navigate-путей в компактных
# карточках, поэтому свой на каждом объекте — задаётся флагом/полем лаунчера.
DEFAULT_DASHBOARD = "dashboard-tets"

# Заголовок в шапке Главной. Из таблицы его не взять — имя объекта там не
# хранится, поэтому флаг.
DEFAULT_TITLE = "Освещение"

# Раскладка коридора (согласовано с владельцем 2026-07-15):
ZONES_PER_GRID = 3   # зон в одной сетке-тройке
GRIDS_PER_ROW = 2    # сеток рядом в одном horizontal-stack, дальше перенос

LABEL_PLACEHOLDER = "—"  # заглушка подписи расположения в классе


# ============================================================
# Загрузка шаблонов и блоков
# ============================================================

def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Шаблон не найден: {path}")
    return path.read_text(encoding="utf-8")


def _strip_header_comments(text: str) -> str:
    """Срезать ведущий блок комментариев/пустых строк (шапку файла).

    Только СВЕРХУ: `#` внутри содержимого (напр. закомментированный CSS в
    card_mod-стилях зала) не трогаем, иначе поменяем строку-литерал.
    Заодно убирает строки-описания маркеров из шапки — иначе _splice
    подставил бы блок и в них.
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    return "\n".join(lines[i:])


def _load_block(templates_dir: Path, name: str) -> dict:
    """Прочитать _blocks/<name>.yaml и вернуть плитку как словарь (первый элемент)."""
    raw = yaml.safe_load(_read(templates_dir / "_blocks" / f"{name}.yaml"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"Блок {name}.yaml должен быть списком с одной карточкой")
    return raw[0]


def _fill(node, mapping: Dict[str, str]):
    """Рекурсивно подставить плейсхолдеры в структуре карточки.

    Рекурсия нужна: компактная карточка вложенная (грид → плитки → tap_action),
    и плейсхолдер лежит не на верхнем уровне.
    """
    if isinstance(node, dict):
        return {k: _fill(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, mapping) for v in node]
    if isinstance(node, str):
        return mapping.get(node, node)
    return node


def _tile(block: dict, placeholder: str, value: str) -> dict:
    """Копия блок-плитки с подставленной сущностью."""
    return _fill(copy.deepcopy(block), {placeholder: value})


def load_manifest(templates_dir: Path) -> Dict[str, str]:
    raw = yaml.safe_load(_read(templates_dir / "_manifest.yaml")) or {}
    out: Dict[str, str] = {}
    for key, cfg in (raw.get("card_types", {}) or {}).items():
        cfg = cfg or {}
        if cfg.get("render", True):
            out[str(key)] = str(cfg.get("wrapper", "")).strip()
    return out


# ============================================================
# Разбивка зон (общее для korridor/hall)
# ============================================================

def balanced_sizes(n: int, max_size: int = ZONES_PER_GRID) -> List[int]:
    """Разбить n зон на сетки как можно ровнее (без одинокого хвоста).

    4 -> [2,2], 5 -> [3,2], 7 -> [3,2,2], 9 -> [3,3,3].
    """
    if n <= 0:
        return []
    grids = math.ceil(n / max_size)
    base, rem = divmod(n, grids)
    return [base + (1 if i < rem else 0) for i in range(grids)]


def _chunks(items: List, size: int) -> List[List]:
    return [items[i:i + size] for i in range(0, len(items), size)]


# ============================================================
# Сборщики блока зон по типам
# ============================================================

def _heading(text: str, style: str = "subtitle") -> dict:
    return {"type": "heading", "heading": text, "heading_style": style}


def _sensor_cell(sensor_block: dict, sensors: List[str]) -> dict:
    """Ячейка датчиков зоны для 2-колоночной сетки коридора.

    0 датчиков -> пустая заглушка (пары не сбиваются);
    1 -> плитка датчика; >1 -> плитки стопкой в одной ячейке.
    """
    tiles = [_tile(sensor_block, "[[SENSOR]]", s) for s in sensors if s]
    if not tiles:
        return {"type": "markdown", "content": ""}
    if len(tiles) == 1:
        return tiles[0]
    return {"type": "vertical-stack", "cards": tiles}


def build_korridor(light_block, sensor_block, zone_lights, sensors_by_group) -> List[dict]:
    """[[ZONES]] коридора/холла: сетки-тройки, пары свет|датчик, перенос по рядам."""
    sizes = balanced_sizes(len(zone_lights))

    grids: List[dict] = []
    idx = 0
    for size in sizes:
        children: List[dict] = [_heading("Группы"), _heading("Датчики")]
        for _ in range(size):
            children.append(_tile(light_block, "[[ZONE_LIGHT]]", zone_lights[idx]))
            children.append(_sensor_cell(sensor_block, sensors_by_group[idx]))
            idx += 1
        grids.append({"type": "grid", "columns": 2, "square": False, "cards": children})

    # одна сетка — без horizontal-stack, во всю ширину (как 3-зонный эталон)
    if len(grids) == 1:
        return grids

    # несколько — по GRIDS_PER_ROW в ряд; недобор в последнем ряду добиваем
    # пустой карточкой, чтобы сетки не растягивались во всю ширину
    rows: List[dict] = []
    for row in _chunks(grids, GRIDS_PER_ROW):
        while len(row) < GRIDS_PER_ROW:
            row.append({"type": "markdown", "content": ""})
        rows.append({
            "type": "horizontal-stack",
            "cards": row,
            "grid_options": {"columns": "full"},
        })
    return rows


def build_special(light_block, sensor_block, zone_lights, sensors_by_group) -> List[dict]:
    """[[ZONES]] спешла: вертикальный список строк [свет | датчик(и)]."""
    rows: List[dict] = []
    for i, light in enumerate(zone_lights):
        cards = [_tile(light_block, "[[ZONE_LIGHT]]", light)]
        cards += [_tile(sensor_block, "[[SENSOR]]", s) for s in sensors_by_group[i] if s]
        rows.append({"type": "horizontal-stack", "cards": cards})
    return rows


def build_class_columns(light_block, sensor_block, label_block,
                        zone_lights, sensors_by_group) -> List[dict]:
    """[[ZONE_COLUMNS]] класса: [свет..., датчик..., подпись...] -> грид разложит в 3 ряда."""
    lights = [_tile(light_block, "[[ZONE_LIGHT]]", z) for z in zone_lights]
    sensors = []
    for grp in sensors_by_group:
        first = next((s for s in grp if s), None)
        sensors.append(_tile(sensor_block, "[[SENSOR]]", first) if first
                       else {"type": "markdown", "content": ""})
    labels = [_tile(label_block, "[[LABEL]]", LABEL_PLACEHOLDER) for _ in zone_lights]
    return lights + sensors + labels


def build_recreation_groups(group_block, zone_lights) -> List[dict]:
    """[[ZONE_GROUPS]] рекреации: узкие группы mushroom по зонам."""
    return [_tile(group_block, "[[ZONE_LIGHT]]", z) for z in zone_lights]


def build_sensors_2col(sensor_block, sensors_flat) -> List[dict]:
    """[[SENSORS_2COL]] рекреации: плитки датчиков (лягут в грид columns:2)."""
    return [_tile(sensor_block, "[[SENSOR]]", s) for s in sensors_flat if s]


def build_nav_map(rooms: List[tuple]) -> str:
    """Строки Jinja-словаря «имя помещения → room_slug» для кнопки перехода.

    Ключи — те же, что в опциях input_select навигации (обе стороны берут
    canon.space_label). Сверка идёт по строке состояния: разойдутся на символ —
    кнопка молча покажет «выберите помещение» при выбранном помещении.
    """
    return ",\n".join(f"  '{label}': '{slug}'" for label, slug in rooms)


def build_main_view(templates_dir: Path, rooms_by_floor: Dict[int, List[tuple]],
                    tech_floors: set, dashboard: str, title: str) -> dict:
    """Главная: блок на этаж — карточка, свет, выбор помещения, переход.

    Собирается текстом, а не структурой: в блоке живут Jinja-карта и CSS
    card_mod, которые владелец правит руками — их надо донести дословно.

    `tech_floors` — этажи, на которых generate_floor_groups реально заведёт
    группу тех.помещений. На остальных плитки не будет: этаж без korridor /
    special / recreation группы не получает, и плитка показывала бы
    «сущность недоступна».
    """
    block_tpl = _strip_header_comments(
        _read(templates_dir / "_blocks" / "main_floor_block.yaml"))
    tech_tpl = _strip_header_comments(
        _read(templates_dir / "_blocks" / "main_tech_tile.yaml"))

    blocks: List[str] = []
    for floor in sorted(rooms_by_floor):
        block = block_tpl
        block = _splice(block, "[[TECH_TILE]]",
                        tech_tpl if floor in tech_floors else "")
        block = block.replace("[[FLOOR_AREA_ID]]", floor_area_id(floor))
        block = block.replace("[[FLOOR_VIEW_PATH]]", V.floor_view_path(floor))
        block = block.replace("[[FLOOR_LIGHT]]", floor_light_entity(floor))
        block = block.replace("[[TECH_LIGHT]]", tech_light_entity(floor))
        block = block.replace("[[NAV_SELECT]]", floor_nav_entity(floor))
        block = block.replace("[[DASHBOARD]]", dashboard)
        block = _splice(block, "[[NAV_MAP]]", build_nav_map(rooms_by_floor[floor]))
        # [[FLOOR]] — последним: он подстрока остальных маркеров только внешне,
        # но порядок всё равно держим предсказуемым.
        block = block.replace("[[FLOOR]]", str(floor))
        blocks.append(block)

    view = _strip_header_comments(_read(templates_dir / "main" / "view.yaml"))
    view = view.replace("[[PATH]]", V.MAIN_PATH)
    view = view.replace("[[TITLE]]", title)
    view = _splice(view, "[[FLOOR_BLOCKS]]", "\n".join(blocks))
    view = _splice(view, "[[SERVICE_BLOCKS]]",
                   build_service_blocks(templates_dir, dashboard))

    return yaml.safe_load(view)


def build_nav_filter(templates_dir: Path) -> str:
    """Панель фильтра навигации: «Все помещения» + шесть типов.

    Собирается из канона, а не перечисляется в шаблоне: те же подписи и иконки
    читает generate_helpers, создавая сами помощники. Разъедутся — в панели
    будет одно имя, в реестре HA другое, и оператор увидит «сущность
    недоступна».

    Панель одинакова на всех страницах, потому что помощники ОБЩИЕ на объект:
    отфильтровали на Главной — этажные страницы уже отфильтрованы.
    """
    panel = _strip_header_comments(
        _read(templates_dir / "_blocks" / "nav_filter.yaml"))
    tile_tpl = _strip_header_comments(
        _read(templates_dir / "_blocks" / "nav_filter_tile.yaml"))

    # «Все» первым — это выключатель фильтра, а не ещё один тип.
    items = [(nav_type_all_entity(), NAV_TYPE_ALL_LABEL, NAV_TYPE_ICONS[NAV_TYPE_ALL_ID])]
    items += [(nav_type_entity(t), label, NAV_TYPE_ICONS[t])
              for t, label in NAV_TYPE_LABELS.items()]

    tiles = []
    for entity, label, icon in items:
        tile = tile_tpl
        tile = tile.replace("[[FILTER_ENTITY]]", entity)
        tile = tile.replace("[[FILTER_LABEL]]", label)
        tile = tile.replace("[[FILTER_ICON]]", icon)
        tiles.append(tile)

    return _splice(panel, "[[FILTER_TILES]]", "\n".join(tiles))


def build_service_blocks(templates_dir: Path, dashboard: str) -> str:
    """Кнопки сервисных страниц: расписание, конфигурация.

    Штучные, из таблицы не выводятся, — поэтому список в каноне, а вид в
    шаблоне. Путь берём из канона, а не из шаблона: по нему же деплой высевает
    саму страницу, и разойдись эти два конца — кнопка уводила бы в
    «view not found».
    """
    tpl = _strip_header_comments(
        _read(templates_dir / "_blocks" / "main_service_block.yaml"))

    blocks: List[str] = []
    for spec in SERVICE_VIEWS:
        block = tpl
        block = block.replace("[[SERVICE_HEADING]]", spec["heading"])
        block = block.replace("[[SERVICE_ICON]]", spec["icon"])
        block = block.replace("[[SERVICE_PATH]]", spec["path"])
        block = block.replace("[[DASHBOARD]]", dashboard)
        blocks.append(block)

    return "\n".join(blocks)


def build_floor_view(templates_dir: Path, floor: int, cards: List[dict],
                     dashboard: str) -> dict:
    """Этажный view из шаблона: шапка, бейджи, компактные карточки.

    Вид целиком в templates/lovelace/floor/view.yaml — владелец правит его сам.
    Код подставляет только то, что знает: путь, номер этажа, иконку, сущность
    группы этажа и дашборд.

    `path` подставляем из кода намеренно: по префиксу `zm-` деплой отличает свои
    views от чужих. Оставь путь на усмотрение шаблона — опечатка в нём
    превратила бы замену view в бесконечное размножение дублей.
    """
    tpl = _strip_header_comments(_read(templates_dir / "floor" / "view.yaml"))

    tpl = tpl.replace("[[PATH]]", V.floor_view_path(floor))
    tpl = tpl.replace("[[FLOOR_ICON]]", floor_icon(floor))
    tpl = tpl.replace("[[FLOOR_LIGHT]]", floor_light_entity(floor))
    tpl = tpl.replace("[[DASHBOARD]]", dashboard)
    tpl = tpl.replace("[[FLOOR]]", str(floor))
    tpl = _splice(tpl, "[[NAV_FILTER]]", build_nav_filter(templates_dir))
    tpl = _splice(tpl, "[[CARDS]]", _dump(cards))

    return yaml.safe_load(tpl)


def build_compact_card(block: dict, heading: str, general_light: str,
                       subview_path: str, space_type: str = "") -> dict:
    """Компактная карточка помещения для этажного view: свет + «Подробнее».

    Получает условие видимости по своему типу — это и есть фильтр навигации.

    ⚠ `visibility` работает потому, что карточка — прямой ребёнок секции.
    Внутри стеков и гридов это свойство игнорируется; наш блок сам грид, но
    лежит в секции, а не внутри другого контейнера. Завернёте карточки во
    что-нибудь ещё — фильтр молча перестанет работать, причём выглядеть это
    будет как «фильтр не нажимается».

    Скрытые карточки секция схлопывает (`.card:has(> *[hidden])`), дыр в
    раскладке не остаётся.
    """
    card = _fill(block, {
        "[[HEADING]]": heading,
        "[[GENERAL_LIGHT]]": general_light,
        "[[SUBVIEW_PATH]]": subview_path,
    })

    if space_type in NAV_TYPE_LABELS:
        # ИЛИ: включён «Все» — фильтр не применяем; либо включён свой тип.
        # `state` принимает список, но здесь нужны РАЗНЫЕ сущности, поэтому or.
        card["visibility"] = [{
            "condition": "or",
            "conditions": [
                {"condition": "state", "entity": nav_type_all_entity(), "state": "on"},
                {"condition": "state", "entity": nav_type_entity(space_type), "state": "on"},
            ],
        }]

    return card


def build_zal_lights(zone_lights) -> List[dict]:
    """[[ZONE_LIGHTS]] зала: плитки групп (свет+яркость, vertical), без блока."""
    return [
        {
            "type": "tile",
            "entity": z,
            "features": [{"type": "light-brightness"}, {"type": "toggle"}],
            "features_position": "bottom",
            "vertical": True,
        }
        for z in zone_lights
    ]


# ============================================================
# Вставка сгенерированного в обёртку
# ============================================================

class _Dumper(yaml.SafeDumper):
    """Свой дампер: многострочные строки пишем блоком `|`, а не с \\n.

    Иначе CSS из card_mod превращается в нечитаемую простыню с экранированием,
    а файлы views существуют ровно затем, чтобы владелец читал их глазами.
    Отдельный класс, а не глобальный представитель, — чтобы не менять вывод
    остальных генераторов, которые тоже зовут yaml в этом же процессе.
    """


def _str_representer(dumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_representer)


def _yaml(obj) -> str:
    return yaml.dump(obj, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     default_flow_style=False)


def _dump(cards: List[dict]) -> str:
    return _yaml(cards).rstrip("\n")


def _splice(text: str, marker: str, block: str) -> str:
    """Заменить строку-маркер на block, выровняв по отступу маркера.

    Пустой block -> строку-маркер убрать (нет зон — нет блока).
    """
    out: List[str] = []
    for line in text.splitlines():
        if marker in line:
            if block.strip():
                indent = len(line) - len(line.lstrip(" "))
                pad = " " * indent
                out.append("\n".join(pad + ln if ln.strip() else ln
                                     for ln in block.splitlines()))
        else:
            out.append(line)
    return "\n".join(out)


def build_card(space_type: str, wrapper: str, blocks: Dict[str, dict],
               row) -> str:
    """Собрать карточку помещения: скаляры + региональные маркеры по типу."""
    space = str(row["space"])
    zone_lights = list(row["zone_light_entities"])
    sensors_by_group = [list(g) for g in row["sensors_by_group"]]

    card = wrapper.replace("[[HEADING]]", build_heading(space))
    card = card.replace("[[GENERAL_LIGHT]]", str(row["general_light_entity"]))

    if space_type in ("korridor", "hall"):
        zones = build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                               zone_lights, sensors_by_group)
        card = _splice(card, "[[ZONES]]", _dump(zones))

    elif space_type == "special":
        zones = build_special(blocks["light_tile"], blocks["sensor_tile"],
                              zone_lights, sensors_by_group)
        card = _splice(card, "[[ZONES]]", _dump(zones))

    elif space_type == "class":
        card = card.replace("[[ZONE_COUNT]]", str(max(1, len(zone_lights))))
        cols = build_class_columns(blocks["light_tile"], blocks["sensor_tile"],
                                   blocks["class_label"], zone_lights, sensors_by_group)
        card = _splice(card, "[[ZONE_COLUMNS]]", _dump(cols))

    elif space_type == "recreation":
        groups = build_recreation_groups(blocks["recreation_group"], zone_lights)
        sensors_flat = [s for grp in sensors_by_group for s in grp if s]
        card = _splice(card, "[[ZONE_GROUPS]]", _dump(groups))
        card = _splice(card, "[[SENSORS_2COL]]", _dump(build_sensors_2col(
            blocks["sensor_tile"], sensors_flat)))

    elif space_type == "zal":
        card = _splice(card, "[[ZONE_LIGHTS]]", _dump(build_zal_lights(zone_lights)))

    return card


def build_heading(space: str) -> str:
    """Заголовок карточки. Правило одно на проект — в каноне: им же подписаны
    опции навигационного input_select и ключи карты «имя → слаг»."""
    return space_label(space)


# ============================================================
# Генерация по объекту
# ============================================================

BLOCK_NAMES = ("light_tile", "sensor_tile", "class_label", "recreation_group",
               "compact_card")


def build_views(spaces_parquet: Path, templates_dir: Path, filters,
                dashboard: str, title: str = ""):
    """Собрать views дашборда: этажные + subview пространств.

    Возвращает (views, report, skipped, excluded). Чистая часть — без записи
    на диск, чтобы её можно было проверить тестами.
    """
    if not spaces_parquet.exists():
        raise FileNotFoundError(f"spaces.parquet не найден: {spaces_parquet}")

    manifest = load_manifest(templates_dir)
    blocks = {name: _load_block(templates_dir, name) for name in BLOCK_NAMES}

    spaces_df = pd.read_parquet(spaces_parquet)
    filtered, excluded = apply_filters(spaces_df, filters)

    # Этажи с группой тех.помещений — тем же правилом, что и в
    # generate_floor_groups: считаем по filtered, а не в цикле сборки карточек.
    # В цикле помещение может быть пропущено (нет типа, нет обёртки), и этаж
    # молча остался бы без плитки при живой группе.
    tech_floors = {
        int(f)
        for f in filtered[filtered["space_type"].isin(TECHNICAL_SPACE_TYPES)
                          & filtered["floor"].notna()]["floor"].unique()
    }

    floor_cards: Dict[int, List[dict]] = {}
    rooms_by_floor: Dict[int, List[tuple]] = {}
    subviews: List[dict] = []
    report: Dict[str, Dict] = {}
    skipped: List[Dict] = []

    for _, row in filtered.iterrows():
        space = str(row["space"])
        space_type = str(row["space_type"]) if row["space_type"] is not None else ""

        if not bool(row["has_valid_type"]):
            skipped.append({"space": space, "reason": "no_valid_type"})
            continue
        wrapper_file = manifest.get(space_type)
        if not wrapper_file:
            skipped.append({"space": space, "reason": f"type_not_in_manifest:{space_type}"})
            continue

        wrapper = _strip_header_comments(_read(templates_dir / wrapper_file))
        # Карточка собирается текстом (в обёртках есть хардкод вроде пресетов
        # зала), а в view кладём уже структурой.
        full_card = yaml.safe_load(build_card(space_type, wrapper, blocks, row))

        room_slug = str(row["room_slug"])
        heading = build_heading(space)
        subviews.append(V.build_space_subview(heading, room_slug, full_card,
                                              space_type=space_type))

        compact = build_compact_card(
            blocks["compact_card"],
            heading=heading,
            general_light=str(row["general_light_entity"]),
            subview_path=f"/{dashboard}/{V.space_view_path(room_slug)}",
            space_type=space_type,
        )
        floor_cards.setdefault(int(row["floor"]), []).append(compact)
        # Для Главной: карта «имя → слаг» и опции навигации строятся из одного
        # списка (canon.space_label) — иначе кнопка перехода молча сломается.
        rooms_by_floor.setdefault(int(row["floor"]), []).append((heading, room_slug))

        report[space] = {
            "space_type": space_type,
            "wrapper": wrapper_file,
            "floor": int(row["floor"]),
            "zones": len(list(row["zone_light_entities"])),
            "subview": V.space_view_path(room_slug),
        }

    floor_views = [
        build_floor_view(templates_dir, f, floor_cards[f], dashboard)
        for f in sorted(floor_cards)
    ]

    views = floor_views + subviews
    if rooms_by_floor:
        views.append(build_main_view(templates_dir, rooms_by_floor, tech_floors,
                                     dashboard, title))

    return V.order_views(views), report, skipped, excluded


def generate_cards(spaces_parquet: Path, templates_dir: Path, out_dir: Path,
                   report_json: Path, filters, dashboard: str,
                   title: str = DEFAULT_TITLE) -> None:
    views, report, skipped, excluded = build_views(
        spaces_parquet, templates_dir, filters, dashboard, title)

    # Файл на view: так глазами видно, что поедет, и диффы читаемы.
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{V.VIEW_PREFIX}*.yaml"):
        old.unlink()                       # чтобы удалённые помещения не оставались
    for view in views:
        path = out_dir / f"{view['path']}.yaml"
        path.write_text(_yaml(view), encoding="utf-8")

    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(
        json.dumps({"version": 3, "dashboard": dashboard,
                    "views": len(views), "cards": len(report),
                    "skipped": skipped, "excluded_by_filter": excluded,
                    "report": report},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    floors = len([v for v in views if v["path"].startswith(V.FLOOR_PREFIX)])
    print("OK: views Lovelace собраны")
    print(f" - этажей: {floors} | пространств: {len(report)} | пропущено: {len(skipped)}")
    print(" - выход :", out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Собрать карточки Lovelace из spaces.parquet и шаблонов.")
    parser.add_argument("--spaces-parquet", dest="spaces_parquet",
                        default=str(DEFAULT_SPACES_PARQUET))
    parser.add_argument("--templates", default=str(DEFAULT_TEMPLATES_DIR))
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--dashboard", default=DEFAULT_DASHBOARD,
                        help="url_path дашборда на объекте (нужен для navigate-путей)")
    parser.add_argument("--title", default=DEFAULT_TITLE,
                        help="Заголовок в шапке Главной (имя объекта)")
    add_filter_args(parser, with_include_floors=True)
    args = parser.parse_args()

    print("\n=== Generate Lovelace Views (v3) ===")
    print("Дашборд :", args.dashboard)
    try:
        generate_cards(
            spaces_parquet=Path(args.spaces_parquet),
            templates_dir=Path(args.templates),
            out_dir=Path(args.out),
            dashboard=args.dashboard,
            title=args.title,
            report_json=Path(args.report),
            filters=filters_from_args(args),
        )
    except (FileNotFoundError, ValueError) as e:
        print("ОШИБКА:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
