# -*- coding: utf-8 -*-
"""
normalized.py
Чтение нормализованного слоя генераторами.

Зачем отдельный модуль: генераторы не должны знать, как называются файлы и
какие в них колонки. Они просят датасет — получают датафрейм со сверенной
схемой. Если на диске лежит parquet от старой версии normalize, мы узнаем
об этом сразу и внятно, а не через странное поведение генератора.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow.parquet as pq

from scripts._lib.schemas import DATASET_NAMES, SCHEMAS


class NormalizedLayerError(RuntimeError):
    """Нормализованный слой отсутствует или не соответствует схеме."""


@dataclass(frozen=True)
class NormalizedLayer:
    """Три датасета нормализованного слоя."""
    devices: pd.DataFrame
    groups: pd.DataFrame
    spaces: pd.DataFrame
    path: Path


def _check_schema(path: Path, name: str) -> None:
    """Сверить схему файла с объявленной."""
    actual = pq.read_schema(path)
    expected = SCHEMAS[name]

    missing = [f for f in expected.names if f not in actual.names]
    if missing:
        raise NormalizedLayerError(
            f"{path.name}: нет колонок {', '.join(missing)}. "
            f"Похоже, файл собран старой версией normalize_excel.py — пересоберите."
        )

    wrong = [
        f"{f}: ожидали {expected.field(f).type}, получили {actual.field(f).type}"
        for f in expected.names
        if actual.field(f).type != expected.field(f).type
    ]
    if wrong:
        raise NormalizedLayerError(
            f"{path.name}: типы колонок не совпадают со схемой:\n  "
            + "\n  ".join(wrong)
            + "\nПересоберите слой: normalize_excel.py"
        )


def load_dataset(output_dir: Path, name: str, check: bool = True) -> pd.DataFrame:
    """Прочитать один датасет нормализованного слоя."""
    if name not in SCHEMAS:
        raise ValueError(f"неизвестный датасет: {name!r}; есть: {', '.join(DATASET_NAMES)}")

    path = Path(output_dir) / f"{name}.parquet"

    if not path.exists():
        raise NormalizedLayerError(
            f"не найден {path}\nСначала запустите normalize_excel.py"
        )

    if check:
        _check_schema(path, name)

    return pd.read_parquet(path)


def load_normalized(output_dir: Path, check: bool = True) -> NormalizedLayer:
    """Прочитать весь нормализованный слой."""
    path = Path(output_dir)
    return NormalizedLayer(
        devices=load_dataset(path, "devices", check),
        groups=load_dataset(path, "groups", check),
        spaces=load_dataset(path, "spaces", check),
        path=path,
    )
