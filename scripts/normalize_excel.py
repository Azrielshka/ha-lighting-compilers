# -*- coding: utf-8 -*-
"""
normalize_excel.py
Excel -> канонический нормализованный слой (parquet).

Что делает:
1) Читает лист "Проектная БД"
2) Строит 3 датасета:
   - devices.parquet  строка = ОДНО устройство (лампа / датчик / панель)
   - groups.parquet   агрегат по группам света
   - spaces.parquet   агрегат по помещениям (для карточек и групп этажей)
3) Пишет normalized_meta.json (паспорт генерации)

Единственное место, где читается Excel. Все генераторы работают с parquet.

Модель данных: docs/internal/data_model_v2.md
Ключевое правило: устройство принадлежит группе, указанной в ЕГО СОБСТВЕННОЙ строке.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import datetime as dt
import json
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts._lib.canon import (
    ALLOWED_SPACE_TYPES,
    NORMALIZED_SCHEMA_VERSION,
    general_light_entity,
    is_blank,
    is_none_token,
    lamp_entity,
    normalize_space_type,
    panel_entity,
    parse_addr,
    sensor_illuminance_entity,
    sensor_motion_entity,
    zone_light_entity,
)
from scripts._lib.excel_schema import COLUMNS, DEVICE_COLUMNS, REQUIRED_COLUMNS, SHEET_NAME
from scripts._lib.naming import slugify_room
from scripts._lib.schemas import SCHEMAS

__version__ = "3.0.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_EXCEL_PATH = PROJECT_ROOT / "data" / "object_example.xlsx"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "normalized"

# Первая строка данных в Excel: 1 — заголовок.
FIRST_DATA_ROW = 2


# ============================================================
# ЧТЕНИЕ EXCEL
# ============================================================

def read_sheet(excel_path: Path, sheet_name: str = SHEET_NAME) -> pd.DataFrame:
    """
    Прочитать лист проектной БД.

    keep_default_na=False обязателен: иначе pandas считает строку "None"
    пропущенным значением, и различие между "устройства нет" и "ячейка не
    заполнена" исчезает — а на нём держится вся модель (см. data_model_v2.md).
    """
    with warnings.catch_warnings():
        # openpyxl ругается на выпадающие списки листа ПНР — нам это неинтересно.
        warnings.filterwarnings("ignore", message=".*Data Validation extension.*")
        book = pd.ExcelFile(excel_path)

        if sheet_name not in book.sheet_names:
            raise ValueError(
                f"в книге нет листа {sheet_name!r}; есть: {', '.join(book.sheet_names)}"
            )

        df = book.parse(sheet_name=sheet_name, dtype=object,
                        keep_default_na=False, na_values=[])

    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"в листе нет обязательных колонок: {', '.join(missing)}")

    return df


def _cell(raw: object) -> str:
    """Ячейка как строка без хвостовых пробелов; пустая -> ''."""
    return "" if is_blank(raw) else str(raw).strip()


def _to_int(raw: object) -> Optional[int]:
    """Число из ячейки Excel: 1, '1', 1.0 -> 1. Мусор -> None."""
    if is_blank(raw):
        return None
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


# ============================================================
# DEVICES
# ============================================================

def build_devices(df: pd.DataFrame) -> pd.DataFrame:
    """
    Развернуть таблицу в длинный формат: строка = одно устройство.

    Одна строка Excel может дать до трёх устройств (лампа + датчик + панель) —
    каждое привязано к группе из своей же строки.

    Ячейки с None/нет/- в devices не попадают: отсутствие устройства
    не является устройством.
    """
    records: List[Dict] = []

    current_space = ""
    current_type: Optional[str] = None

    for idx, row in df.iterrows():
        excel_row = int(idx) + FIRST_DATA_ROW

        # Помещение и тип объявляются на первой строке помещения и тянутся вниз.
        space_cell = _cell(row.get(COLUMNS.space))
        if space_cell:
            current_space = space_cell
            current_type = normalize_space_type(row.get(COLUMNS.space_type))

        if not current_space:
            continue  # строка до первого помещения — валидатор про неё уже сказал

        group_id = _cell(row.get(COLUMNS.group))
        if not group_id:
            continue  # устройство не к чему привязать (E12)

        floor = _to_int(row.get(COLUMNS.floor))
        dali_bus = _cell(row.get(COLUMNS.dali_bus))
        room_slug = slugify_room(current_space)

        for kind, column in DEVICE_COLUMNS.items():
            raw = row.get(column)

            if is_blank(raw) or is_none_token(raw):
                continue

            try:
                addr = parse_addr(raw)
            except ValueError:
                # Мусор в ячейке — это ошибка валидации (E03/E14).
                # Здесь пропускаем: normalize не место для диагностики.
                continue

            if kind == "lamp":
                entity_id, entity_id_2 = lamp_entity(addr), None
            elif kind == "sensor":
                entity_id, entity_id_2 = sensor_motion_entity(addr), sensor_illuminance_entity(addr)
            else:
                entity_id, entity_id_2 = panel_entity(addr), None

            records.append({
                "row_id": excel_row,
                "kind": kind,
                "addr": str(addr),
                "addr_floor": addr.floor,
                "addr_bus": addr.bus,
                "addr_num": addr.num,
                "entity_id": entity_id,
                "entity_id_2": entity_id_2,
                "group_id": group_id,
                "space": current_space,
                "room_slug": room_slug,
                "floor": floor,
                "space_type": current_type,
                "dali_bus": dali_bus or None,
            })

    devices = pd.DataFrame.from_records(records, columns=[
        "row_id", "kind", "addr", "addr_floor", "addr_bus", "addr_num",
        "entity_id", "entity_id_2", "group_id", "space", "room_slug",
        "floor", "space_type", "dali_bus",
    ])

    for col in ("row_id", "addr_floor", "addr_bus", "addr_num", "floor"):
        devices[col] = devices[col].astype("Int64")

    return devices


# ============================================================
# GROUPS
# ============================================================

def build_groups(devices: pd.DataFrame) -> pd.DataFrame:
    """
    Агрегат по группам света.

    Порядок групп и устройств внутри — как в таблице: наладчик читает отчёты
    и YAML сверху вниз и ожидает увидеть тот же порядок, что у себя в Excel.
    """
    records: List[Dict] = []

    for group_id, gdf in devices.groupby("group_id", sort=False):
        first = gdf.iloc[0]

        lamps = gdf[gdf["kind"] == "lamp"]
        sensors = gdf[gdf["kind"] == "sensor"]
        panels = gdf[gdf["kind"] == "panel"]

        records.append({
            "group_id": str(group_id),
            "space": first["space"],
            "room_slug": first["room_slug"],
            "floor": first["floor"],
            "space_type": first["space_type"],
            "zone_light_entity": zone_light_entity(str(group_id)),
            "lamps": lamps["entity_id"].tolist(),
            "sensors_ms": sensors["entity_id"].tolist(),
            "sensors_il": sensors["entity_id_2"].tolist(),
            "panels": panels["entity_id"].tolist(),
            "lamp_count": len(lamps),
            "sensor_count": len(sensors),
            "panel_count": len(panels),
        })

    groups = pd.DataFrame.from_records(records, columns=[
        "group_id", "space", "room_slug", "floor", "space_type", "zone_light_entity",
        "lamps", "sensors_ms", "sensors_il", "panels",
        "lamp_count", "sensor_count", "panel_count",
    ])

    groups["floor"] = groups["floor"].astype("Int64")
    for col in ("lamp_count", "sensor_count", "panel_count"):
        groups[col] = groups[col].astype("int64")

    return groups


# ============================================================
# SPACES
# ============================================================

def build_spaces(devices: pd.DataFrame, groups: pd.DataFrame) -> pd.DataFrame:
    """
    Агрегат по помещениям: для общих групп, групп этажей и карточек Lovelace.

    has_valid_type=False означает, что помещение не попадёт в карточки,
    но останется в группах света: лампы в нём физически существуют.
    """
    records: List[Dict] = []

    for space, sdf in devices.groupby("space", sort=False):
        first = sdf.iloc[0]
        space_type = first["space_type"]
        room_slug = first["room_slug"]

        gdf = groups[groups["space"] == space]

        warnings_: List[str] = []
        if space_type is None:
            warnings_.append("missing_space_type")
        elif space_type not in ALLOWED_SPACE_TYPES:
            warnings_.append(f"unknown_space_type:{space_type}")

        records.append({
            "space": str(space),
            "room_slug": room_slug,
            "floor": first["floor"],
            "space_type": space_type,
            "has_valid_type": space_type in ALLOWED_SPACE_TYPES,
            "groups": gdf["group_id"].tolist(),
            "groups_count": len(gdf),
            "general_light_entity": general_light_entity(room_slug),
            "zone_light_entities": gdf["zone_light_entity"].tolist(),
            # Списки по группам: индекс i соответствует groups[i].
            # Пустой вложенный список = у группы нет датчиков (норма для zal).
            "sensors_by_group": [list(x) for x in gdf["sensors_ms"]],
            "panels_by_group": [list(x) for x in gdf["panels"]],
            "sensors_unique": sorted({s for lst in gdf["sensors_ms"] for s in lst}),
            "warnings": warnings_,
        })

    spaces = pd.DataFrame.from_records(records, columns=[
        "space", "room_slug", "floor", "space_type", "has_valid_type",
        "groups", "groups_count", "general_light_entity", "zone_light_entities",
        "sensors_by_group", "panels_by_group", "sensors_unique", "warnings",
    ])

    spaces["floor"] = spaces["floor"].astype("Int64")
    spaces["groups_count"] = spaces["groups_count"].astype("int64")

    return spaces


# ============================================================
# ЗАПИСЬ
# ============================================================

def normalize(
    excel_path: Path,
    output_dir: Path,
    sheet_name: str = SHEET_NAME,
) -> Dict:
    """Прочитать Excel и записать нормализованный слой. Возвращает meta."""
    df = read_sheet(excel_path, sheet_name)

    devices = build_devices(df)
    groups = build_groups(devices)
    spaces = build_spaces(devices, groups)

    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "devices": output_dir / "devices.parquet",
        "groups": output_dir / "groups.parquet",
        "spaces": output_dir / "spaces.parquet",
    }

    # Пишем СТРОГО по объявленной схеме, а не выводим её из данных.
    # Иначе на объекте без единой панели panels_by_group получил бы тип
    # list<list<null>> вместо list<list<string>> — и генератор сломался бы
    # не у нас, а у наладчика. Подробности: scripts/_lib/schemas.py
    for name, frame in (("devices", devices), ("groups", groups), ("spaces", spaces)):
        table = pa.Table.from_pandas(frame, schema=SCHEMAS[name], preserve_index=False)
        pq.write_table(table, paths[name])

    # Схема v1 писала device_rows.parquet. Если он остался от прошлого запуска,
    # генераторы могли бы прочитать устаревшие данные и не заметить этого.
    stale = output_dir / "device_rows.parquet"
    if stale.exists():
        stale.unlink()

    kinds = devices["kind"].value_counts().to_dict()

    meta = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "generator_version": __version__,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_file": str(excel_path),
        "sheet_name": sheet_name,
        "output_files": {k: str(v) for k, v in paths.items()},
        "stats": {
            "excel_rows": int(len(df)),
            "devices": int(len(devices)),
            "lamps": int(kinds.get("lamp", 0)),
            "sensors": int(kinds.get("sensor", 0)),
            "panels": int(kinds.get("panel", 0)),
            "groups": int(len(groups)),
            "spaces": int(len(spaces)),
            "spaces_without_valid_type": int((~spaces["has_valid_type"]).sum()),
        },
        "columns": {
            "devices": list(devices.columns),
            "groups": list(groups.columns),
            "spaces": list(spaces.columns),
        },
        "notes": {
            "device_binding": "устройство принадлежит группе из своей строки Excel",
            "sensor_entities": "один адрес датчика -> sensor.ms_* и sensor.il_*",
            "zone_light_rule": "light.<group_id>",
            "general_light_rule": "light.<room_slug>_obshchii",
            "absent_devices": "ячейки None/нет/- в devices не попадают",
        },
    }

    meta_path = output_dir / "normalized_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return meta


def _print_stats(meta: Dict, output_dir: Path) -> None:
    s = meta["stats"]
    print("📊 Нормализовано:")
    print(f"  Строк Excel:   {s['excel_rows']}")
    print(f"  Устройств:     {s['devices']}")
    print(f"    лампы:       {s['lamps']}")
    print(f"    датчики:     {s['sensors']}  (+{s['sensors']} сущностей освещённости)")
    print(f"    панели:      {s['panels']}")
    print(f"  Групп:         {s['groups']}")
    print(f"  Помещений:     {s['spaces']}")

    if s["spaces_without_valid_type"]:
        print(f"\n⚠ Помещений без корректного типа: {s['spaces_without_valid_type']}")
        print("  Они попадут в группы света, но не в карточки Lovelace.")

    print(f"\nOK: записано в {output_dir}")
    for name, path in meta["output_files"].items():
        print(f" - {Path(path).name}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Нормализовать Excel в канонический parquet-слой.",
    )
    parser.add_argument("--excel", default=str(DEFAULT_EXCEL_PATH), help="Путь к Excel-файлу")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_DIR), help="Папка вывода")
    parser.add_argument("--sheet", default=SHEET_NAME, help="Имя листа")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Нормализовать даже при блокирующих ошибках в таблице",
    )
    args = parser.parse_args()

    excel_path = Path(args.excel)
    output_dir = Path(args.out)

    print("\n=== Normalize Excel ===")
    print("Excel  :", excel_path)
    print("Sheet  :", args.sheet)
    print("Output :", output_dir)
    print()

    if not excel_path.exists():
        print(f"❌ Файл не найден: {excel_path}")
        return 2

    # Проверяем таблицу перед нормализацией. Шаг validate остаётся отдельным
    # и самостоятельным, но молча нормализовать заведомо битую таблицу нельзя:
    # ошибки всплывут уже в Home Assistant.
    from validate_excel import validate  # локальный импорт: normalize не зависит от CLI валидатора

    findings, _ = validate(excel_path, args.sheet)
    errors = [f for f in findings if f.severity == "error"]

    if errors:
        print(f"❌ В таблице {len(errors)} блокирующих ошибок — нормализация отменена.")
        print("   Запустите validate_excel.py, чтобы увидеть полный список.\n")
        for f in errors[:10]:
            where = f"строка {f.row}: " if f.row else ""
            print(f"   [{f.code}] {where}{f.message}")
        if len(errors) > 10:
            print(f"   … ещё {len(errors) - 10}")

        if not args.force:
            print("\n   Обойти проверку: --force (на свой страх)")
            return 1

        print("\n⚠ --force: нормализуем несмотря на ошибки\n")

    try:
        meta = normalize(excel_path, output_dir, args.sheet)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    _print_stats(meta, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
