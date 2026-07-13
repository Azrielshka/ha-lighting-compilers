# -*- coding: utf-8 -*-
"""
Общая обвязка тестов.

Скрипты проекта — CLI-first: они лежат в scripts/ и импортируют модули
как `from scripts._lib.canon import ...`, а сами себя видят через `_lib.bootstrap`.
Чтобы pytest мог их импортировать, кладём в sys.path и корень, и scripts/.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pytest
from openpyxl import Workbook

PROJECT_ROOT = Path(__file__).resolve().parent.parent

for _p in (PROJECT_ROOT, PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


SHEET_NAME = "Проектная БД"

HEADERS: List[str] = [
    "Этаж",
    "Название помещения",
    "Тип помещения",
    "Блок",
    "Шина DALI",
    "Группа",
    "Лампа",
    "Addr L",
    "Датчик",
    "Addr MS",
    "Панель",
    "Addr KP",
]


def make_book(
    path: Path,
    rows: Iterable[Optional[Dict[str, object]]],
    headers: Optional[List[str]] = None,
    sheet_name: str = SHEET_NAME,
) -> Path:
    """
    Собрать .xlsx из списка строк-словарей.

    `None` вместо словаря даёт пустую строку — так тестируем W06.
    Ключи, которых нет в headers, игнорируются.
    """
    headers = headers or HEADERS

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)

    for row in rows:
        if row is None:
            ws.append([None] * len(headers))
            continue
        ws.append([row.get(h) for h in headers])

    wb.save(path)
    return path


def base_rows() -> List[Dict[str, object]]:
    """
    Минимальная валидная таблица: одно помещение, одна группа,
    две лампы, датчик, панели нет (явное None).
    """
    return [
        {
            "Этаж": 1, "Название помещения": "101_Тамбур", "Тип помещения": "Special",
            "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.1",
            "Датчик": "1.1.1", "Панель": "None",
        },
        {"Этаж": 1, "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.2"},
    ]


@pytest.fixture
def valid_xlsx(tmp_path: Path) -> Path:
    return make_book(tmp_path / "valid.xlsx", base_rows())


@pytest.fixture
def object_example() -> Path:
    """Реальная фикстура формата v2."""
    return PROJECT_ROOT / "data" / "object_example.xlsx"
