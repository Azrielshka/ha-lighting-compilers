# -*- coding: utf-8 -*-
"""
generate_helpers.py
Вспомогательные объекты (helpers) Home Assistant — одним пакетом.

Вход:  data/normalized/spaces.parquet
Выход: data/helpers/lighting-compilers.yaml

Раньше помощников заводил наладчик руками, и забытый всплывал уже на объекте:
без `input_number.vacant_delay_<тип>` свет не гаснет, без `input_select` не работает
навигация с Главной. Теперь их создаёт пайплайн.

Что создаётся:

  input_number.vacant_delay_<тип>  — задержка гашения, ПО ОДНОМУ на тип
                                     помещения. OFF-автоматизация ссылается на
                                     задержку своего типа. Без initial — значение
                                     принадлежит объекту.
  input_button.but_back            — «назад» в бейджах этажных view.
  input_boolean.regim_auto_<N>     — БОЛЬШЕ НЕ СОЗДАЁТСЯ (правка 5): бейдж режима
                                     переключён на switch/гейт Оркестратора.
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
    NAV_TYPE_ALL_ID,
    NAV_TYPE_ALL_LABEL,
    NAV_TYPE_ICONS,
    floor_type_filter_id,
    floor_type_filter_options,
    NAV_PICK_ID,
    ALLOWED_SPACE_TYPES,
    NAV_TYPE_LABELS,
    nav_pick_options,
    nav_type_id,
    BACK_BUTTON_ID,
    NAV_PLACEHOLDER,
    space_label,
    space_sort_key,
    VACANT_DELAY_MAX,
    VACANT_DELAY_MIN,
    VACANT_DELAY_STEP,
    vacant_delay_id,
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

    # Помещения по этажам. Порядок опций задаётся ниже — по номеру, возрастание
    # (space_sort_key), а не как в таблице: в списке навигации так искать легче.
    by_floor: Dict[int, List[str]] = {}
    types_by_floor: Dict[int, set] = {}
    for _, row in filtered.iterrows():
        if pd.isna(row["floor"]):
            continue
        fl = int(row["floor"])
        by_floor.setdefault(fl, []).append(space_label(row["space"]))
        st = row["space_type"]
        if st is not None and str(st) in NAV_TYPE_LABELS:
            types_by_floor.setdefault(fl, set()).add(str(st))

    floors = sorted(by_floor)

    # Задержка гашения — по одному input_number на КАЖДЫЙ тип помещения
    # (2026-07-23). Все 6 канонических, порядок стабилен (sorted). БЕЗ initial:
    # значение принадлежит объекту, наладчик выставляет его под тип и оно
    # сохраняется между рестартами (см. canon про снятый initial и его цену).
    numbers = {
        vacant_delay_id(space_type): {
            "name": f"Задержка гашения — {NAV_TYPE_LABELS[space_type]}",
            "min": VACANT_DELAY_MIN,
            "max": VACANT_DELAY_MAX,
            "step": VACANT_DELAY_STEP,
            "unit_of_measurement": "с",
            "mode": "box",
            "icon": "mdi:timer-outline",
        }
        for space_type in sorted(ALLOWED_SPACE_TYPES)
    }

    buttons = {
        BACK_BUTTON_ID: {"name": "Назад", "icon": "mdi:skip-backward"},
    }

    booleans: Dict[str, Dict] = {}
    # Правка 5 (2026-07-23): генерация regim_auto ПРЕКРАЩЕНА. Их логику забрал
    # Оркестратор здания: бейдж режима на этажном view переключён на его switch
    # (switch.orkestrator_..._avtomatika_etazh_<N>) + гейт-индикатор датчиков.
    # Оставлено закомментированным, а не удалено, — на случай отката/истории.
    #
    # ⚠ На объектах, где regim_auto уже создан, сущности останутся осиротевшими:
    # удаление из генерируемого файла их не сносит, нужна ручная уборка.
    # for floor in floors:
    #     booleans[floor_auto_mode_id(floor)] = {
    #         "name": f"Автоматический режим — {floor} этаж",
    #         "icon": "mdi:motion-sensor",
    #     }
    for preset_id, title in ZAL_PRESETS.items():
        booleans[preset_id] = {"name": title, "icon": "mdi:theater"}

    # Фильтр навигации по типу помещения. ОБЩИЙ на объект, а не на этаж:
    # обход «только коридоры» не должен сбрасываться при переходе между
    # этажами, и это 7 сущностей вместо 7×N.
    #
    # ⚠ «Все» с initial: on — чтобы на свежем объекте было видно ВСЁ. Забудете
    # initial, и после первого старта HA дашборд окажется пустым: все фильтры
    # выключены, ни одна карточка помещения условие не проходит. Выглядит как
    # поломка генератора, а не как «фильтр не настроен».
    booleans[NAV_TYPE_ALL_ID] = {
        "name": NAV_TYPE_ALL_LABEL,
        "icon": NAV_TYPE_ICONS[NAV_TYPE_ALL_ID],
        "initial": True,
    }
    # Типы создаём ВСЕ шесть, даже если на объекте таких помещений нет.
    # Панель фильтров одна на объект и захардкожена; помощник, которого нет,
    # показал бы в ней «сущность недоступна».
    for space_type, label in NAV_TYPE_LABELS.items():
        booleans[nav_type_id(space_type)] = {
            "name": label,
            "icon": NAV_TYPE_ICONS[space_type],
        }

    # Заглушка первой опцией и она же initial: при загрузке ничего не выбрано.
    # В карту перехода она не попадает — см. canon.NAV_PLACEHOLDER.
    selects: Dict[str, Dict] = {}

    # ⚠ ВРЕМЕННОЕ (2026-07-20): второй фильтр тем же набором типов, но списком.
    # Заведён, чтобы сравнить на объекте два вида управления — семь плиток
    # против одного селекта. После сравнения один из двух уходит; убирая
    # проигравший, снимите и соответствующее условие в build_compact_card.
    selects[NAV_PICK_ID] = {
        "name": "Фильтр: тип помещения",
        "options": nav_pick_options(),
        "initial": nav_pick_options()[0],   # «Все помещения» — фильтр не сужает
        "icon": "mdi:filter-menu",
    }

    # Фильтр групп по типу — ПО ОДНОМУ на этаж (плитка в блоке этажа под switch).
    # Опции — только присутствующие на этаже типы + заглушка. Выбрал тип —
    # conditional-плитка группы этого типа показывается на этом этаже.
    for floor in floors:
        opts = floor_type_filter_options(types_by_floor.get(floor, set()))
        selects[floor_type_filter_id(floor)] = {
            "name": f"Группы по типу — {floor} этаж",
            "options": opts,
            "initial": opts[0],
            "icon": "mdi:home-group",
        }

    for floor in floors:
        selects[floor_nav_id(floor)] = {
            "name": f"Помещения {floor} этажа",
            "options": [NAV_PLACEHOLDER] + sorted(by_floor[floor], key=space_sort_key),
            "initial": NAV_PLACEHOLDER,
            "icon": "mdi:door",
        }

    print(f"  Этажей:               {len(floors)}")
    print(f"  input_number:         {len(numbers)} (задержка гашения на тип помещения)")
    print(f"  input_button:         {len(buttons)}")
    # «режимы этажей» ушли из счётчика: regim_auto больше не генерится (правка 5).
    print(f"  input_boolean:        {len(booleans)} "
          f"(пресеты зала: {len(ZAL_PRESETS)}, "
          f"фильтр типов: {len(NAV_TYPE_LABELS) + 1})")
    print(f"  input_select:         {len(selects)}")
    print("  ⚠ У задержек гашения нет initial: на ПЕРВОМ старте HA каждая = 0")
    print("    (свет гаснет мгновенно). Выставьте значения под типы на объекте —")
    print("    дальше они сохраняются между перезапусками.")

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
        "# Пайплайн создаёт сами объекты, но НЕ логику за ними: пресеты зала —\n"
        "# это выключатели, их поведение описывают ваши\n"
        "# автоматизации. Исключение — vacant_delay, nav_floor_<N> и nav_type_*:\n"
        "# их читает сгенерированный код (OFF-автоматизации, кнопка перехода\n"
        "# на Главной и условия видимости карточек помещений).\n"
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
