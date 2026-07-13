# -*- coding: utf-8 -*-
"""
filters.py
Фильтры генераторов: единая логика и единый набор CLI-аргументов.

Зачем: логика фильтров была скопирована в трёх генераторах почти дословно,
а значения задавались константами в исходнике — чтобы исключить этаж,
наладчику приходилось править код. Теперь фильтры передаются флагами.

Фильтры применяются к датафрейму, у которого есть колонки
`room_slug`, `space` и `floor` — то есть к groups или spaces.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class Filters:
    """Набор фильтров генератора."""

    # Белый список помещений (room_slug; можно и space — сверяем оба).
    spaces: List[str] = field(default_factory=list)

    # Белый список этажей. Пустой = все этажи.
    include_floors: List[int] = field(default_factory=list)

    # Чёрный список этажей.
    exclude_floors: List[int] = field(default_factory=list)

    # Исключить помещения, в имени которых есть подстрока (без учёта регистра).
    exclude_space_contains: List[str] = field(default_factory=list)

    @property
    def any_set(self) -> bool:
        return bool(
            self.spaces
            or self.include_floors
            or self.exclude_floors
            or self.exclude_space_contains
        )

    def describe(self) -> str:
        """Одна строка для лога: что именно фильтруем."""
        if not self.any_set:
            return "нет (генерируем всё)"

        parts = []
        if self.spaces:
            parts.append(f"только помещения: {', '.join(self.spaces)}")
        if self.include_floors:
            parts.append(f"только этажи: {', '.join(map(str, self.include_floors))}")
        if self.exclude_floors:
            parts.append(f"кроме этажей: {', '.join(map(str, self.exclude_floors))}")
        if self.exclude_space_contains:
            parts.append(f"кроме содержащих: {', '.join(self.exclude_space_contains)}")
        return "; ".join(parts)


def add_filter_args(parser: argparse.ArgumentParser, with_include_floors: bool = False) -> None:
    """
    Добавить флаги фильтров в CLI генератора.

    with_include_floors — только для generate_floor_groups: у остальных
    белый список этажей смысла не имеет (они и так фильтруются помещениями).
    """
    group = parser.add_argument_group("фильтры")

    group.add_argument(
        "--spaces", nargs="+", metavar="SLUG", default=[],
        help="Только эти помещения (room_slug или имя из таблицы)",
    )
    if with_include_floors:
        group.add_argument(
            "--floors", nargs="+", type=int, metavar="N", default=[],
            help="Только эти этажи",
        )
    group.add_argument(
        "--exclude-floors", nargs="+", type=int, metavar="N", default=[],
        help="Исключить эти этажи",
    )
    group.add_argument(
        "--exclude-space-contains", nargs="+", metavar="ПОДСТРОКА", default=[],
        help="Исключить помещения, в имени которых есть подстрока",
    )


def filters_from_args(args: argparse.Namespace) -> Filters:
    """Собрать Filters из разобранных аргументов CLI."""
    return Filters(
        spaces=list(args.spaces),
        include_floors=list(getattr(args, "floors", []) or []),
        exclude_floors=list(args.exclude_floors),
        exclude_space_contains=list(args.exclude_space_contains),
    )


def apply_filters(df: pd.DataFrame, filters: Filters) -> Tuple[pd.DataFrame, List[str]]:
    """
    Применить фильтры.

    Возвращает (отфильтрованный df, список исключённых помещений).
    Список нужен для отчёта: наладчик должен видеть, что именно выпало,
    а не гадать, почему в YAML меньше помещений, чем в таблице.
    """
    if df.empty:
        return df, []

    before = list(dict.fromkeys(df["space"].tolist()))
    out = df

    # Белый список помещений: сверяем и room_slug, и человекочитаемое имя —
    # наладчику неочевидно, что в фильтр надо писать транслит.
    if filters.spaces:
        wanted = {str(s).strip() for s in filters.spaces}
        out = out[out["room_slug"].isin(wanted) | out["space"].isin(wanted)]

    if filters.include_floors:
        keep = {int(f) for f in filters.include_floors}
        out = out[out["floor"].isin(keep)]

    if filters.exclude_floors:
        drop = {int(f) for f in filters.exclude_floors}
        out = out[~out["floor"].isin(drop)]

    if filters.exclude_space_contains:
        subs = [s.lower() for s in filters.exclude_space_contains]

        def allowed(row: pd.Series) -> bool:
            # Ищем и в транслите, и в исходном имени: наладчик пишет "коридор",
            # а в room_slug лежит "korridor" — и наоборот.
            haystack = f"{row['room_slug']} {row['space']}".lower()
            return not any(sub in haystack for sub in subs)

        out = out[out.apply(allowed, axis=1)]

    after = set(out["space"].tolist())
    excluded = [s for s in before if s not in after]

    return out.copy(), excluded


def print_filter_report(name: str, filters: Filters, total: int,
                        kept: int, excluded: List[str]) -> None:
    """Единый отчёт по фильтрам для всех генераторов."""
    print(f"📊 {name}")
    print(f"  Фильтры:              {filters.describe()}")
    print(f"  Помещений в данных:   {total}")

    if excluded:
        print(f"  Исключено фильтрами:  {len(excluded)} — {', '.join(excluded)}")
    else:
        print(f"  Исключено фильтрами:  нет")
