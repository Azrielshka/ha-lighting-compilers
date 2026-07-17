# -*- coding: utf-8 -*-
"""
generate_scripts.py
Клонирование шаблонных скриптов управления освещением.

Вход:  data/normalized/units.parquet
       templates/scripts/*.yaml
Выход: data/scripts/scripts.yaml

Зачем клонировать
-----------------
Один экземпляр скрипта в Home Assistant — это ОДНА ОЧЕРЕДЬ. При тысяче датчиков
вызовы копятся, и свет отстаёт от человека; mode: queued не спасает, а
усугубляет. Поэтому у каждой единицы обслуживания свой набор скриптов —
они друг друга не ждут.

Тела скриптов одинаковы на всех объектах и не содержат имён: конфигурацию
(группы света, соседей) они получают параметрами от blueprint'а, который
берёт её из Zone Manager. Отличается только имя — корневой ключ YAML,
из которого Home Assistant делает entity_id.

    shablon_script_on:   ->  103_vestibiul_on:     ->  script.103_vestibiul_on

Состав набора зависит от семейства помещения (canon.SCRIPTS_BY_FAMILY):
    default (коридор, рекреация)  ->  on, off, near_off
    hall                          ->  on, off, hall_near
    special                       ->  on, off
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from scripts._lib.canon import SCRIPTS_BY_FAMILY, script_object_id
from scripts._lib.filters import (
    Filters,
    add_filter_args,
    apply_filters,
    filters_from_args,
    print_filter_report,
)
from scripts._lib.normalized import NormalizedLayerError, load_dataset

__version__ = "1.0.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
DEFAULT_TEMPLATES_DIR = PROJECT_ROOT / "templates" / "scripts"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "scripts" / "scripts.yaml"

# Человеческие названия ролей — идут в alias, который HA показывает в UI.
# Без этого все клоны назывались бы «Шаблон скрипта на включение».
ROLE_TITLES: Dict[str, str] = {
    "on": "включение",
    "off": "выключение своей зоны",
    "near_off": "выключение соседей",
    "hall_near": "выключение соседей (холл)",
}

# Корневой ключ шаблона: строка вида `shablon_script_on:` с нулевым отступом.
ROOT_KEY_RE = re.compile(r"^([a-z_][a-z0-9_]*):\s*$")

# alias внутри тела скрипта (отступ 2 пробела).
ALIAS_RE = re.compile(r"^(\s+alias:).*$")


class TemplateError(RuntimeError):
    """Шаблон не найден или устроен не так, как ожидается."""


def load_template(templates_dir: Path, filename: str) -> Tuple[str, List[str]]:
    """
    Прочитать шаблон и вернуть (корневой ключ, строки тела).

    Тело начинается с корневого ключа: комментарии-шапку отбрасываем,
    в клонах она была бы враньём («Шаблон общего скрипта...»).
    """
    path = templates_dir / filename

    if not path.exists():
        raise TemplateError(f"шаблон не найден: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()

    for i, line in enumerate(lines):
        match = ROOT_KEY_RE.match(line)
        if match:
            return match.group(1), lines[i:]

    raise TemplateError(
        f"в шаблоне {filename} не найден корневой ключ вида 'shablon_script_on:'"
    )


def clone_script(body: List[str], unit_id: str, role: str) -> List[str]:
    """
    Подставить имя единицы в тело шаблона.

    Меняем ровно две вещи:
      - корневой ключ  -> из него HA делает entity_id
      - alias          -> иначе в UI будет двести одинаковых «Шаблон скрипта»

    Больше в теле имён нет: конфигурацию скрипт получает параметрами.
    """
    object_id = script_object_id(unit_id, role)
    title = ROLE_TITLES.get(role, role)

    out: List[str] = [f"{object_id}:"]
    alias_done = False

    for line in body[1:]:
        if not alias_done:
            match = ALIAS_RE.match(line)
            if match:
                out.append(f'{match.group(1)} "{unit_id} — {title}"')
                alias_done = True
                continue
        out.append(line)

    return out


def build_yaml(units_df: pd.DataFrame, templates_dir: Path, filters: Filters) -> str:
    """Собрать scripts.yaml из шаблонов и единиц обслуживания."""
    total = len(units_df)

    # units уже отфильтрованы по семейству (class и zal не автоматизируются),
    # но фильтры пользователя применяем: они работают по помещениям и этажам.
    filtered, excluded = _apply_unit_filters(units_df, filters)

    print_filter_report(
        "Скрипты управления освещением",
        filters,
        total=total,
        kept=len(filtered),
        excluded=excluded,
    )

    if filtered.empty:
        print("\n⚠ После фильтров не осталось единиц обслуживания.")
        return "# Нет единиц обслуживания — скрипты не сгенерированы\n"

    lines: List[str] = [
        "# Скрипты управления освещением по датчикам движения.",
        "#",
        "# Клоны шаблонов из templates/scripts/. Тела одинаковы и не содержат",
        "# имён: конфигурацию (группы света, соседей) скрипт получает параметрами",
        "# от blueprint'а, который берёт её из Zone Manager.",
        "#",
        "# Клонируем потому, что один экземпляр скрипта в HA — это одна очередь:",
        "# при тысяче датчиков вызовы копились бы и свет отставал от человека.",
        "#",
        "# Единица обслуживания = помещение (если «Блок» пуст) либо все помещения",
        "# одного «Блока». Файл собран автоматически — правки будут затёрты.",
        "",
    ]

    # Шаблон читаем один раз на файл, а не на каждый клон.
    cache: Dict[str, Tuple[str, List[str]]] = {}
    by_family: Dict[str, int] = {}

    for _, unit in filtered.iterrows():
        family = unit["family"]
        roles = SCRIPTS_BY_FAMILY.get(family)

        if not roles:
            # Такого быть не должно: units собирает только автоматизируемые.
            print(f"  ⚠ у единицы {unit['unit_id']} неизвестное семейство {family!r} — пропущена")
            continue

        spaces = ", ".join(unit["spaces"])
        lines.append(f"# ── {unit['unit_id']}  ({family}, {unit['sensor_count']} датч.)  {spaces}")

        for role, filename in roles.items():
            if filename not in cache:
                cache[filename] = load_template(templates_dir, filename)

            _, body = cache[filename]
            lines.extend(clone_script(body, str(unit["unit_id"]), role))
            lines.append("")

        by_family[family] = by_family.get(family, 0) + 1

    script_count = sum(
        len(SCRIPTS_BY_FAMILY.get(u["family"], {})) for _, u in filtered.iterrows()
    )

    print(f"  Единиц обслуживания:  {len(filtered)}")
    for family, count in sorted(by_family.items()):
        roles = ", ".join(SCRIPTS_BY_FAMILY[family])
        print(f"    {family:8} {count:3} ед. × [{roles}]")
    print(f"  Скриптов в YAML:      {script_count}")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


def _apply_unit_filters(units_df: pd.DataFrame, filters: Filters):
    """
    Фильтры работают по помещениям, а единица может содержать несколько.
    Оставляем единицу, если прошло хотя бы одно её помещение: разорвать
    блок фильтром нельзя — скрипты клонируются на единицу целиком.
    """
    if not filters.any_set:
        return units_df, []

    # Разворачиваем в плоский вид «единица × помещение», фильтруем, собираем обратно.
    flat = units_df.explode("spaces").rename(columns={"spaces": "space"})
    flat["room_slug"] = flat["space"]
    flat["floor"] = flat["floors"].apply(lambda f: list(f)[0] if len(f) else pd.NA)

    kept, _ = apply_filters(flat, filters)
    kept_units = set(kept["unit_id"])

    excluded = [
        u["unit_id"] for _, u in units_df.iterrows() if u["unit_id"] not in kept_units
    ]

    return units_df[units_df["unit_id"].isin(kept_units)].copy(), excluded


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Клонировать шаблонные скрипты по единицам обслуживания.",
    )
    parser.add_argument("--normalized", default=str(DEFAULT_NORMALIZED_DIR),
                        help="Папка с parquet")
    parser.add_argument("--templates", default=str(DEFAULT_TEMPLATES_DIR),
                        help="Папка с шаблонами скриптов")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH),
                        help="Куда записать YAML")
    add_filter_args(parser, with_include_floors=True)
    args = parser.parse_args()

    output_path = Path(args.out)
    templates_dir = Path(args.templates)

    print("\n=== Generate Scripts ===")
    print("Источник :", args.normalized)
    print("Шаблоны  :", templates_dir)
    print("Выход    :", output_path)
    print()

    try:
        units_df = load_dataset(Path(args.normalized), "units")
    except NormalizedLayerError as exc:
        print(f"❌ {exc}")
        return 2

    try:
        yaml_text = build_yaml(units_df, templates_dir, filters_from_args(args))
    except TemplateError as exc:
        print(f"❌ {exc}")
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")

    print(f"\nOK: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
