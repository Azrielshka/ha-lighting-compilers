# -*- coding: utf-8 -*-
"""
excel_schema.py
Единые имена листа и колонок входной таблицы.

Зачем:
- входная таблица со временем меняется
- все скрипты должны знать о ней из одного места

Схема v2 покрывает "Проектную БД" (см. docs/internal/data_model.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


# Лист читается по имени, а не по порядку: в книге есть ещё ПНР,
# "ИНФ контроллеры", "Глоссарий" и "Группы соседей" — их пайплайн не трогает.
SHEET_NAME: str = "Проектная БД"


@dataclass(frozen=True)
class ExcelColumnsV2:
    """Колонки листа "Проектная БД"."""

    floor: str = "Этаж"                      # заполнена в каждой строке
    space: str = "Название помещения"        # только первая строка помещения
    space_type: str = "Тип помещения"        # только первая строка помещения

    # Единица обслуживания: помещения с одинаковым «Блоком» обслуживаются
    # одним набором скриптов. Пусто — помещение само по себе.
    # Заполняется только на первой строке помещения, как и тип.
    block: str = "Блок"

    dali_bus: str = "Шина DALI"              # справочно, истина — в адресе
    group: str = "Группа"                    # заполнена в каждой строке
    lamp: str = "Лампа"
    sensor: str = "Датчик"
    panel: str = "Панель"


COLUMNS = ExcelColumnsV2()


# Без этих колонок читать таблицу бессмысленно.
REQUIRED_COLUMNS: Tuple[str, ...] = (
    COLUMNS.floor,
    COLUMNS.space,
    COLUMNS.space_type,
    COLUMNS.block,
    COLUMNS.dali_bus,
    COLUMNS.group,
    COLUMNS.lamp,
    COLUMNS.sensor,
    COLUMNS.panel,
)

# Колонки, которые есть в таблице, но пайплайном не читаются.
# Заполняются наладчиком вручную и на генерацию не влияют.
IGNORED_COLUMNS: Tuple[str, ...] = ("Addr L", "Addr MS", "Addr KP")

# Колонки, которые протягиваются вниз внутри помещения.
# "Группа" сюда НЕ входит: в v2 она заполнена в каждой строке.
FFILL_COLUMNS: Tuple[str, ...] = (COLUMNS.space, COLUMNS.space_type, COLUMNS.block)

# Колонки устройств: kind -> колонка. Порядок задаёт порядок в отчётах.
DEVICE_COLUMNS = {
    "lamp": COLUMNS.lamp,
    "sensor": COLUMNS.sensor,
    "panel": COLUMNS.panel,
}


# Схема v1 (таблица data/example.xlsx с колонками «(авто)» и card_type)
# удалена вместе с переездом генераторов. Сам файл остаётся в репозитории
# как исторический артефакт, но пайплайн его не читает — валидатор скажет
# «нет листа "Проектная БД"», и это ожидаемое поведение.
