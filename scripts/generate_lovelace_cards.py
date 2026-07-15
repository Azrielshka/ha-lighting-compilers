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

from scripts._lib.filters import add_filter_args, apply_filters, filters_from_args

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SPACES_PARQUET = PROJECT_ROOT / "data" / "normalized" / "spaces.parquet"
DEFAULT_TEMPLATES_DIR = PROJECT_ROOT / "templates" / "lovelace"
DEFAULT_OUTPUT_TXT = PROJECT_ROOT / "data" / "lovelace_cards_generated.txt"
DEFAULT_REPORT_JSON = PROJECT_ROOT / "data" / "lovelace_cards_report.json"

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


def _tile(block: dict, placeholder: str, value: str) -> dict:
    """Копия блок-плитки с подставленной сущностью."""
    out = copy.deepcopy(block)
    for k, v in out.items():
        if v == placeholder:
            out[k] = value
    return out


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

def _dump(cards: List[dict]) -> str:
    return yaml.safe_dump(cards, sort_keys=False, allow_unicode=True,
                          default_flow_style=False).rstrip("\n")


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
    return str(space).replace("_", " ").strip()


# ============================================================
# Генерация по объекту
# ============================================================

BLOCK_NAMES = ("light_tile", "sensor_tile", "class_label", "recreation_group")


def generate_cards(spaces_parquet: Path, templates_dir: Path,
                   output_txt: Path, report_json: Path, filters) -> None:
    if not spaces_parquet.exists():
        raise FileNotFoundError(f"spaces.parquet не найден: {spaces_parquet}")

    manifest = load_manifest(templates_dir)
    blocks = {name: _load_block(templates_dir, name) for name in BLOCK_NAMES}

    spaces_df = pd.read_parquet(spaces_parquet)
    filtered, excluded = apply_filters(spaces_df, filters)

    out_blocks: List[str] = []
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
        card = build_card(space_type, wrapper, blocks, row)

        header = f"# ─── {space}  ({space_type}) ───"
        out_blocks.append(header + "\n" + card.rstrip() + "\n")
        report[space] = {
            "space_type": space_type,
            "wrapper": wrapper_file,
            "zones": len(list(row["zone_light_entities"])),
        }

    output_txt.parent.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    output_txt.write_text("\n".join(out_blocks), encoding="utf-8")
    report_json.write_text(
        json.dumps({"version": 3, "cards": len(report), "skipped": skipped,
                    "excluded_by_filter": excluded, "report": report},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("OK: карточки Lovelace собраны")
    print(" - карточек:", len(report), "| пропущено:", len(skipped))
    print(" - выход :", output_txt)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Собрать карточки Lovelace из spaces.parquet и шаблонов.")
    parser.add_argument("--spaces-parquet", dest="spaces_parquet",
                        default=str(DEFAULT_SPACES_PARQUET))
    parser.add_argument("--templates", default=str(DEFAULT_TEMPLATES_DIR))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_TXT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_JSON))
    add_filter_args(parser, with_include_floors=True)
    args = parser.parse_args()

    print("\n=== Generate Lovelace Cards (v3) ===")
    try:
        generate_cards(
            spaces_parquet=Path(args.spaces_parquet),
            templates_dir=Path(args.templates),
            output_txt=Path(args.out),
            report_json=Path(args.report),
            filters=filters_from_args(args),
        )
    except (FileNotFoundError, ValueError) as e:
        print("ОШИБКА:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
