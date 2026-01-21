"""
Скрипт generate_floor_groups.py

Назначение:
    1. Прочитать файл lights_general_groups.yaml, в котором описаны
       общие группы по помещениям (403 Общий кабинет медиц, 171 Общий лестница и т.п.).
    2. На основе этих данных собрать группы по этажам:
        - все помещения 1-го этажа (101, 102, 103, ...) -> "Весь 1-й этаж"
        - все помещения 2-го этажа (201, 202, 203, ...) -> "Весь 2-й этаж"
        и т.д.
    3. В группы этажей ДОБАВЛЯЕМ НЕ ЛАМПЫ, а сами общие группы помещений,
       то есть их entity_id (light.<slug от name>).
    4. Результат сохраняем в lights_floor_groups.yaml.

Требуется библиотека PyYAML:
    pip install pyyaml
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

# Если INCLUDE_FLOORS не пустой — создаём группы только для этих этажей
INCLUDE_FLOORS: list[int] = []  # например [1, 2]

# Этажи, которые нужно исключить
EXCLUDE_FLOORS: list[int] = []  # например [0, 4]


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def transliterate_ru_to_en(text: str) -> str:
    """
    Простейшая транслитерация кириллицы в латиницу для формирования slug.
    Не претендует на полное совпадение с Home Assistant, но логика похожа.

    Пример:
        "403 Общий кабинет медиц" -> "403_obshchii_kabinet_medits"
    """
    mapping = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
        "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
        "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch",
        "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
        " ": "_", "-": "_", "/": "_", ".": "_",
    }

    result_chars = []
    for ch in text.lower():
        if ch in mapping:
            result_chars.append(mapping[ch])
        elif ch.isalnum():
            # Латиница и цифры оставляем как есть
            result_chars.append(ch)
        else:
            # Остальное превращаем в "_"
            result_chars.append("_")

    slug = "".join(result_chars)
    # Сжимаем повторяющиеся "_" и убираем ведущие/хвостовые
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def general_group_entity_id_from_name(name: str) -> str:
    """
    Преобразует name общей группы помещения в ожидаемый entity_id.

    Пример:
        name: "403 Общий кабинет медиц"
        -> "light.403_obshchii_kabinet_medits"
    """
    slug = transliterate_ru_to_en(name)
    # На всякий случай, если slug пустой — подстрахуемся
    if not slug:
        slug = "general_group"
    return f"light.{slug}"


def detect_floor_from_entity(entity_id: str) -> int | None:
    """
    Определяем номер этажа по entity_id лампы/подгруппы.

    Ожидаемый формат:
        light.<room>_<...>

    Где <room> — трёхзначный номер помещения:
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

    floor = room_num // 100
    return floor


def make_floor_group_name(floor: int) -> str:
    """
    Формирование name для группы этажа на РУССКОМ:

        "Весь 1-й этаж", "Весь 2-й этаж", ...
    """
    return f"Весь {floor}-й этаж"


def make_floor_group_unique_id(floor: int) -> str:
    """
    Формирование unique_id для группы этажа.

    Делаем его латинским и стабильным:
        "floor_1_all", "floor_2_all", ...
    """
    return f"floor_{floor}_all"


# === ОСНОВНАЯ ЛОГИКА ===

def load_general_groups(path: Path) -> list[dict]:
    """
    Загрузка lights_general_groups.yaml и получение списка
    общих групп по помещениям.

    Ожидаем структуру:

        lights_general_group:
          light:
            - platform: group
              name: "403 Общий кабинет медиц"
              unique_id: "403 Общий кабинет медиц"
              entities:
                - light.403_0
                - light.403_1
                - light.403_2

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


def build_floor_groups(groups: list[dict]) -> dict[int, set[str]]:
    """
    Собрать структуру: этаж -> множество entity_id ОБЩИХ ГРУПП помещений.

    Логика:
        - Для каждой общей группы берём её entities (лампы) и name.
        - По ПЕРВОЙ лампе определяем этаж.
        - Формируем entity_id самой общей группы по её name
          (light.<slug(name)>).
        - Добавляем этот entity_id в множество сущностей для этажа.

    Возвращаем:
        { floor_number: { "light.xxx", "light.yyy", ... }, ... }
    """
    floor_entities: dict[int, set[str]] = defaultdict(set)

    for grp in groups:
        name = grp.get("name", "")
        entities = grp.get("entities", [])
        if not entities:
            # Нет ламп внутри общей группы — пропускаем
            continue

        # Определяем этаж по первой лампе в общей группе
        first_entity = entities[0]
        floor = detect_floor_from_entity(first_entity)
        if floor is None:
            # Если не удалось распознать этаж — пропускаем
            continue

        # Применяем фильтры по этажам, если заданы
        if INCLUDE_FLOORS and floor not in INCLUDE_FLOORS:
            continue
        if EXCLUDE_FLOORS and floor in EXCLUDE_FLOORS:
            continue

        # entity_id самой общей группы, которую будем включать в этаж
        group_entity_id = general_group_entity_id_from_name(name)

        floor_entities[floor].add(group_entity_id)

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
                - light.403_obshchii_kabinet_medits
                - light.402_obshchii_kabinet_medits
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

        # Пустая строка между группами этажей
        lines.append("")

    # Убираем возможный лишний пустой хвост
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


# === ТОЧКА ВХОДА ===

def main():
    # 1. Загружаем общие группы по помещениям
    groups = load_general_groups(INPUT_PATH)

    # 2. Строим структуру "этаж -> множество entity_id общих групп"
    floor_entities = build_floor_groups(groups)

    # 3. Небольшая статистика в консоль
    total_floors = len(floor_entities)
    total_entities = sum(len(s) for s in floor_entities.values())
    print("📊 Статистика по группам этажей:")
    print(f"  Этажей найдено:         {total_floors}")
    print(f"  Всего общих групп в них: {total_entities}")
    if INCLUDE_FLOORS:
        print(f"  Фильтр INCLUDE_FLOORS: {INCLUDE_FLOORS}")
    if EXCLUDE_FLOORS:
        print(f"  Фильтр EXCLUDE_FLOORS: {EXCLUDE_FLOORS}")

    # 4. Генерируем YAML
    yaml_text = render_floor_groups_yaml(floor_entities)

    # 5. Записываем результат
    OUTPUT_PATH.write_text(yaml_text, encoding="utf-8")
    print(f"Готово! Файл с группами по этажам записан в: {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
