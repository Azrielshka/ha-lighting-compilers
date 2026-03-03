"""
Скрипт generate_floor_groups.py

Назначение:
    1. Прочитать файл lights_general_groups.yaml, в котором описаны общие группы по помещениям.
    2. На основе этих данных собрать группы по этажам:
        - все помещения 1-го этажа (101, 102, 103, ...) -> "Весь 1-й этаж"
        - все помещения 2-го этажа (201, 202, 203, ...) -> "Весь 2-й этаж"
        и т.д.
    3. Сгенерировать новый YAML-файл lights_floor_groups.yaml
       с группами вида:

        lights_floor_group:
          light:
            #Группа для всего 1-го этажа
            - platform: group
              name: "Весь 1-й этаж"
              unique_id: "floor_1_all"
              entities:
                - light.101_0
                - light.101_1
                - light.102_0
                ...

Особенности:
    - Скрипт НЕ лезет в Excel — он работает только с уже сгенерированным lights_general_groups.yaml.
    - Для разбора YAML используется библиотека PyYAML (pip install pyyaml).
"""

from pathlib import Path
from collections import defaultdict
import re

import yaml  # pip install pyyaml


# === НАСТРОЙКИ ===

# Входной YAML-файл с общими группами по помещениям
INPUT_PATH = Path("lights_general_groups.yaml")

# Выходной YAML-файл с группами по этажам
OUTPUT_PATH = Path("lights_floor_groups.yaml")

# Фильтры по этажам:
# Если INCLUDE_FLOORS не пустой — генерируем группы только для перечисленных этажей.
INCLUDE_FLOORS = []  # например [1, 2]

# Этажи, которые нужно исключить (не создавать групп для них)
EXCLUDE_FLOORS = []  # например [0, 4]


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def detect_floor_from_entity(entity_id: str) -> int | None:
    """
    Определение номера этажа по entity_id подгруппы.

    Ожидаемый формат:
        light.<room>_<...>
    где <room> — трёхзначный номер помещения:
        101, 102, 126, 203, 304, ...

    Правило:
        floor = room // 100

    Примеры:
        light.101_0 -> room=101 -> floor=1
        light.203_1 -> room=203 -> floor=2

    Если формат не подходит — возвращаем None.
    """
    m = re.search(r"^light\.(\d+)_", entity_id)
    if not m:
        return None

    room_num_str = m.group(1)
    try:
        room_num = int(room_num_str)
    except ValueError:
        return None

    # Этаж — сотни (101..199 -> 1, 201..299 -> 2 и т.д.)
    floor = room_num // 100
    return floor


def make_floor_group_name(floor: int) -> str:
    """
    Формирование name для группы этажа на РУССКОМ:

        "Весь 1-й этаж", "Весь 2-й этаж", ...

    При желании можно доработать склонения (1-й, 2-й, 3-й и т.п.),
    но для наших задач достаточно "N-й".
    """
    return f"Весь {floor}-й этаж"


def make_floor_group_unique_id(floor: int) -> str:
    """
    Формирование unique_id для группы этажа.

    Делаем его латинским и стабильным, чтобы не зависеть от локализации:
        "floor_1_all", "floor_2_all", ...
    """
    return f"floor_{floor}_all"


# === ОСНОВНАЯ ЛОГИКА ===

def load_general_groups(path: Path) -> list[dict]:
    """
    Загрузка lights_general_groups.yaml и получение
    списка общих групп по помещениям.

    Ожидаем структуру:
        lights_general_group:
          light:
            - platform: group
              name: "113 Общий учебный кабинет"
              unique_id: "113 Общий учебный кабинет"
              entities:
                - light.113_0
                - light.113_1
                ...

    Возвращаем список этих словарей (элементы массива 'light').
    """
    if not path.exists():
        raise FileNotFoundError(f"Входной файл не найден: {path}")

    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    if not isinstance(data, dict) or "lights_general_group" not in data:
        raise ValueError("Ожидается корневой ключ 'lights_general_group' в YAML.")

    lg = data["lights_general_group"]
    if not isinstance(lg, dict) or "light" not in lg:
        raise ValueError("В 'lights_general_group' ожидается ключ 'light' со списком групп.")

    groups = lg["light"]
    if not isinstance(groups, list):
        raise ValueError("'lights_general_group.light' должен быть списком.")

    return groups


