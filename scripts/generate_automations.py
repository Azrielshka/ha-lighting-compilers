# -*- coding: utf-8 -*-
"""
generate_automations.py
Генератор автоматизаций из blueprint'ов.

Вход:  data/normalized/units.parquet
Выход: data/automations/automations.yaml
       data/blueprints/*.yaml  (копии шаблонов, для деплоя)

По две автоматизации на единицу обслуживания: ON (движение) и OFF (пусто).
Blueprint — диспетчер: он ловит событие, спрашивает конфигурацию зоны у
Zone Manager и передаёт её в клонированный скрипт. Логики управления светом
в нём нет.

Формат файла: ГОЛЫЙ СПИСОК
--------------------------
Файл кладётся в includes/automations/, которая подключена так:

    automation manual: !include_dir_merge_list includes/automations/

Директива merge_list ждёт в каждом файле СПИСОК, а домен `automation:` в
Home Assistant списком и является. Обёртки вида `zm_automations:` /
`automation:` здесь быть НЕ должно — с ней HA файл не подхватит.

(Для сравнения: scripts.yaml идёт в includes/scripts/ с merge_named — там,
наоборот, нужен словарь `object_id -> скрипт`, и он там есть.)

Почему не automations.yaml в корне: туда Home Assistant пишет автоматизации,
созданные через UI. Перезаписав его, мы стёрли бы ручную работу наладчика.

⚠ Известный долг
----------------
input_number.vacant_delay пайплайн НЕ создаёт (см. canon.VACANT_DELAY_ENTITY).
Без него OFF-автоматизации соберутся и загрузятся, но триггер не сработает:
`for: seconds: {{ states(...) }}` вернёт unknown — и свет не будет гаснуть.

Zone Manager JSON тоже собирается вручную. Без него автоматизация отработает,
получит found: false и запишет warning в лог. Свет не включится.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

from scripts._lib.canon import (
    BLUEPRINT_DIR,
    BLUEPRINT_INPUTS_BY_FAMILY,
    BLUEPRINTS_BY_FAMILY,
    VACANT_DELAY_ENTITY,
    automation_id,
    blueprint_path,
    script_entity,
)
from scripts._lib.filters import (
    Filters,
    add_filter_args,
    filters_from_args,
    print_filter_report,
)
from scripts._lib.normalized import NormalizedLayerError, load_dataset

__version__ = "1.0.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
DEFAULT_TEMPLATES_DIR = PROJECT_ROOT / "templates" / "blueprints"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "automations" / "automations.yaml"
DEFAULT_BLUEPRINTS_OUT = PROJECT_ROOT / "data" / "blueprints"

ROLE_TITLES = {"on": "ON", "off": "OFF"}


class BlueprintError(RuntimeError):
    """Файл blueprint'а не найден."""


def _spaces_label(unit) -> str:
    """Человеческое имя единицы для alias: имена помещений через запятую."""
    return ", ".join(unit["spaces"])


def build_automation(unit, role: str, directory: str) -> List[str]:
    """
    Собрать одну автоматизацию — экземпляр blueprint'а.

    Состав входов зависит от семейства: у special OFF скрипт один
    (off_script), у default и hall — два (off_script_1 + off_script_2).
    """
    unit_id = str(unit["unit_id"])
    family = unit["family"]

    inputs = BLUEPRINT_INPUTS_BY_FAMILY[family][role]
    bp_file = BLUEPRINTS_BY_FAMILY[family][role]

    label = _spaces_label(unit)
    sensors = list(unit["sensors_ms"])

    # Элемент списка верхнего уровня: файл целиком — голый список,
    # его подхватывает !include_dir_merge_list.
    lines: List[str] = [
        f"- id: {automation_id(unit_id, role)}",
        f'  alias: "{label} — {ROLE_TITLES[role]}"',
        "  use_blueprint:",
        f"    path: {blueprint_path(bp_file, directory)}",
        "    input:",
        f'      automation_label: "{label} {ROLE_TITLES[role]}"',
    ]

    for input_name, source in inputs.items():
        if source == "sensors":
            lines.append(f"      {input_name}:")
            for sensor in sensors:
                lines.append(f"        - {sensor}")
        elif source == "vacant_delay":
            lines.append(f"      {input_name}: {VACANT_DELAY_ENTITY}")
        else:
            # source — роль скрипта: on / off / near_off / hall_near
            lines.append(f"      {input_name}: {script_entity(unit_id, source)}")

    lines.append("")
    return lines


