# -*- coding: utf-8 -*-
"""
show_normalized.py
Показать содержимое нормализованного слоя (parquet — бинарный, глазами не открыть).

Инструмент отладки: ничего не генерирует и не меняет.

Примеры:
    python scripts/show_normalized.py                    # обзор всех трёх датасетов
    python scripts/show_normalized.py --space 102        # всё про помещение
    python scripts/show_normalized.py --group 102_1      # всё про группу
    python scripts/show_normalized.py --devices --full   # таблица устройств целиком
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = PROJECT_ROOT / "data" / "normalized"

# Сколько строк печатать без --full.
PREVIEW_ROWS = 12


def _fmt_list(value) -> str:
    """Список entity_id -> компактная строка."""
    items = list(value) if value is not None else []
    return ", ".join(str(x) for x in items) if items else "—"


def _print_frame(df: pd.DataFrame, columns: List[str], full: bool) -> None:
    if df.empty:
        print("  (пусто)")
        return

    shown = df if full else df.head(PREVIEW_ROWS)

    with pd.option_context("display.width", 250,
                           "display.max_colwidth", 45,
                           "display.max_columns", None):
        # У лампы нет второй сущности — печатаем прочерк, а не NaN:
        # NaN в таблице читается как поломка, хотя это норма.
        print(shown[columns].to_string(index=False, na_rep="—"))

    hidden = len(df) - len(shown)
    if hidden > 0:
        print(f"  … ещё {hidden} строк (--full, чтобы показать все)")


def show_meta(path: Path) -> None:
    meta_path = path / "normalized_meta.json"
    if not meta_path.exists():
        return

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    stats = meta.get("stats", {})

    print("📋 Паспорт нормализации")
    print(f"  Схема:      v{meta.get('schema_version')}")
    print(f"  Источник:   {Path(meta.get('source_file', '')).name}")
    print(f"  Лист:       {meta.get('sheet_name')}")
    print(f"  Собрано:    {meta.get('generated_at', '')[:19].replace('T', ' ')} UTC")
    print()
    print(f"  Устройств:  {stats.get('devices')}"
          f"  (ламп {stats.get('lamps')}, датчиков {stats.get('sensors')}, "
          f"панелей {stats.get('panels')})")
    print(f"  Групп:      {stats.get('groups')}")
    print(f"  Помещений:  {stats.get('spaces')}")

    without_type = stats.get("spaces_without_valid_type", 0)
    if without_type:
        print(f"\n  ⚠ Без корректного типа: {without_type} — не попадут в карточки")
    print()


def show_devices(devices: pd.DataFrame, full: bool) -> None:
    print("🔌 devices — строка = одно устройство")
    _print_frame(
        devices,
        ["row_id", "kind", "addr", "entity_id", "entity_id_2", "group_id", "space"],
        full,
    )
    print()


def show_groups(groups: pd.DataFrame, full: bool) -> None:
    print("💡 groups — группы света (зоны)")
    _print_frame(
        groups,
        ["group_id", "zone_light_entity", "lamp_count", "sensor_count",
         "panel_count", "space_type", "space"],
        full,
    )
    print()


def show_spaces(spaces: pd.DataFrame, full: bool) -> None:
    print("🏢 spaces — помещения")
    _print_frame(
        spaces,
        ["space", "room_slug", "floor", "space_type", "has_valid_type",
         "groups_count", "general_light_entity"],
        full,
    )
    print()


def show_space_detail(space_query: str, devices: pd.DataFrame,
                      groups: pd.DataFrame, spaces: pd.DataFrame) -> None:
    """Всё про одно помещение: группы, их состав, сущности."""
    match = spaces[spaces["space"].str.contains(space_query, case=False, na=False)]

    if match.empty:
        print(f"❌ Помещение не найдено: {space_query!r}")
        print(f"   Есть: {', '.join(spaces['space'].tolist())}")
        return

    for _, s in match.iterrows():
        print(f"🏢 {s['space']}")
        print(f"   Тип:          {s['space_type'] or '— не указан —'}"
              f"{'' if s['has_valid_type'] else '  ⚠ карточка не будет создана'}")
        print(f"   Этаж:         {s['floor']}")
        print(f"   room_slug:    {s['room_slug']}")
        print(f"   Общий свет:   {s['general_light_entity']}")
        print()

        gdf = groups[groups["space"] == s["space"]]

        for _, g in gdf.iterrows():
            print(f"   ── Группа {g['group_id']}  →  {g['zone_light_entity']}")
            print(f"      Лампы ({g['lamp_count']}):    {_fmt_list(g['lamps'])}")
            print(f"      Движение ({g['sensor_count']}): {_fmt_list(g['sensors_ms'])}")
            print(f"      Освещённость: {_fmt_list(g['sensors_il'])}")
            print(f"      Панели ({g['panel_count']}):   {_fmt_list(g['panels'])}")
            print()

        if len(s["warnings"]):
            print(f"   ⚠ {', '.join(s['warnings'])}\n")


def show_group_detail(group_id: str, groups: pd.DataFrame, devices: pd.DataFrame) -> None:
    """Всё про одну группу, включая строки Excel, откуда она собрана."""
    match = groups[groups["group_id"] == group_id]

    if match.empty:
        print(f"❌ Группа не найдена: {group_id!r}")
        print(f"   Есть: {', '.join(groups['group_id'].tolist())}")
        return

    g = match.iloc[0]

    print(f"💡 Группа {g['group_id']}  →  {g['zone_light_entity']}")
    print(f"   Помещение:    {g['space']}  ({g['space_type'] or '— тип не указан —'})")
    print(f"   Этаж:         {g['floor']}")
    print()
    print(f"   Лампы ({g['lamp_count']}):    {_fmt_list(g['lamps'])}")
    print(f"   Движение ({g['sensor_count']}): {_fmt_list(g['sensors_ms'])}")
    print(f"   Освещённость: {_fmt_list(g['sensors_il'])}")
    print(f"   Панели ({g['panel_count']}):   {_fmt_list(g['panels'])}")
    print()
    print("   Строки Excel, из которых собрана группа:")

    gdev = devices[devices["group_id"] == group_id]
    with pd.option_context("display.width", 200, "display.max_colwidth", 40):
        print(gdev[["row_id", "kind", "addr", "entity_id"]].to_string(index=False))
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Показать нормализованный слой (parquet).",
    )
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help="Папка с parquet")
    parser.add_argument("--devices", action="store_true", help="Только устройства")
    parser.add_argument("--groups", action="store_true", help="Только группы")
    parser.add_argument("--spaces", action="store_true", help="Только помещения")
    parser.add_argument("--space", metavar="ИМЯ", help="Подробно про помещение (поиск по подстроке)")
    parser.add_argument("--group", metavar="ID", help="Подробно про группу")
    parser.add_argument("--full", action="store_true", help="Показать все строки, а не первые 12")
    args = parser.parse_args()

    path = Path(args.dir)

    missing = [n for n in ("devices", "groups", "spaces")
               if not (path / f"{n}.parquet").exists()]
    if missing:
        print(f"❌ В {path} нет файлов: {', '.join(missing)}")
        print("   Сначала запустите normalize_excel.py")
        return 2

    devices = pd.read_parquet(path / "devices.parquet")
    groups = pd.read_parquet(path / "groups.parquet")
    spaces = pd.read_parquet(path / "spaces.parquet")

    print()

    if args.space:
        show_space_detail(args.space, devices, groups, spaces)
        return 0

    if args.group:
        show_group_detail(args.group, groups, devices)
        return 0

    # Явно выбранные датасеты, иначе — обзор всех.
    picked = args.devices or args.groups or args.spaces

    if not picked:
        show_meta(path)

    if args.devices or not picked:
        show_devices(devices, args.full)
    if args.groups or not picked:
        show_groups(groups, args.full)
    if args.spaces or not picked:
        show_spaces(spaces, args.full)

    if not args.full and not picked:
        print("Подсказки:")
        print("  --full            показать все строки")
        print("  --space 102       подробно про помещение")
        print("  --group 102_1     подробно про группу")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
