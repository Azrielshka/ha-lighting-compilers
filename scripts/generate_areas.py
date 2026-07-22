# -*- coding: utf-8 -*-
"""
generate_areas.py
Генератор пространств (Areas) и этажей (Floors) для Home Assistant.

Вход:  data/normalized/spaces.parquet
Выход: data/areas/areas.yaml

ВАЖНО: шаг полностью офлайновый. К Home Assistant не подключается и ничего
в него не пишет — только готовит файл. Отправка на объект — отдельный шаг
деплоя, по явному действию наладчика.

Areas и Floors — это не YAML-конфигурация HA, а записи в реестрах, которые
создаются по WebSocket API. Поэтому наш файл — не конфиг, а ЗАДАНИЕ на
создание: что создать, с какими именами. Наладчик может открыть его глазами
и поправить перед деплоем.

Имя пространства берём прямо из колонки «Название помещения»: проектировщик
уже написал его по-человечески. Транслит (room_slug) идёт в алиасы, чтобы
в HA искалось и по нему.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

from scripts._lib.canon import (
    BA_FLOOR_AREA_LABEL,
    area_aliases,
    area_name,
    ba_type_label,
    floor_area_id,
    floor_area_name,
    floor_icon,
    floor_light_entity,
    floor_name,
    general_light_entity,
    normalize_space_type,
)
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
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "areas" / "areas.yaml"


def build_payload(spaces_df: pd.DataFrame, filters: Filters) -> Dict:
    """
    Собрать задание на создание Areas и Floors.

    Возвращает структуру, которую шаг деплоя отправит в Home Assistant:

        {
          "floors": [{"level": 1, "name": "1 этаж", "icon": "mdi:home-floor-1"}],
          "areas":  [{"name": "101_Тамбур", "aliases": ["101_tambur"], "floor": 1,
                      "light": "light.101_tambur_obshchii",
                      "labels": ["ba_type_special"]}]
        }

    Привязка area -> floor хранится уровнем этажа, а не floor_id: id выдаёт
    сам Home Assistant при создании, и знать его заранее мы не можем.

    Поля light и labels — для Оркестратора здания (см. канон, раздел меток).
    light назначается сущности при деплое (config/entity_registry/update),
    labels — самой Area. Оба поля необязательны: без Оркестратора они просто
    размечают реестр и никому не мешают.

    ⚠ light строим билдерами канона, а НЕ из unique_id группы: у YAML-групп
    entity_id выводится из отображаемого имени через slugify, а unique_id лишь
    регистрирует запись в реестре. Подробнее — data_model.md.
    """
    total = len(spaces_df)
    filtered, excluded = apply_filters(spaces_df, filters)

    print_filter_report(
        "Пространства и этажи для Home Assistant",
        filters,
        total=total,
        kept=len(filtered),
        excluded=excluded,
    )

    areas: List[Dict] = []
    floors: List[Dict] = []
    seen_floors = set()

    # Порядок — как в таблице.
    for _, row in filtered.iterrows():
        space = str(row["space"])
        room_slug = str(row["room_slug"])

        area: Dict = {
            "name": area_name(space),
            "aliases": area_aliases(room_slug),
            # Ровно одна световая сущность на Area — общий свет помещения.
            # Зонные группы и отдельные лампы сюда не попадают намеренно.
            "light": general_light_entity(room_slug),
        }

        space_type = normalize_space_type(row.get("space_type"))
        if space_type:
            area["labels"] = [ba_type_label(space_type)]
        else:
            # Тип не проставлен — метку не выдумываем. Оркестратор без неё
            # просто не применит профиль по типу; это лучше, чем неверный.
            print(f"  ⚠ у помещения {space} не указан тип — Area будет без метки типа")

        floor = row["floor"]

        # Помещение без этажа — не повод его терять: создаём Area без привязки.
        if pd.isna(floor):
            print(f"  ⚠ у помещения {space} не указан этаж — Area будет без привязки")
        else:
            level = int(floor)
            area["floor"] = level

            if level not in seen_floors:
                seen_floors.add(level)
                floors.append({
                    "level": level,
                    "name": floor_name(level),
                    "icon": floor_icon(level),
                })

        areas.append(area)

    floors.sort(key=lambda f: f["level"])

    # Area на каждый этаж — отдельно от комнатных и ПОСЛЕ них: порядок
    # помещений должен остаться как в таблице, наладчик сверяет YAML с Excel.
    #
    # Зачем: карточка `type: area` на Главной умеет показывать только Area,
    # карточки для Floor в HA нет. Комнатным Areas такая не конкурент —
    # сущность принадлежит ровно одной Area, но групповые светильники этажа
    # устройства не имеют, интеграция их никуда не разложит, и попадут они
    # только сюда (руками владельца).
    # Метка ba_floor_area отличает агрегатную Area от комнатной. Опознавать по
    # имени нельзя: area_id выводится из имени при создании, а переименование
    # в интерфейсе HA его не меняет — связь по имени разъедется. Без метки
    # Оркестратор отправил бы команду и на этажную группу, и на каждое
    # помещение этажа: то самое двойное воздействие, только с другой стороны.
    floor_areas = [
        {
            "name": floor_area_name(f["level"]),
            "aliases": [floor_area_id(f["level"])],
            "floor": f["level"],
            "light": floor_light_entity(f["level"]),
            "labels": [BA_FLOOR_AREA_LABEL],
        }
        for f in floors
    ]
    areas.extend(floor_areas)

    print(f"  Этажей:               {len(floors)}")
    print(f"  Пространств:          {len(areas) - len(floor_areas)}")
    print(f"  Areas этажей:         {len(floor_areas)}")

    return {"floors": floors, "areas": areas}


def render_yaml(payload: Dict) -> str:
    """
    YAML пишем текстом, а не сериализацией — как и остальные файлы проекта:
    наладчик читает результат глазами, поэтому важны комментарии и порядок.
    """
    lines: List[str] = [
        "# Пространства (Areas) и этажи (Floors) для Home Assistant.",
        "#",
        "# Это НЕ конфигурация HA — это задание на создание записей в реестрах.",
        "# Отправляется на объект отдельным шагом деплоя, по явному действию.",
        "#",
        "# name    — как помещение будет называться в HA (из колонки «Название помещения»)",
        "# aliases — транслит, чтобы помещение находилось и по нему",
        "# floor   — уровень этажа; сам floor_id выдаёт Home Assistant при создании",
        "# light   — какую световую сущность назначить в эту Area (ровно одну)",
        "# labels  — метки для Оркестратора здания",
        "#",
        "# ⚠ light назначится только той сущности, которая уже есть в реестре HA.",
        "# На ПЕРВОМ деплое групп света там ещё нет: пакеты только положены на",
        "# диск, а Home Assistant деплой не перезапускает. Это не ошибка —",
        "# перезапустите HA и повторите деплой, назначения доедут вторым проходом.",
        "",
    ]

    floors = payload.get("floors", [])
    areas = payload.get("areas", [])

    if not floors and not areas:
        return "# Нет данных для создания пространств\n"

    lines.append("floors:")
    if not floors:
        lines.append("  []")
    for floor in floors:
        lines.append(f"  - level: {floor['level']}")
        lines.append(f"    name: \"{floor['name']}\"")
        lines.append(f"    icon: {floor['icon']}")
    lines.append("")

    lines.append("areas:")
    for area in areas:
        lines.append(f"  - name: \"{area['name']}\"")

        aliases = area.get("aliases") or []
        if aliases:
            joined = ", ".join(f'"{a}"' for a in aliases)
            lines.append(f"    aliases: [{joined}]")

        if "floor" in area:
            lines.append(f"    floor: {area['floor']}")

        if area.get("light"):
            lines.append(f"    light: {area['light']}")

        labels = area.get("labels") or []
        if labels:
            joined = ", ".join(labels)
            lines.append(f"    labels: [{joined}]")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Подготовить пространства и этажи Home Assistant (офлайн, без подключения к HA).",
    )
    parser.add_argument("--normalized", default=str(DEFAULT_NORMALIZED_DIR),
                        help="Папка с parquet")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH),
                        help="Куда записать YAML")
    add_filter_args(parser, with_include_floors=True)
    args = parser.parse_args()

    output_path = Path(args.out)

    print("\n=== Generate Areas & Floors ===")
    print("Источник:", args.normalized)
    print("Выход   :", output_path)
    print()

    try:
        spaces_df = load_dataset(Path(args.normalized), "spaces")
    except NormalizedLayerError as exc:
        print(f"❌ {exc}")
        return 2

    payload = build_payload(spaces_df, filters_from_args(args))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_yaml(payload), encoding="utf-8")

    print(f"\nOK: {output_path}")
    print("   Файл офлайновый. Чтобы создать пространства в HA — шаг деплоя.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