def build_floor_groups(groups: list[dict]) -> dict:
    """
    Собрать структуру данных для групп по этажам.

    Вход:
        groups — список общих групп по помещениям (как из YAML),
                 каждая группа содержит entities со списком light.<room>_<...>.

    Логика:
        - для каждой общей группы смотрим её entities;
        - по ПЕРВОМУ entity определяем этаж (detect_floor_from_entity);
        - все entities этой общей группы добавляем в набор данного этажа.

    Выход:
        словарь { floor: set(entity_ids) }, например:
            {
              1: {"light.101_0", "light.101_1", "light.102_0", ...},
              2: {"light.201_0", "light.201_1", ...},
            }
    """
    floor_entities: dict[int, set[str]] = defaultdict(set)

    for grp in groups:
        entities = grp.get("entities", [])
        if not entities:
            continue

        # Определяем этаж по первой лампе в общей группе
        first_entity = entities[0]
        floor = detect_floor_from_entity(first_entity)
        if floor is None:
            # Если невозможно распознать этаж — пропускаем эту группу
            continue

        # Применяем фильтры по этажам, если заданы
        if INCLUDE_FLOORS and floor not in INCLUDE_FLOORS:
            continue
        if EXCLUDE_FLOORS and floor in EXCLUDE_FLOORS:
            continue

        # Добавляем все entities этой общей группы в этаж
        for ent in entities:
            floor_entities[floor].add(ent)

    return floor_entities


def render_floor_groups_yaml(floor_entities: dict[int, set[str]]) -> str:
    """
    Собрать YAML-текст для групп по этажам из словаря floor_entities.

    Формат результата:

        lights_floor_group:
          light:
            #Группа для всего 1-го этажа
            - platform: group
              name: "Весь 1-й этаж"
              unique_id: "floor_1_all"
              entities:
                - light.101_0
                - light.101_1
                - light.102_0
                ...

    Этажи сортируем по возрастанию.
    """
    if not floor_entities:
        return "# Нет данных для формирования групп по этажам\n"

    lines: list[str] = []
    lines.append("lights_floor_group:")
    lines.append("  light:")

    for floor in sorted(floor_entities.keys()):
        ents = sorted(floor_entities[floor])  # сортируем entity_id для стабильности

        comment = f"  #Группа для всего {floor}-го этажа"
        name = make_floor_group_name(floor)
        unique_id = make_floor_group_unique_id(floor)

        lines.append(comment)
        lines.append("    - platform: group")
        lines.append(f'      name: "{name}"')
        lines.append(f'      unique_id: "{unique_id}"')
        lines.append("      entities:")

        for ent in ents:
            lines.append(f"        - {ent}")

        # Пустая строка между группами этажей для читаемости
        lines.append("")

    # Убираем возможный лишний пустой хвост
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


# === ТОЧКА ВХОДА ===

def main():
    # 1. Загружаем общие группы по помещениям
    groups = load_general_groups(INPUT_PATH)

    # 2. Строим структуру "этаж -> множество entity_id"
    floor_entities = build_floor_groups(groups)

    # Небольшая статистика в консоль
    total_floors = len(floor_entities)
    total_entities = sum(len(s) for s in floor_entities.values())
    print("📊 Статистика по группам этажей:")
    print(f"  Этажей найдено:        {total_floors}")
    print(f"  Всего сущностей (ламп): {total_entities}")
    if INCLUDE_FLOORS:
        print(f"  Фильтр INCLUDE_FLOORS: {INCLUDE_FLOORS}")
    if EXCLUDE_FLOORS:
        print(f"  Фильтр EXCLUDE_FLOORS: {EXCLUDE_FLOORS}")

    # 3. Генерируем YAML
    yaml_text = render_floor_groups_yaml(floor_entities)

    # 4. Записываем результат
    OUTPUT_PATH.write_text(yaml_text, encoding="utf-8")
    print(f"Готово! Файл с группами по этажам записан в: {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