def build_yaml(units_df: pd.DataFrame, filters: Filters, directory: str) -> str:
    """Собрать пакет автоматизаций из единиц обслуживания."""
    from generate_scripts import _apply_unit_filters

    total = len(units_df)
    filtered, excluded = _apply_unit_filters(units_df, filters)

    print_filter_report(
        "Автоматизации (экземпляры blueprint'ов)",
        filters,
        total=total,
        kept=len(filtered),
        excluded=excluded,
    )

    if filtered.empty:
        print("\n⚠ После фильтров не осталось единиц обслуживания.")
        return "# Нет единиц обслуживания — автоматизации не сгенерированы\n"

    lines: List[str] = [
        "# Автоматизации управления освещением — экземпляры blueprint'ов.",
        "#",
        "# По две на единицу обслуживания: ON (движение) и OFF (пусто).",
        "# Blueprint — диспетчер: ловит событие, берёт конфигурацию зоны у",
        "# Zone Manager и передаёт её в клонированный скрипт.",
        "#",
        "# Файл — ГОЛЫЙ СПИСОК, без обёртки: он кладётся в includes/automations/,",
        "# подключённую через !include_dir_merge_list. Домен automation: в Home",
        "# Assistant списком и является.",
        "#",
        "# Не automations.yaml в корне: туда HA пишет автоматизации, созданные",
        "# через UI, и перезапись стёрла бы ручную работу наладчика.",
        "#",
        f"# ⚠ {VACANT_DELAY_ENTITY} пайплайн не создаёт — заведите его на объекте,",
        "#   иначе OFF-триггер не сработает и свет не будет гаснуть.",
        "#",
        "# Файл собран автоматически — правки будут затёрты.",
        "",
    ]

    by_family: Dict[str, int] = {}
    no_sensors: List[str] = []

    for _, unit in filtered.iterrows():
        if not len(unit["sensors_ms"]):
            # Автоматизация без датчиков не имеет триггеров — она мертва.
            no_sensors.append(str(unit["unit_id"]))
            continue

        lines.append(f"# ── {unit['unit_id']}  ({unit['family']}, "
                     f"{unit['sensor_count']} датч.)")

        for role in ("on", "off"):
            lines.extend(build_automation(unit, role, directory))

        by_family[unit["family"]] = by_family.get(unit["family"], 0) + 1

    made = sum(by_family.values())

    print(f"  Единиц обслуживания:  {len(filtered)}")
    for family, count in sorted(by_family.items()):
        print(f"    {family:8} {count:3} ед. × 2 (ON + OFF)")
    print(f"  Автоматизаций:        {made * 2}")

    if no_sensors:
        print(f"\n  ⚠ Без датчиков — автоматизации не созданы: {', '.join(no_sensors)}")

    if made == 0:
        return "# Ни одна единица обслуживания не имеет датчиков — автоматизации не созданы\n"

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


def copy_blueprints(templates_dir: Path, output_dir: Path) -> List[str]:
    """
    Скопировать файлы blueprint'ов для деплоя — как есть, без изменений.

    Автоматизации ссылаются на них по path; если файлов не будет на HA,
    автоматизации не загрузятся вовсе.
    """
    needed = sorted({
        f for family in BLUEPRINTS_BY_FAMILY.values() for f in family.values()
    })

    missing = [f for f in needed if not (templates_dir / f).exists()]
    if missing:
        raise BlueprintError(
            f"не найдены blueprint'ы в {templates_dir}: {', '.join(missing)}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in needed:
        shutil.copy2(templates_dir / filename, output_dir / filename)

    return needed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сгенерировать автоматизации (экземпляры blueprint'ов).",
    )
    parser.add_argument("--normalized", default=str(DEFAULT_NORMALIZED_DIR),
                        help="Папка с parquet")
    parser.add_argument("--templates", default=str(DEFAULT_TEMPLATES_DIR),
                        help="Папка с blueprint'ами")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH),
                        help="Куда записать YAML автоматизаций")
    parser.add_argument("--blueprints-out", default=str(DEFAULT_BLUEPRINTS_OUT),
                        help="Куда положить копии blueprint'ов для деплоя")
    parser.add_argument("--blueprint-dir", default=BLUEPRINT_DIR,
                        help="Подпапка в config/blueprints/automation/ на HA")
    add_filter_args(parser, with_include_floors=True)
    args = parser.parse_args()

    output_path = Path(args.out)
    templates_dir = Path(args.templates)
    blueprints_out = Path(args.blueprints_out)

    print("\n=== Generate Automations ===")
    print("Источник   :", args.normalized)
    print("Blueprint'ы:", templates_dir)
    print("Выход      :", output_path)
    print()

    try:
        units_df = load_dataset(Path(args.normalized), "units")
    except NormalizedLayerError as exc:
        print(f"❌ {exc}")
        return 2

    try:
        copied = copy_blueprints(templates_dir, blueprints_out)
    except BlueprintError as exc:
        print(f"❌ {exc}")
        return 2

    yaml_text = build_yaml(units_df, filters_from_args(args), args.blueprint_dir)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")

    print(f"\nOK: {output_path}")
    print(f"    {blueprints_out} — {len(copied)} blueprint'ов для деплоя")
    print(f"\n⚠ Заведите {VACANT_DELAY_ENTITY} на объекте:")
    print("   без него OFF-триггер не сработает и свет не будет гаснуть.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
