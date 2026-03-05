# -*- coding: utf-8 -*-
"""
normalize_excel.py
Новый нормализатор Excel -> канонические данные проекта.

Что делает:
1) Читает Excel (исходную таблицу устройств)
2) Строит 2 датафрейма:
   - device_rows.parquet: построчный слой
   - spaces.parquet: агрегированный слой по помещениям (для Lovelace)
3) Пишет normalized_meta.json (паспорт генерации)

Зачем нужен:
- все последующие генераторы будут читать нормализованный слой, а не Excel напрямую
- правила (ffill, group->sensor, уникальность датчиков) фиксируются в одном месте
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pyarrow as pa
import pyarrow.parquet as pq

from typing import Dict, List, Optional, Tuple
from pathlib import Path

import pandas as pd

from scripts._lib.canon import NORMALIZED_SCHEMA_VERSION, GENERAL_LIGHT_RULE, ALLOWED_CARD_TYPES
from scripts._lib.excel_schema import COLUMNS
from scripts._lib.naming import slugify_room

# Корень проекта (на уровень выше папки scripts)
BASE_DIR = Path(__file__).resolve().parent.parent

# ===== CONFIG (для запуска из PyCharm) =====
DEFAULT_EXCEL_PATH = str(BASE_DIR / "data" / "Тестовая таблица.xlsx")
DEFAULT_OUTPUT_DIR = str(BASE_DIR / "data" / "normalized")
DEFAULT_SHEET_NAME = None

def _ensure_dir(path: str) -> None:
    """Создаёт папку, если её нет (нужно для data/normalized/*)."""
    os.makedirs(path, exist_ok=True)


def _pick_first_existing(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """
    Возвращает первое имя колонки из списка, которое реально существует в df.
    Зачем: устойчивость к изменениям таблицы.
    """
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _ffill_series(s: pd.Series) -> pd.Series:
    """Безопасный ffill (пустые строки тоже считаем пустыми)."""
    # Пустые строки -> NaN, чтобы ffill работал предсказуемо
    s2 = s.replace("", pd.NA)
    return s2.ffill()


def _to_str_nullable(s: pd.Series) -> pd.Series:
    """Приводит серию к строкам, сохраняя NA (нужно для смешанных типов вроде '22/21')."""
    return s.apply(lambda x: pd.NA if pd.isna(x) else str(x).strip())

def _normalize_card_type_per_space(df: pd.DataFrame, space_col: str, card_type_col: str) -> pd.Series:
    """
    card_type может быть указан только на первой строке помещения.
    Протягиваем внутри помещения вниз.
    """
    if card_type_col not in df.columns:
        return pd.Series([pd.NA] * len(df), index=df.index)

    tmp = df[[space_col, card_type_col]].copy()
    tmp[card_type_col] = tmp[card_type_col].replace("", pd.NA)

    # ffill внутри группы space
    return tmp.groupby(space_col, dropna=False)[card_type_col].ffill()


def _build_group_and_sensor_by_rule(
    df: pd.DataFrame,
    group_raw_col: Optional[str],
    sensor_raw_col: Optional[str],
    group_auto_col: Optional[str],
    sensor_auto_col: Optional[str],
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Канон: группа задаётся в "сырых" колонках:
    - group_id берём из строки, где group_raw не пусто
    - затем протягиваем вниз до следующей группы
    - ms_sensor берём из sensor_raw ТОЛЬКО на стартовой строке группы и протягиваем внутри группы

    Если "сырых" колонок нет — используем auto-колонки как fallback.

    Возвращает:
    - group_id_series
    - ms_sensor_series (ffill по группе)
    - is_group_start (bool) — для диагностики
    """
    if group_raw_col and sensor_raw_col:
        group_start = df[group_raw_col].replace("", pd.NA).notna()
        group_id = df[group_raw_col].replace("", pd.NA)
        group_id = group_id.ffill()

        # датчик берём только на стартовой строке группы
        sensor_start_values = df[sensor_raw_col].replace("", pd.NA).where(group_start, pd.NA)
        ms_sensor = sensor_start_values.groupby(group_id, dropna=False).ffill()

        return group_id, ms_sensor, group_start

    # Fallback на auto-колонки (если пользовательская логика уже заложена в Excel)
    if group_auto_col:
        group_id = df[group_auto_col].replace("", pd.NA)
    else:
        group_id = pd.Series([pd.NA] * len(df), index=df.index)

    if sensor_auto_col:
        ms_sensor = df[sensor_auto_col].replace("", pd.NA)
    else:
        ms_sensor = pd.Series([pd.NA] * len(df), index=df.index)

    group_start = group_id.notna()
    return group_id, ms_sensor, group_start


def _unique_ms_sensors_by_group(groups: List[str], sensors_by_group: List[Optional[str]]) -> Tuple[List[Optional[str]], List[str]]:
    """
    Убираем повторы датчиков в пределах помещения:
    - если датчик уже использовался ранее в карточке, пытаемся оставить None и пишем warning
    (в будущем можно добавить поиск альтернативы внутри группы, если в данных она появится)

    Возвращает:
    - sensors_by_group_unique (список той же длины)
    - warnings (список строк)
    """
    used = set()
    out: List[Optional[str]] = []
    warnings: List[str] = []

    for g, s in zip(groups, sensors_by_group):
        if s is None or (isinstance(s, float) and pd.isna(s)):
            out.append(None)
            continue

        s_str = str(s).strip()
        if not s_str:
            out.append(None)
            continue

        # Если датчик повторяется — считаем это проблемой и НЕ дублируем в карточке
        if s_str in used:
            out.append(None)
            warnings.append(f"duplicate_ms_sensor: group {g} repeats {s_str}")
            continue

        used.add(s_str)
        out.append(s_str)

    return out, warnings


def normalize(
    excel_path: str,
    output_dir: str = "data/normalized",
    sheet_name: Optional[str] = None,
) -> None:
    """
    Главная функция:
    - читает Excel
    - строит parquet + meta.json
    """
    # 1) читаем Excel
    df = pd.read_excel(excel_path, sheet_name=sheet_name) if sheet_name else pd.read_excel(excel_path)

    # 2) выбираем колонки (устойчиво)
    space_col = _pick_first_existing(df, [COLUMNS.space_auto, COLUMNS.space_raw])
    floor_col = _pick_first_existing(df, [COLUMNS.floor_auto, COLUMNS.floor_raw])
    dali_bus_col = _pick_first_existing(df, [COLUMNS.dali_bus_auto, COLUMNS.dali_bus_raw])
    button_col = _pick_first_existing(df, [COLUMNS.button_auto, COLUMNS.button_raw])
    lamp_col = _pick_first_existing(df, [COLUMNS.lamp_raw])

    # "сырые" колонки для канона D->G (в терминах заголовков)
    group_raw_col = _pick_first_existing(df, [COLUMNS.group_raw])
    sensor_raw_col = _pick_first_existing(df, [COLUMNS.sensor_raw])

    # auto fallback
    group_auto_col = _pick_first_existing(df, [COLUMNS.group_auto])
    sensor_auto_col = _pick_first_existing(df, [COLUMNS.sensor_auto])

    card_type_col = _pick_first_existing(df, [COLUMNS.card_type])

    if not space_col:
        raise ValueError("Не найдена колонка помещения. Ожидали 'Помещение (авто)' или 'Помещение'.")

    # 3) базовая нормализация space/floor (ffill по листу)
    df["__space"] = _ffill_series(df[space_col])
    df["__floor"] = _ffill_series(df[floor_col]) if floor_col else pd.NA

    # floor приводим к int, если возможно
    df["__floor"] = pd.to_numeric(df["__floor"], errors="coerce").astype("Int64")

    # 4) group_id и ms_sensor по канону
    group_id, ms_sensor, is_group_start = _build_group_and_sensor_by_rule(
        df=df,
        group_raw_col=group_raw_col,
        sensor_raw_col=sensor_raw_col,
        group_auto_col=group_auto_col,
        sensor_auto_col=sensor_auto_col,
    )
    df["__group_id"] = group_id
    df["__ms_sensor_id"] = ms_sensor

    # 5) card_type протягиваем в рамках помещения
    df["__card_type"] = _normalize_card_type_per_space(df, "__space", card_type_col) if card_type_col else pd.NA

    # Валидация card_type (мягкая): неизвестные оставляем, но пометим в warnings потом
    # (строгую ошибку не делаем, чтобы не ломать пайплайн)
    # 6) room_slug
    df["__room_slug"] = df["__space"].astype(str).map(slugify_room)

    # 7) собираем device_rows
    device_rows = pd.DataFrame({
        "row_id": df.index.astype(int) + 1,   # +1, чтобы было ближе к "номеру строки" (условно)
        "space_raw": df[space_col] if space_col in df.columns else pd.NA,
        "space": df["__space"],
        "room_slug": df["__room_slug"],
        "floor": df["__floor"],
        "card_type": df["__card_type"],
        "group_id": df["__group_id"],
        "ms_sensor_id": df["__ms_sensor_id"],
        "lamp_id": _to_str_nullable(df[lamp_col]) if lamp_col else pd.Series([pd.NA]*len(df)),
        "dali_bus": _to_str_nullable(df[dali_bus_col]) if dali_bus_col else pd.Series([pd.NA]*len(df)),
        "kp_id": _to_str_nullable(df[button_col]) if button_col else pd.Series([pd.NA]*len(df)),
        "is_group_start": is_group_start,
    })

    # Приводим ключевые поля к строкам/NA, чтобы parquet-писатель не спотыкался о mixed types
    for _col in ["space_raw","space","room_slug","card_type","group_id","ms_sensor_id","lamp_id","dali_bus","kp_id"]:
        if _col in device_rows.columns:
            device_rows[_col] = _to_str_nullable(device_rows[_col])

    # 8) агрегируем spaces
    spaces_records: List[Dict] = []
    warnings_summary: Dict[str, List[str]] = {
        "spaces_without_card_type": [],
        "spaces_with_unknown_card_type": [],
        "spaces_with_duplicate_ms_sensor": [],
    }

    for space, sdf in device_rows.groupby("space", dropna=False, sort=False):
        space_str = str(space)

        # Порядок групп: как встретились впервые в таблице
        groups_order = []
        seen_groups = set()
        for g in sdf["group_id"].tolist():
            if pd.isna(g):
                continue
            g_str = str(g).strip()
            if not g_str:
                continue
            if g_str not in seen_groups:
                seen_groups.add(g_str)
                groups_order.append(g_str)

        # Датчик по группе: берём значение ms_sensor_id на стартовой строке группы (is_group_start=True)
        group_to_sensor: Dict[str, Optional[str]] = {}
        for g in groups_order:
            start_rows = sdf[(sdf["group_id"].astype(str) == g) & (sdf["is_group_start"] == True)]
            sensor_val = None
            if not start_rows.empty:
                raw = start_rows.iloc[0]["ms_sensor_id"]
                if not pd.isna(raw) and str(raw).strip():
                    sensor_val = str(raw).strip()
            group_to_sensor[g] = sensor_val

        sensors_by_group = [group_to_sensor.get(g) for g in groups_order]
        sensors_by_group_unique, dupe_warnings = _unique_ms_sensors_by_group(groups_order, sensors_by_group)

        # Приводим датчики к HA entity_id (sensor.<id>) если надо.
        # Сейчас в таблице датчики вида "1.20.3". Договорённость на будущее:
        # - если датчик уже начинается с "sensor." — оставляем
        # - иначе делаем "sensor." + id, заменяя недопустимые символы ('.' -> '_')
        def to_sensor_entity(x: Optional[str]) -> Optional[str]:
            if x is None:
                return None
            s = str(x).strip()
            if not s:
                return None
            if s.startswith("sensor."):
                return s
            # Иначе: датчики в таблице вида "1.20.3" -> sensor.ms_1_20_3
            clean = s.replace(".", "_").replace("-", "_")
            return "sensor.ms_" + clean

        ms_sensors_by_group = [to_sensor_entity(x) for x in sensors_by_group_unique]
        ms_sensors_unique = sorted({s for s in ms_sensors_by_group if s}, key=lambda z: z)

        # card_type берём первый непустой
        ct = None
        for v in sdf["card_type"].tolist():
            if pd.isna(v):
                continue
            v_str = str(v).strip()
            if v_str:
                ct = v_str
                break

        warnings: List[str] = []
        if ct is None:
            warnings.append("missing_card_type")
            warnings_summary["spaces_without_card_type"].append(space_str)
            ct = "generic"

        if ct not in ALLOWED_CARD_TYPES:
            warnings.append(f"unknown_card_type:{ct}")
            warnings_summary["spaces_with_unknown_card_type"].append(space_str)

        if dupe_warnings:
            warnings.extend(dupe_warnings)
            warnings_summary["spaces_with_duplicate_ms_sensor"].append(space_str)

        room_slug = sdf["room_slug"].iloc[0]
        floor = sdf["floor"].iloc[0]
        general_light_entity = GENERAL_LIGHT_RULE.build(room_slug)

        spaces_records.append({
            "space": space_str,
            "room_slug": room_slug,
            "floor": int(floor) if not pd.isna(floor) else None,
            "card_type": ct,
            "groups": groups_order,
            "groups_count": len(groups_order),
            "general_light_entity": general_light_entity,
            # Важно для Lovelace: строго по группе, без повторов
            "ms_sensors_by_group": ms_sensors_by_group,
            "ms_sensors_unique": ms_sensors_unique,
            "warnings": warnings,
        })

    spaces = pd.DataFrame(spaces_records)

    # 9) пишем файлы
    _ensure_dir(output_dir)
    device_rows_path = os.path.join(output_dir, "device_rows.parquet")
    spaces_path = os.path.join(output_dir, "spaces.parquet")
    meta_path = os.path.join(output_dir, "normalized_meta.json")

    # Parquet
    # Пишем через pyarrow напрямую (устойчивее, чем pandas.to_parquet в разных окружениях)
    device_rows_tbl = pa.Table.from_pandas(device_rows, preserve_index=False)
    spaces_tbl = pa.Table.from_pandas(spaces, preserve_index=False)

    pq.write_table(device_rows_tbl, device_rows_path)
    pq.write_table(spaces_tbl, spaces_path)
    # Meta json
    meta = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_file": excel_path,
        "output_files": {
            "device_rows": device_rows_path,
            "spaces": spaces_path,
        },
        "stats": {
            "excel_rows": int(len(df)),
            "device_rows": int(len(device_rows)),
            "spaces": int(len(spaces)),
        },
        "columns": {
            "device_rows": list(device_rows.columns),
            "spaces": list(spaces.columns),
        },
        "warnings_summary": warnings_summary,
        "notes": {
            "zone_light_rule": "ZONE_LIGHT_i = 'light.' + groups[i-1]",
            "ms_sensor_rule": "MS sensor taken from column 'Датчик' only on group start rows (where 'Группа' is filled). Duplicates are removed (set to null) in ms_sensors_by_group.",
            "general_light_rule": "general_light_entity = 'light.' + room_slug + '_obshchii'",
        },
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("OK: wrote")
    print(" -", device_rows_path)
    print(" -", spaces_path)
    print(" -", meta_path)


def main() -> None:
    """
    CLI-обёртка, чтобы запускать из терминала PyCharm:
    python scripts/normalize_excel.py --excel data/Тестовая таблица.xlsx
    """
    parser = argparse.ArgumentParser(description="Normalize Excel table into canonical parquet datasets.")
    parser.add_argument(
        "--excel",
        default=DEFAULT_EXCEL_PATH,
        help="Path to source Excel file"
    )

    parser.add_argument(
        "--out",
        default=DEFAULT_OUTPUT_DIR,
        help="Output folder"
    )

    parser.add_argument(
        "--sheet",
        default=DEFAULT_SHEET_NAME,
        help="Excel sheet"
    )
    args = parser.parse_args()

    # --- Лог запуска (для удобства отладки) ---
    print("\n=== Normalize Excel ===")
    print("Excel file :", args.excel)
    print("Output dir :", args.out)
    print("Sheet      :", args.sheet)
    print()

    normalize(excel_path=args.excel, output_dir=args.out, sheet_name=args.sheet)


if __name__ == "__main__":
    main()
