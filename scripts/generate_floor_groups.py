# -*- coding: utf-8 -*-
"""
generate_floor_groups.py
Генератор групп этажей.

Вход:  data/normalized/spaces.parquet
Выход: data/light_groups/lights_floor_groups.yaml

Группа этажа собирается НЕ из ламп, а из общих групп помещений:

    floor_1_all  ->  light.101_tambur_obshchii, light.102_tambur_obshchii, ...

Поэтому она согласована с generate_general_groups.py: те же помещения,
те же фильтры. Если помещение исключено фильтром здесь, но не там (или
наоборот), в HA появится группа, ссылающаяся на несуществующую сущность.

Этаж берётся из колонки «Этаж» таблицы, а не из адреса: помещение может
физически стоять на границе (лестница), и в группу этажа должно попасть
туда, куда его отнёс проектировщик.

Опционально — группа технических помещений этажа (tex_floor_<n>).
Состав TECHNICAL_SPACE_TYPES пока не согласован, флаг по умолчанию выключен.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

from scripts._lib.canon import TECHNICAL_SPACE_TYPES
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
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "light_groups" / "lights_floor_groups.yaml"

ROOT_KEY = "lights_floor_group"


def floor_group_name(floor: int) -> str:
    """«Весь 1-й этаж» — отображаемое имя."""
    return f"Весь {floor}-й этаж"


def floor_group_unique_id(floor: int) -> str:
    """floor_1_all"""
    return f"floor_{floor}_all"


def tech_group_name(floor: int) -> str:
    """«Тех.пом 1-й этаж»"""
    return f"Тех.пом {floor}-й этаж"


def tech_group_unique_id(floor: int) -> str:
    """tex_floor_1"""
    return f"tex_floor_{floor}"


def build_yaml(spaces_df: pd.DataFrame, filters: Filters, tech_groups: bool) -> str:
    """Собрать YAML групп этажей из spaces.parquet."""
    total_spaces = len(spaces_df)
    filtered, excluded = apply_filters(spaces_df, filters)

    print_filter_report(
        "Группы этажей",
        filters,
        total=total_spaces,
        kept=len(filtered),
        excluded=excluded,
    )

    # Помещение без этажа в группу этажа попасть не может.
    no_floor = filtered[filtered["floor"].isna()]
    for _, row in no_floor.iterrows():
        print(f"  ⚠ у помещения {row['space']} не указан этаж — пропущено")

    filtered = filtered[filtered["floor"].notna()]

    if filtered.empty:
        print("\n⚠ После фильтров не осталось помещений — YAML будет пустым.")
        return render_document(ROOT_KEY, [], "Нет данных для формирования групп по этажам")

    groups: List[LightGroup] = []
    tech_count = 0

    # Этажи по возрастанию; помещения внутри — в порядке таблицы.
    for floor in sorted(filtered["floor"].unique()):
        floor = int(floor)
        fdf = filtered[filtered["floor"] == floor]

        entities = fdf["general_light_entity"].tolist()

        groups.append(LightGroup(
            unique_id=floor_group_unique_id(floor),
            name=floor_group_name(floor),
            entities=entities,
            comment=f"Группа для всего {floor}-го этажа",
        ))

        if not tech_groups:
            continue

        tech_df = fdf[fdf["space_type"].isin(TECHNICAL_SPACE_TYPES)]
        if tech_df.empty:
            continue

        tech_count += 1
        groups.append(LightGroup(
            unique_id=tech_group_unique_id(floor),
            name=tech_group_name(floor),
            entities=tech_df["general_light_entity"].tolist(),
            comment=f"Группа для тех помещений {floor}-го этажа",
        ))

    floors = sorted(filtered["floor"].unique())
    print(f"  Этажей:               {len(floors)} ({', '.join(str(int(f)) for f in floors)})")
    print(f"  Помещений в группах:  {len(filtered)}")

    if tech_groups:
        types = ", ".join(sorted(TECHNICAL_SPACE_TYPES))
        print(f"  Тех.группы:           {tech_count} (типы: {types})")
    else:
        print("  Тех.группы:           выключены (--generate-tech-groups)")

    return render_document(ROOT_KEY, groups, "Нет данных для формирования групп по этажам")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сгенерировать YAML групп этажей из нормализованного слоя.",
    )
    parser.add_argument("--normalized", default=str(DEFAULT_NORMALIZED_DIR),
                        help="Папка с parquet")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH),
                        help="Куда записать YAML")
    parser.add_argument("--generate-tech-groups", action="store_true",
                        help=f"Дополнительно создать tex_floor_<n> "
                             f"для типов: {', '.join(sorted(TECHNICAL_SPACE_TYPES))}")
    add_filter_args(parser, with_include_floors=True)
    args = parser.parse_args()

    output_path = Path(args.out)

    print("\n=== Generate Floor Groups ===")
    print("Источник:", args.normalized)
    print("Выход   :", output_path)
    print()

    try:
        spaces_df = load_dataset(Path(args.normalized), "spaces")
    except NormalizedLayerError as exc:
        print(f"❌ {exc}")
        return 2

    yaml_text = build_yaml(spaces_df, filters_from_args(args), args.generate_tech_groups)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")

    print(f"\nOK: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
