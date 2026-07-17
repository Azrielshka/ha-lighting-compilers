# -*- coding: utf-8 -*-
"""
generate_general_groups.py
Генератор общих групп помещений.

Вход:  data/normalized/spaces.parquet
Выход: data/light_groups/lights_general_groups.yaml

Каждое помещение получает одну общую группу, объединяющую его зоны:

    light.<room_slug>_obshchii  ->  light.<group_id_1>, light.<group_id_2>, ...

Имя собирается ТОЛЬКО из названия помещения:

    103_Вестибюль -> 103_vestibiul -> 103_vestibiul_obshchii

Тип помещения (space_type) в имени НЕ участвует и на генерацию не влияет:
общую группу получают все помещения — коридоры, залы, тамбуры.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import sys
from pathlib import Path
from typing import List

from scripts._lib.canon import GENERAL_LIGHT_RULE
from scripts._lib.filters import (
    Filters,
    add_filter_args,
    apply_filters,
    filters_from_args,
    print_filter_report,
)
from scripts._lib.normalized import NormalizedLayerError, load_dataset
from scripts._lib.yaml_render import LightGroup, render_document

__version__ = "3.0.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "light_groups" / "lights_general_groups.yaml"

ROOT_KEY = "lights_general_group"


def general_object_id(room_slug: str) -> str:
    """
    object_id общей группы: <room_slug>_obshchii

    В YAML это и name, и unique_id. Домен добавляет Home Assistant,
    получая light.<room_slug>_obshchii — то же, что лежит в
    spaces.general_light_entity.
    """
    return f"{room_slug}{GENERAL_LIGHT_RULE.suffix}"


def build_yaml(spaces_df, filters: Filters) -> str:
    """Собрать YAML общих групп из spaces.parquet."""
    total_spaces = len(spaces_df)
    filtered, excluded = apply_filters(spaces_df, filters)

    print_filter_report(
        "Общие группы помещений",
        filters,
        total=total_spaces,
        kept=len(filtered),
        excluded=excluded,
    )

    if filtered.empty:
        print("\n⚠ После фильтров не осталось помещений — YAML будет пустым.")
        return render_document(ROOT_KEY, [], "Нет данных для генерации общих групп")

    groups: List[LightGroup] = []

    for _, row in filtered.iterrows():
        zones = list(row["zone_light_entities"])

        # Помещение без зон — ошибка таблицы (E09), сюда дойти не должно.
        if not zones:
            print(f"  ⚠ помещение {row['space']} без групп — пропущено")
            continue

        object_id = general_object_id(str(row["room_slug"]))

        groups.append(LightGroup(
            unique_id=object_id,
            name=object_id,
            entities=zones,
            comment=f"Общая группа для {row['space']}",
        ))

    zone_total = sum(len(g.entities) for g in groups)
    print(f"  Общих групп:          {len(groups)}")
    print(f"  Зон в них:            {zone_total}")

    return render_document(ROOT_KEY, groups, "Нет данных для генерации общих групп")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сгенерировать YAML общих групп помещений из нормализованного слоя.",
    )
    parser.add_argument("--normalized", default=str(DEFAULT_NORMALIZED_DIR),
                        help="Папка с parquet")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH),
                        help="Куда записать YAML")
    add_filter_args(parser)
    args = parser.parse_args()

    output_path = Path(args.out)

    print("\n=== Generate General Groups ===")
    print("Источник:", args.normalized)
    print("Выход   :", output_path)
    print()

    try:
        spaces_df = load_dataset(Path(args.normalized), "spaces")
    except NormalizedLayerError as exc:
        print(f"❌ {exc}")
        return 2

    yaml_text = build_yaml(spaces_df, filters_from_args(args))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")

    print(f"\nOK: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
