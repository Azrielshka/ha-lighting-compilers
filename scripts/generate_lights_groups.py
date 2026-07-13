# -*- coding: utf-8 -*-
"""
generate_lights_groups.py
Генератор подгрупп света (зон).

Вход:  data/normalized/groups.parquet
Выход: data/light_groups/lights_group.yaml

Каждая группа из таблицы становится одной light-группой:

    light.<group_id>  ->  все лампы этой группы

Помещения без типа сюда ПОПАДАЮТ: лампы в них физически существуют.
Тип нужен только для карточек Lovelace.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import sys
from pathlib import Path
from typing import List

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
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "light_groups" / "lights_group.yaml"

ROOT_KEY = "lights_group"


def build_yaml(groups_df, filters: Filters) -> str:
    """Собрать YAML подгрупп света из groups.parquet."""
    total_spaces = groups_df["space"].nunique()
    filtered, excluded = apply_filters(groups_df, filters)

    print_filter_report(
        "Подгруппы света (зоны)",
        filters,
        total=total_spaces,
        kept=filtered["space"].nunique(),
        excluded=excluded,
    )

    if filtered.empty:
        print("\n⚠ После фильтров не осталось групп — YAML будет пустым.")
        return render_document(ROOT_KEY, [], "Нет данных для генерации групп")

    groups: List[LightGroup] = []
    current_space = None

    # Порядок — как в таблице: наладчик сверяет YAML со своим Excel.
    for _, row in filtered.iterrows():
        lamps = list(row["lamps"])

        # Группа без ламп — это ошибка таблицы (E08), сюда она дойти не должна.
        # Но если дошла (запуск с --force), пустую группу в HA не отдаём.
        if not lamps:
            print(f"  ⚠ группа {row['group_id']} без ламп — пропущена")
            continue

        comment = ""
        if row["space"] != current_space:
            current_space = row["space"]
            comment = f"Группы для {current_space}"

        groups.append(LightGroup(
            unique_id=str(row["group_id"]),
            name=str(row["group_id"]),
            entities=lamps,
            comment=comment,
        ))

    lamp_total = sum(len(g.entities) for g in groups)
    print(f"  Групп в YAML:         {len(groups)}")
    print(f"  Ламп в группах:       {lamp_total}")

    return render_document(ROOT_KEY, groups, "Нет данных для генерации групп")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сгенерировать YAML подгрупп света (зон) из нормализованного слоя.",
    )
    parser.add_argument("--normalized", default=str(DEFAULT_NORMALIZED_DIR),
                        help="Папка с parquet")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH),
                        help="Куда записать YAML")
    add_filter_args(parser)
    args = parser.parse_args()

    output_path = Path(args.out)

    print("\n=== Generate Lights Groups ===")
    print("Источник:", args.normalized)
    print("Выход   :", output_path)
    print()

    try:
        groups_df = load_dataset(Path(args.normalized), "groups")
    except NormalizedLayerError as exc:
        print(f"❌ {exc}")
        return 2

    yaml_text = build_yaml(groups_df, filters_from_args(args))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")

    print(f"\nOK: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
