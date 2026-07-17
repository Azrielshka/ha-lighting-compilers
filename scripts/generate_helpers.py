# -*- coding: utf-8 -*-
"""
generate_helpers.py
Вспомогательные объекты (helpers) Home Assistant — одним пакетом.

Вход:  data/normalized/spaces.parquet
Выход: data/helpers/lighting-compilers.yaml

Раньше помощников заводил наладчик руками, и забытый всплывал уже на объекте:
без `input_number.vacant_delay` свет не гаснет, без `input_select` не работает
навигация с Главной. Теперь их создаёт пайплайн.

Что создаётся:

  input_number.vacant_delay        — задержка перехода в vacant. Один на объект,
                                     на него ссылается КАЖДАЯ OFF-автоматизация.
  input_button.but_back            — «назад» в бейджах этажных view.
  input_boolean.regim_auto_<N>     — бейдж режима, по одному на этаж.
  input_boolean.<пресет зала>       — 4 сценария зала.
  input_select.nav_floor_<N>       — выбор помещения на Главной, по одному на
                                     этаж. Опции — помещения этажа.

⚠ Пайплайн создаёт САМ ОБЪЕКТ, но не логику за ним. `input_boolean.rezhim_tetra`
появится, но «Режим театра» ничего не сделает, пока владелец не напишет
автоматизацию. Исключение — vacant_delay и nav_floor_<N>: их читает наш код.

Файл — пакет: у HA `packages: !include_dir_merge_named includes/packages/`,
поэтому в нём корневой ключ = имя пакета, а внутри домены `input_*`.
Шаг офлайновый: к Home Assistant не подключается.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

from scripts._lib.canon import (
    BACK_BUTTON_ID,
    NAV_PLACEHOLDER,
    space_label,
    VACANT_DELAY_DEFAULT,
    VACANT_DELAY_ID,
    VACANT_DELAY_MAX,
    VACANT_DELAY_MIN,
    VACANT_DELAY_STEP,
    ZAL_PRESETS,
    floor_auto_mode_id,
    floor_nav_id,
)
from scripts._lib.filters import (
    Filters,
    add_filter_args,
    apply_filters,
    filters_from_args,
    print_filter_report,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "helpers" / "lighting-compilers.yaml"

# Имя пакета — корневой ключ файла. merge_named требует его: каждый файл
# в includes/packages/ становится пакетом с этим именем.
PACKAGE_KEY = "lighting_compilers"


def build_payload(spaces_df: pd.DataFrame, filters: Filters) -> Dict:
    """Собрать содержимое пакета помощников."""
    total = len(spaces_df)
    filtered, excluded = apply_filters(spaces_df, filters)

    print_filter_report(
        "Вспомогательные объекты",
        filters,
        total=total,
        kept=len(filtered),
        excluded=excluded,
    )

    # Помещения по этажам — в порядке таблицы, как и везде.
    by_floor: Dict[int, List[str]] = {}
    for _, row in filtered.iterrows():
        if pd.isna(row["floor"]):
            continue
        by_floor.setdefault(int(row["floor"]), []).append(space_label(row["space"]))

    floors = sorted(by_floor)

    numbers = {
        VACANT_DELAY_ID: {
            "name": "Задержка перехода в vacant",
            "min": VACANT_DELAY_MIN,
            "max": VACANT_DELAY_MAX,
            "step": VACANT_DELAY_STEP,
            "initial": VACANT_DELAY_DEFAULT,
            "unit_of_measurement": "с",
            "mode": "box",
            "icon": "mdi:timer-outline",
        }
    }

    buttons = {
        BACK_BUTTON_ID: {"name": "Назад", "icon": "mdi:skip-backward"},
    }

    booleans: Dict[str, Dict] = {}
    for floor in floors:
        booleans[floor_auto_mode_id(floor)] = {
            "name": f"Автоматический режим — {floor} этаж",
            "icon": "mdi:motion-sensor",
        }
    for preset_id, title in ZAL_PRESETS.items():
        booleans[preset_id] = {"name": title, "icon": "mdi:theater"}

    # Заглушка первой опцией и она же initial: при загрузке ничего не выбрано.
    # В карту перехода она не попадает — см. canon.NAV_PLACEHOLDER.
    selects: Dict[str, Dict] = {}
    for floor in floors:
        selects[floor_nav_id(floor)] = {
            "name": f"Помещения {floor} этажа",
            "options": [NAV_PLACEHOLDER] + by_floor[floor],
            "initial": NAV_PLACEHOLDER,
            "icon": "mdi:door",
        }

    print(f"  Этажей:               {len(floors)}")
    print(f"  input_number:         {len(numbers)}")
    print(f"  input_button:         {len(buttons)}")
    print(f"  input_boolean:        {len(booleans)} "
          f"(режимы этажей: {len(floors)}, пресеты зала: {len(ZAL_PRESETS)})")
    print(f"  input_select:         {len(selects)}")

    return {
        "input_number": numbers,
        "input_button": buttons,
        "input_boolean": booleans,
        "input_select": selects,
    }


def render_yaml(payload: Dict) -> str:
    """Пакет как текст. Пустой результат объясняем — иначе выглядит поломкой."""
    import yaml as _yaml

    if not payload.get("input_select") and not payload.get("input_boolean"):
        return (
            "# Вспомогательные объекты не сгенерированы: в выборке нет помещений\n"
            "# с указанным этажом. Проверьте таблицу и фильтры.\n"
        )

    header = (
        "# Вспомогательные объекты (helpers) для Home Assistant.\n"
        "#\n"
        "# Сгенерировано generate_helpers.py — правки здесь перезатрёт деплой.\n"
        "# Значения задаются в scripts/_lib/canon.py.\n"
        "#\n"
        "# Пайплайн создаёт сами объекты, но НЕ логику за ними: пресеты зала и\n"
        "# режимы этажей — это выключатели, их поведение описывают ваши\n"
        "# автоматизации. Исключение — vacant_delay и nav_floor_<N>: их читает\n"
        "# сгенерированный код (OFF-автоматизации и кнопка перехода на Главной).\n"
        "#\n"
        "# ⚠ initial у vacant_delay применяется при КАЖДОМ старте HA, а не\n"
        "# только при создании. Это осознанно: значение принадлежит пайплайну.\n"
    )
    body = _yaml.safe_dump(
        {PACKAGE_KEY: payload},
        sort_keys=False, allow_unicode=True, default_flow_style=False,
    )
    return header + body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Собрать вспомогательные объекты HA одним пакетом.")
    parser.add_argument("--normalized", default=str(DEFAULT_NORMALIZED_DIR))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH))
    add_filter_args(parser, with_include_floors=True)
    args = parser.parse_args()

    print("\n=== Generate Helpers ===")

    from scripts._lib.normalized import load_dataset

    try:
        spaces = load_dataset(Path(args.normalized), "spaces")
    except (FileNotFoundError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        print("   Сначала запустите normalize_excel.py", file=sys.stderr)
        return 2

    payload = build_payload(spaces, filters_from_args(args))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_yaml(payload), encoding="utf-8")

    print(f"\nOK: {out}")
    print("   Файл офлайновый. Чтобы создать помощников в HA — шаг деплоя.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
