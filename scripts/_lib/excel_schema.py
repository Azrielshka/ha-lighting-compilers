# -*- coding: utf-8 -*-
"""
excel_schema.py
Единые имена колонок Excel и выбор приоритетных "источников правды".

Зачем:
- входная таблица со временем меняется (имена/наличие колонок)
- мы хотим, чтобы скрипты работали устойчиво: сначала ищем колонку по имени, затем fallback.

Эта схема покрывает текущую "Тестовую таблицу.xlsx".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ExcelColumns:
    # "Сырые" колонки (как заполняет человек)
    floor_raw: str = "Этаж"
    space_raw: str = "Помещение"
    dali_bus_raw: str = "Шина DALI"
    group_raw: str = "Группа"
    lamp_raw: str = "Лампа"
    sensor_raw: str = "Датчик"
    button_raw: str = "Кнопка"
    card_type: str = "card_type"

    # "Авто" колонки (вычисляемые/протянутые)
    floor_auto: str = "Этаж (авто)"
    space_auto: str = "Помещение (авто)"
    dali_bus_auto: str = "Шина DALI (авто)"
    group_auto: str = "Группа (авто)"
    sensor_auto: str = "Датчик (авто)"
    button_auto: str = "Кнопка (авто)"


COLUMNS = ExcelColumns()
