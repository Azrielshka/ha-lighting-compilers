# -*- coding: utf-8 -*-
"""
generate_zone_manager.py
Генератор zone_manager.json — конфигурации зон датчиков.

Вход:  data/normalized/neighbors.parquet  (лист «Группы соседей»)
Выход: data/json/zone_manager.json

Файл запрашивают blueprint'ы датчиков через zone_manager.get_sensor_config:
по entity_id датчика он возвращает light_group и neighbor_groups. Без этого
конфига автоматизация получает found: false и свет НЕ включается.

Интеграция: github.com/Azrielshka/zone_manager. Формат и правила сборки —
docs/internal/plan-zone-manager.md.

ВАЖНО: шаг офлайновый. Отправка на объект (/homeassistant/zone_manager.json) —
отдельный шаг деплоя.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

import pandas as pd

from scripts._lib.canon import (
    ZAGLUSHKA_LIGHT,
    ZAGLUSHKA_SENSOR,
    ZONE_MANAGER_VERSION,
)
from scripts._lib.normalized import NormalizedLayerError, load_dataset

__version__ = "1.0.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "json" / "zone_manager.json"

# Помещение для зон, чей датчик не нашёлся в «Проектной БД». Обычно значит
# опечатку в листе «Группы соседей»; строгую валидацию делает шаг 4.
UNKNOWN_SPACE = "(без помещения)"

# Эталонный блок NAME SPACE — идёт в выход первым, как образец структуры для
# человека, который откроет файл. Значения фиктивные (sensor.1, light.0),
# захардкожены дословно из templates/json/zone_manager.json.
NAME_SPACE_BLOCK: Dict = {
    "zones": {
        "sensor.1": {
            "neighbors": ["sensor.1", "sensor.2"],
            "far_neighbors": ["sensor.1", "sensor.2"],
            "neighbor_groups": ["light.1", "light.2"],
            "light_group": ["light.0"],
        },
        "sensor.2": {
            "neighbors": ["sensor.1", "sensor.2"],
            "far_neighbors": ["sensor.1", "sensor.2"],
            "neighbor_groups": ["light.1", "light.2"],
            "light_group": ["light.0"],
        },
    },
}


def build_zone_manager(neighbors_df: pd.DataFrame) -> Dict:
    """Собрать структуру zone_manager.json из зон датчиков.

    Порядок ключей зоны — как ждёт образец: neighbors, far_neighbors,
    neighbor_groups, light_group. light_group_single НЕ кладём: его интеграция
    вычисляет сама из light_group.
    """
    # NAME SPACE первым — эталон. Порядок помещений дальше — как в parquet
    # (порядок таблицы), порядок зон — как встретились.
    spaces: Dict = {"NAME SPACE": NAME_SPACE_BLOCK}

    for _, row in neighbors_df.iterrows():
        space = str(row["space"]).strip() or UNKNOWN_SPACE
        spaces.setdefault(space, {"zones": {}})

        spaces[space]["zones"][row["sensor"]] = {
            "neighbors": list(row["neighbors"]),
            "far_neighbors": list(row["far_neighbors"]),
            "neighbor_groups": list(row["neighbor_groups"]),
            "light_group": list(row["light_group"]),
        }

    return {"version": ZONE_MANAGER_VERSION, "spaces": spaces}


def check_references(payload: Dict, known_sensors: set, known_lights: set) -> list:
    """Сверить ссылки зон с реально существующими сущностями объекта.

    Возвращает предупреждения о битых ссылках (не ошибка: заглушки валидны, а
    реальная несуществующая ссылка — обычно опечатка в листе «Группы соседей»).
    Заглушки из проверки исключены — их сущностей на объекте и не должно быть.
    """
    stubs = {ZAGLUSHKA_SENSOR, ZAGLUSHKA_LIGHT}
    problems: list = []

    for space, body in payload["spaces"].items():
        if space == "NAME SPACE":
            continue  # эталон, реальных сущностей не содержит

        for sensor, zone in body["zones"].items():
            for field, known in (
                ("neighbors", known_sensors),
                ("far_neighbors", known_sensors),
                ("neighbor_groups", known_lights),
                ("light_group", known_lights),
            ):
                for ref in zone[field]:
                    if ref in stubs or ref in known:
                        continue
                    problems.append(f"{sensor} / {field}: нет сущности {ref}")

    return problems


def render_json(payload: Dict) -> str:
    """JSON с отступами и живой кириллицей (ensure_ascii=False)."""
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Собрать zone_manager.json (офлайн, без подключения к HA).",
    )
    parser.add_argument("--normalized", default=str(DEFAULT_NORMALIZED_DIR),
                        help="Папка с parquet")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH),
                        help="Куда записать JSON")
    args = parser.parse_args()

    output_path = Path(args.out)

    print("\n=== Generate Zone Manager ===")
    print("Источник:", args.normalized)
    print("Выход   :", output_path)
    print()

    try:
        neighbors = load_dataset(Path(args.normalized), "neighbors")
    except NormalizedLayerError as exc:
        print(f"❌ {exc}")
        return 2

    payload = build_zone_manager(neighbors)

    real_spaces = [s for s in payload["spaces"] if s != "NAME SPACE"]
    zones = sum(len(payload["spaces"][s]["zones"]) for s in real_spaces)

    print(f"  Помещений: {len(real_spaces)}")
    print(f"  Зон:       {zones}")

    if not real_spaces:
        print("\n  ⚠ Лист «Группы соседей» пуст — в файле только эталон NAME SPACE.")
        print("    zone_manager на объекте не заработает: свет по датчикам")
        print("    не будет включаться, пока лист не заполнен.")

    if UNKNOWN_SPACE in payload["spaces"]:
        n = len(payload["spaces"][UNKNOWN_SPACE]["zones"])
        print(f"\n  ⚠ {n} зон без помещения — датчик не найден в «Проектной БД».")
        print("    Проверьте адреса основных датчиков в листе «Группы соседей».")

    # Битые ссылки: сверяем соседей и группы с реальными сущностями объекта.
    # devices/groups/spaces могут отсутствовать (например, отдельный прогон) —
    # тогда сверку пропускаем, она не критична для сборки файла.
    try:
        norm_dir = Path(args.normalized)
        devices = load_dataset(norm_dir, "devices")
        groups = load_dataset(norm_dir, "groups")
        spaces = load_dataset(norm_dir, "spaces")

        known_sensors = set(devices.loc[devices["kind"] == "sensor", "entity_id"])
        known_lights = set(groups["zone_light_entity"]) | set(spaces["general_light_entity"])

        broken = check_references(payload, known_sensors, known_lights)
        if broken:
            print(f"\n  ⚠ Битых ссылок: {len(broken)} (вероятно, опечатки в листе):")
            for w in broken[:10]:
                print(f"    • {w}")
            if len(broken) > 10:
                print(f"    … и ещё {len(broken) - 10}")
    except NormalizedLayerError:
        print("\n  (сверка ссылок пропущена: нет devices/groups/spaces)")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_json(payload), encoding="utf-8")

    print(f"\nOK: {output_path}")
    print("   Файл офлайновый. Чтобы отправить на объект — шаг деплоя.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
