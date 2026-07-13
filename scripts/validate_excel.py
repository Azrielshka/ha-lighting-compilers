# -*- coding: utf-8 -*-
"""
validate_excel.py
Первый шаг пайплайна: проверка входной таблицы ДО генерации чего-либо.

Ничего не пишет в data/normalized/. Пишет отчёт data/validation_report.json
и возвращает ненулевой код возврата при блокирующих ошибках.

Зачем: на объекте в 12 этажей таблица — тысячи строк, и опечатка вида
"одна лампа в двух группах" обнаружится уже в Home Assistant.

Правила и их коды: docs/ROADMAP.md, этап 2.
Модель данных: docs/internal/data_model_v2.md.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import datetime as dt
import json
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from scripts._lib.canon import (
    ALLOWED_SPACE_TYPES,
    MAX_SENSORS_PER_UNIT,
    Addr,
    family_for_space_type,
    is_blank,
    is_none_token,
    normalize_space_type,
    parse_addr,
)
from scripts._lib.excel_schema import (
    COLUMNS,
    DEVICE_COLUMNS,
    REQUIRED_COLUMNS,
    SHEET_NAME,
)

__version__ = "1.0.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_EXCEL_PATH = PROJECT_ROOT / "data" / "object_example.xlsx"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "validation_report.json"

# Первая строка данных в Excel: 1 — заголовок, значит данные начинаются со 2-й.
FIRST_DATA_ROW = 2

# Сколько находок одного кода печатать в консоль (в JSON попадают все).
CONSOLE_LIMIT = 20


# ============================================================
# НАХОДКИ
# ============================================================

@dataclass
class Finding:
    """Одна проблема: код, тяжесть, где нашли, что не так."""
    code: str
    severity: str  # "error" | "warning"
    message: str
    row: Optional[int] = None
    space: Optional[str] = None
    group: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "row": self.row,
            "space": self.space,
            "group": self.group,
            "message": self.message,
        }


RULE_TITLES: Dict[str, str] = {
    "E01": "нет листа с проектной БД",
    "E02": "нет обязательной колонки",
    "E03": "адрес лампы не в формате X.Y.Z",
    "E04": "дубликат адреса лампы",
    "E05": "дубликат адреса датчика",
    "E06": "дубликат адреса панели",
    "E07": "один датчик привязан к двум группам",
    "E08": "группа без ламп",
    "E09": "помещение без ламп",
    "E10": "в помещении не указан датчик (нет ни адреса, ни None)",
    "E11": "в помещении не указана панель (нет ни адреса, ни None)",
    "E12": "устройство в строке без группы",
    "E13": "группа встречается в двух помещениях",
    "E14": "нераспознанное значение в колонке устройства",
    "W01": "помещение без типа (исключается из карточек)",
    "W02": "неизвестный тип помещения",
    "W03": "этаж в адресе не совпадает с колонкой «Этаж»",
    "W04": "шина в адресе не совпадает с колонкой «Шина DALI»",
    "W05": "группа без датчиков",
    "W06": "пустая строка внутри листа",
    "W07": "в единице обслуживания больше 12 датчиков",
    "W08": "помещение с автоматизациями, но без датчиков",
    "E15": "блок смешивает разные семейства",
    "E16": "блок задан у помещения, которое не автоматизируется",
}


# ============================================================
# РАЗБОР СТРОК
# ============================================================

@dataclass
class DeviceCell:
    """Результат разбора ячейки устройства."""
    kind: str                    # lamp | sensor | panel
    raw: str
    addr: Optional[Addr] = None  # разобранный адрес
    declared_absent: bool = False  # ячейка = None / нет / -


@dataclass
class SpaceAcc:
    """Накопитель по помещению."""
    name: str
    rows: List[int] = field(default_factory=list)
    space_type: Optional[str] = None
    block: Optional[str] = None
    groups: List[str] = field(default_factory=list)
    lamp_count: int = 0
    sensor_count: int = 0
    # Правило "либо датчик, либо None" проверяется на уровне помещения:
    # достаточно одной непустой ячейки на всё помещение.
    sensor_declared: bool = False
    panel_declared: bool = False


@dataclass
class GroupAcc:
    """Накопитель по группе."""
    group_id: str
    spaces: List[str] = field(default_factory=list)
    rows: List[int] = field(default_factory=list)
    lamp_count: int = 0
    sensor_count: int = 0
    panel_count: int = 0


def _to_int(raw: object) -> Optional[int]:
    """Число из ячейки Excel: 1, '1', 1.0 -> 1. Мусор -> None."""
    if is_blank(raw):
        return None
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _cell(raw: object) -> str:
    """Ячейка как строка без хвостовых пробелов."""
    return "" if is_blank(raw) else str(raw).strip()


def _parse_device_cell(kind: str, raw: object, findings: List[Finding], row: int,
                       space: Optional[str], group: Optional[str]) -> Optional[DeviceCell]:
    """
    Разобрать ячейку устройства.

    Пустая -> None (в этой строке про устройство ничего не сказано).
    None/нет/- -> устройства по проекту нет.
    X.Y.Z -> адрес.
    Иначе -> ошибка: E03 для лампы, E14 для датчика/панели.
    """
    if is_blank(raw):
        return None

    text = _cell(raw)

    if is_none_token(raw):
        if kind == "lamp":
            # Лампа не может отсутствовать явно: строка существует ради лампы.
            findings.append(Finding(
                "E03", "error",
                f"в колонке «{DEVICE_COLUMNS[kind]}» стоит {text!r} — лампа не может отсутствовать",
                row=row, space=space, group=group,
            ))
            return None
        return DeviceCell(kind=kind, raw=text, declared_absent=True)

    try:
        addr = parse_addr(text)
    except ValueError:
        code = "E03" if kind == "lamp" else "E14"
        findings.append(Finding(
            code, "error",
            f"в колонке «{DEVICE_COLUMNS[kind]}» значение {text!r} — не адрес X.Y.Z и не None",
            row=row, space=space, group=group,
        ))
        return None

    return DeviceCell(kind=kind, raw=text, addr=addr)


# ============================================================
# ВАЛИДАЦИЯ
# ============================================================

def _load_sheet(excel_path: Path, sheet_name: str) -> Tuple[Optional[pd.DataFrame], List[Finding]]:
    """Открыть книгу и вернуть нужный лист. E01/E02 — фатальны."""
    findings: List[Finding] = []

    with warnings.catch_warnings():
        # openpyxl ругается на выпадающие списки листа ПНР — нам это неинтересно.
        warnings.filterwarnings("ignore", message=".*Data Validation extension.*")
        return _load_sheet_inner(excel_path, sheet_name, findings)


def _load_sheet_inner(excel_path: Path, sheet_name: str,
                      findings: List[Finding]) -> Tuple[Optional[pd.DataFrame], List[Finding]]:
    book = pd.ExcelFile(excel_path)
    if sheet_name not in book.sheet_names:
        findings.append(Finding(
            "E01", "error",
            f"в книге нет листа {sheet_name!r}; есть: {', '.join(book.sheet_names)}",
        ))
        return None, findings

    # keep_default_na=False обязателен: иначе pandas считает строку "None"
    # пропущенным значением, а для нас "None" и пустая ячейка — разные вещи.
    df = book.parse(sheet_name=sheet_name, dtype=object, keep_default_na=False, na_values=[])
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    for col in missing:
        findings.append(Finding("E02", "error", f"нет обязательной колонки «{col}»"))

    if missing:
        return None, findings

    return df, findings


def validate(excel_path: Path, sheet_name: str = SHEET_NAME) -> Tuple[List[Finding], Dict]:
    """
    Проверить таблицу. Возвращает (находки, статистика).

    Ничего не пишет на диск — этим занимается main().
    """
    df, findings = _load_sheet(excel_path, sheet_name)
    if df is None:
        return findings, {}

    spaces: Dict[str, SpaceAcc] = {}
    groups: Dict[str, GroupAcc] = {}

    # адрес -> где встретился (для поиска дублей)
    lamp_addrs: Dict[str, List[int]] = defaultdict(list)
    sensor_addrs: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    panel_addrs: Dict[str, List[int]] = defaultdict(list)

    current_space: Optional[str] = None
    current_type: Optional[str] = None
    current_block: Optional[str] = None

    # Пустые строки в хвосте листа — это не проблема, а вот дырка в середине — да.
    # Поэтому сначала находим последнюю содержательную строку.
    def _row_is_blank(r: pd.Series) -> bool:
        return all(is_blank(r.get(c)) for c in REQUIRED_COLUMNS)

    last_meaningful = -1
    for idx, row in df.iterrows():
        if not _row_is_blank(row):
            last_meaningful = idx

    n_rows = 0

    for idx, row in df.iterrows():
        excel_row = int(idx) + FIRST_DATA_ROW

        if _row_is_blank(row):
            if idx < last_meaningful:
                findings.append(Finding("W06", "warning", "пустая строка внутри данных", row=excel_row))
            continue

        n_rows += 1

        # --- помещение, тип и блок: протягиваем вниз ---
        space_cell = _cell(row.get(COLUMNS.space))
        if space_cell:
            current_space = space_cell
            current_type = normalize_space_type(row.get(COLUMNS.space_type))
            current_block = _cell(row.get(COLUMNS.block)) or None

        space = current_space
        space_type = current_type

        if space is None:
            # Строка до первого помещения — данные без владельца.
            findings.append(Finding(
                "E09", "error", "строка не принадлежит ни одному помещению", row=excel_row,
            ))
            continue

        acc = spaces.setdefault(space, SpaceAcc(name=space))
        if space_cell:
            acc.space_type = space_type
            acc.block = current_block
        acc.rows.append(excel_row)

        # --- группа ---
        group_id = _cell(row.get(COLUMNS.group)) or None

        if group_id:
            gacc = groups.setdefault(group_id, GroupAcc(group_id=group_id))
            gacc.rows.append(excel_row)
            if space not in gacc.spaces:
                gacc.spaces.append(space)
            if group_id not in acc.groups:
                acc.groups.append(group_id)
        else:
            gacc = None

        # --- устройства ---
        floor_col = _to_int(row.get(COLUMNS.floor))
        bus_col = _to_int(row.get(COLUMNS.dali_bus))

        row_devices: List[DeviceCell] = []
        for kind in ("lamp", "sensor", "panel"):
            dev = _parse_device_cell(
                kind, row.get(DEVICE_COLUMNS[kind]), findings, excel_row, space, group_id,
            )
            if dev is not None:
                row_devices.append(dev)

        # Устройство в строке без группы — привязать его не к чему.
        if not group_id:
            present = [d for d in row_devices if d.addr is not None]
            for dev in present:
                findings.append(Finding(
                    "E12", "error",
                    f"{DEVICE_COLUMNS[dev.kind]} {dev.raw} в строке без группы",
                    row=excel_row, space=space,
                ))

        # Расхождение колонок с адресом — предупреждение: истина в адресе.
        # Достаточно одного сообщения на строку, иначе отчёт утонет.
        reported_w03 = reported_w04 = False

        for dev in row_devices:
            if dev.declared_absent:
                if dev.kind == "sensor":
                    acc.sensor_declared = True
                elif dev.kind == "panel":
                    acc.panel_declared = True
                continue

            assert dev.addr is not None
            addr_key = str(dev.addr)

            if floor_col is not None and dev.addr.floor != floor_col and not reported_w03:
                findings.append(Finding(
                    "W03", "warning",
                    f"адрес {addr_key} указывает на этаж {dev.addr.floor}, "
                    f"а в колонке «{COLUMNS.floor}» стоит {floor_col}",
                    row=excel_row, space=space, group=group_id,
                ))
                reported_w03 = True

            if bus_col is not None and dev.addr.bus != bus_col and not reported_w04:
                findings.append(Finding(
                    "W04", "warning",
                    f"адрес {addr_key} указывает на шину {dev.addr.bus}, "
                    f"а в колонке «{COLUMNS.dali_bus}» стоит {bus_col}",
                    row=excel_row, space=space, group=group_id,
                ))
                reported_w04 = True

            if dev.kind == "lamp":
                lamp_addrs[addr_key].append(excel_row)
                acc.lamp_count += 1
                if gacc:
                    gacc.lamp_count += 1
            elif dev.kind == "sensor":
                acc.sensor_declared = True
                acc.sensor_count += 1
                sensor_addrs[addr_key].append((excel_row, group_id or ""))
                if gacc:
                    gacc.sensor_count += 1
            elif dev.kind == "panel":
                acc.panel_declared = True
                panel_addrs[addr_key].append(excel_row)
                if gacc:
                    gacc.panel_count += 1

    # ========================================================
    # ПРОВЕРКИ ПОСЛЕ ПРОХОДА ПО СТРОКАМ
    # ========================================================

    # E04 / E05 / E06 — дубликаты адресов внутри своего типа устройства.
    for addr_key, rows in sorted(lamp_addrs.items()):
        if len(rows) > 1:
            findings.append(Finding(
                "E04", "error",
                f"лампа {addr_key} дублируется ({len(rows)} вхождения): строки {_rows_str(rows)}",
            ))

    for addr_key, hits in sorted(sensor_addrs.items()):
        if len(hits) > 1:
            rows = [r for r, _ in hits]
            findings.append(Finding(
                "E05", "error",
                f"датчик {addr_key} дублируется ({len(hits)} вхождения): строки {_rows_str(rows)}",
            ))

            # E07 добавляет контекст: дубликат ещё и разъехался по группам.
            distinct_groups = sorted({g for _, g in hits if g})
            if len(distinct_groups) > 1:
                findings.append(Finding(
                    "E07", "error",
                    f"датчик {addr_key} привязан к группам: {', '.join(distinct_groups)}",
                ))

    for addr_key, rows in sorted(panel_addrs.items()):
        if len(rows) > 1:
            findings.append(Finding(
                "E06", "error",
                f"панель {addr_key} дублируется ({len(rows)} вхождения): строки {_rows_str(rows)}",
            ))

    # E08 / W05 — по группам.
    for group_id, gacc in groups.items():
        space = gacc.spaces[0] if gacc.spaces else None

        if gacc.lamp_count == 0:
            findings.append(Finding(
                "E08", "error", f"группа {group_id} не содержит ни одной лампы",
                space=space, group=group_id,
            ))

        # E13 — один group_id в двух помещениях: entity_id light.<group_id> перестаёт быть уникальным.
        if len(gacc.spaces) > 1:
            findings.append(Finding(
                "E13", "error",
                f"группа {group_id} встречается в помещениях: {', '.join(gacc.spaces)}",
                group=group_id,
            ))

        space_type = spaces[space].space_type if space in spaces else None
        if (
            gacc.sensor_count == 0
            and space_type in ALLOWED_SPACE_TYPES
            and space_type != "zal"
        ):
            findings.append(Finding(
                "W05", "warning",
                f"в группе {group_id} нет датчиков (тип помещения — {space_type})",
                space=space, group=group_id,
            ))

    # E09 / E10 / E11 / W01 / W02 — по помещениям.
    for space, acc in spaces.items():
        if acc.lamp_count == 0:
            findings.append(Finding(
                "E09", "error", f"в помещении «{space}» нет ни одной лампы", space=space,
            ))

        if not acc.groups:
            findings.append(Finding(
                "E09", "error", f"в помещении «{space}» нет ни одной группы", space=space,
            ))

        if not acc.sensor_declared:
            findings.append(Finding(
                "E10", "error",
                f"в помещении «{space}» колонка «{COLUMNS.sensor}» пуста во всех строках: "
                f"нужен адрес или None",
                space=space,
            ))

        if not acc.panel_declared:
            findings.append(Finding(
                "E11", "error",
                f"в помещении «{space}» колонка «{COLUMNS.panel}» пуста во всех строках: "
                f"нужен адрес или None",
                space=space,
            ))

        if acc.space_type is None:
            findings.append(Finding(
                "W01", "warning",
                f"у помещения «{space}» не указан тип — карточка не будет сгенерирована",
                space=space,
            ))
        elif acc.space_type not in ALLOWED_SPACE_TYPES:
            findings.append(Finding(
                "W02", "warning",
                f"у помещения «{space}» неизвестный тип {acc.space_type!r}; "
                f"допустимые: {', '.join(sorted(ALLOWED_SPACE_TYPES))}",
                space=space,
            ))

    # ========================================================
    # ЕДИНИЦЫ ОБСЛУЖИВАНИЯ (колонка «Блок»)
    # ========================================================
    #
    # Единица = помещение, если блок пуст; иначе все помещения одного блока.
    # На каждую единицу клонируется свой набор скриптов: один экземпляр
    # скрипта в HA — это одна очередь, и при тысяче датчиков свет отстал бы
    # от человека.

    units: Dict[str, List[SpaceAcc]] = defaultdict(list)

    for space, acc in spaces.items():
        family = family_for_space_type(acc.space_type)

        if family is None:
            # class и zal не автоматизируются — блок им не нужен.
            if acc.block:
                findings.append(Finding(
                    "E16", "error",
                    f"у помещения «{space}» (тип {acc.space_type}) задан блок "
                    f"{acc.block!r}, но для этого типа скрипты не создаются",
                    space=space,
                ))
            continue

        if acc.sensor_count == 0:
            findings.append(Finding(
                "W08", "warning",
                f"у помещения «{space}» (тип {acc.space_type}) нет датчиков — "
                f"автоматизации по движению работать не будут",
                space=space,
            ))

        unit_id = acc.block or space
        units[unit_id].append(acc)

    for unit_id, members in units.items():
        families = {family_for_space_type(m.space_type) for m in members}

        # Блок из помещений разных семейств: им нужны разные blueprint'ы
        # и разные скрипты — одной единицей они быть не могут.
        if len(families) > 1:
            names = ", ".join(f"{m.name} ({m.space_type})" for m in members)
            findings.append(Finding(
                "E15", "error",
                f"блок {unit_id!r} смешивает разные семейства: {names}",
            ))

        total_sensors = sum(m.sensor_count for m in members)

        # Предел зашит в сами blueprint'ы: при большем числе датчиков
        # автоматизация в HA останавливается и пишет warning в лог.
        if total_sensors > MAX_SENSORS_PER_UNIT:
            names = ", ".join(m.name for m in members)
            findings.append(Finding(
                "W07", "warning",
                f"в единице {unit_id!r} {total_sensors} датчиков "
                f"(предел {MAX_SENSORS_PER_UNIT}): {names}. "
                f"Разделите на два блока в колонке «{COLUMNS.block}»",
            ))

    stats = {
        "rows": n_rows,
        "spaces": len(spaces),
        "groups": len(groups),
        "lamps": sum(len(v) for v in lamp_addrs.values()),
        "sensors": sum(len(v) for v in sensor_addrs.values()),
        "panels": sum(len(v) for v in panel_addrs.values()),
        "units": len(units),
    }

    return findings, stats


def _rows_str(rows: List[int]) -> str:
    """Строки Excel через запятую, с обрезкой длинного хвоста."""
    if len(rows) <= 6:
        return ", ".join(str(r) for r in rows)
    head = ", ".join(str(r) for r in rows[:6])
    return f"{head} и ещё {len(rows) - 6}"


# ============================================================
# ОТЧЁТ
# ============================================================

def _print_report(findings: List[Finding], stats: Dict, strict: bool) -> None:
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if stats:
        print("📊 Статистика таблицы:")
        print(f"  Строк данных:  {stats['rows']}")
        print(f"  Помещений:     {stats['spaces']}")
        print(f"  Групп:         {stats['groups']}")
        print(f"  Ламп:          {stats['lamps']}")
        print(f"  Датчиков:      {stats['sensors']}")
        print(f"  Панелей:       {stats['panels']}")
        print(f"  Единиц обсл.:  {stats['units']}")
        print()

    for title, bucket in (("❌ Ошибки", errors), ("⚠ Предупреждения", warnings)):
        if not bucket:
            continue

        print(f"{title}: {len(bucket)}")
        by_code: Dict[str, List[Finding]] = defaultdict(list)
        for f in bucket:
            by_code[f.code].append(f)

        for code in sorted(by_code):
            items = by_code[code]
            print(f"  [{code}] {RULE_TITLES.get(code, '')} — {len(items)} шт")
            for f in items[:CONSOLE_LIMIT]:
                where = f"строка {f.row}: " if f.row else ""
                print(f"      {where}{f.message}")
            if len(items) > CONSOLE_LIMIT:
                print(f"      … ещё {len(items) - CONSOLE_LIMIT} той же категории (все — в JSON-отчёте)")
        print()

    if not errors and not warnings:
        print("✅ Таблица прошла валидацию без замечаний")
    elif not errors:
        if strict:
            print("❌ Предупреждения считаются ошибками (--strict)")
        else:
            print("✅ Блокирующих ошибок нет, генерацию можно запускать")


def _write_report(path: Path, excel_path: Path, sheet_name: str,
                  findings: List[Finding], stats: Dict, strict: bool, ok: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": __version__,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_file": str(excel_path),
        "sheet_name": sheet_name,
        "strict": strict,
        "ok": ok,
        "stats": stats,
        "errors": [f.to_dict() for f in findings if f.severity == "error"],
        "warnings": [f.to_dict() for f in findings if f.severity == "warning"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проверить входную таблицу до запуска генерации.",
    )
    parser.add_argument("--excel", default=str(DEFAULT_EXCEL_PATH), help="Путь к Excel-файлу")
    parser.add_argument("--sheet", default=SHEET_NAME, help="Имя листа")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH), help="Путь к JSON-отчёту")
    parser.add_argument("--strict", action="store_true", help="Считать предупреждения ошибками")
    args = parser.parse_args()

    excel_path = Path(args.excel)
    report_path = Path(args.report)

    print("\n=== Validate Excel ===")
    print("Excel  :", excel_path)
    print("Sheet  :", args.sheet)
    print("Report :", report_path)
    print("Strict :", args.strict)
    print()

    if not excel_path.exists():
        print(f"❌ Файл не найден: {excel_path}")
        return 2

    findings, stats = validate(excel_path, args.sheet)

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    ok = not errors and not (args.strict and warnings)

    _print_report(findings, stats, args.strict)
    _write_report(report_path, excel_path, args.sheet, findings, stats, args.strict, ok)

    print(f"\nОтчёт: {report_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
