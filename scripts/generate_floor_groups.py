"""
Скрипт generate_floor_groups.py

Назначение:
    1. Прочитать нормализованные данные из data/normalized/device_rows.parquet.
    2. На основе этих данных собрать группы по этажам:
        - все помещения 1-го этажа -> "Весь 1-й этаж" (unique_id: floor_1_all)
        - все помещения 2-го этажа -> "Весь 2-й этаж" (unique_id: floor_2_all)
        и т.д.
    3. В группы этажей добавляем НЕ лампы, а общие группы помещений:
        light.<room_slug>_obshchii
    4. Результат сохраняем в data/light_groups/lights_floor_groups.yaml

Почему так:
    - исключаем повторное чтение Excel и любые "хрупкие" правила нейминга
    - используем канон (scripts/_lib/canon.py), чтобы entity_id всегда были едины
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Set

import pandas as pd

# Канон проекта
from scripts._lib.canon import TECHNICAL_CARD_TYPES

__version__ = "2.0.1"

# === НАСТРОЙКИ ===

# Корень проекта (чтобы запуск из PyCharm/терминала работал одинаково)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Вход: нормализованные строки устройств
SPACES_PARQUET = PROJECT_ROOT / "data" / "normalized" / "spaces.parquet"

# Выход: папка и файл
OUTPUT_DIR = PROJECT_ROOT / "data" / "light_groups"
OUTPUT_PATH = OUTPUT_DIR / "lights_floor_groups.yaml"

# Фильтры (в стиле других генераторов)
# Если INCLUDE_FLOORS не пустой — создаём группы только для этих этажей
INCLUDE_FLOORS: List[int] = []  # например [1, 2]

# Этажи, которые нужно исключить
EXCLUDE_FLOORS: List[int] = []  # например [0, 4]

# Ограничить генерацию только перечисленными пространствами (room_slug предпочтительнее)
SPACES_FILTER: List[str] = []  # например ["403_kabinet_medits", "402_kabinet_medits"]

# Исключить пространства, в названии которых встречаются подстроки (без учёта регистра)
EXCLUDE_SPACE_CONTAINS: List[str] = []  # например ["sklad", "server"]

# Включить/выключить генерацию тех.групп по этажам (1 = да, 0 = нет)
GENERATE_TECH_GROUPS: int = 0

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def _space_key(row: pd.Series) -> str:
    """
    Ключ помещения для фильтров/комментариев:
    - берём room_slug (стабильный)
    - если его нет — fallback на space
    """
    rs = row.get("room_slug", None)
    sp = row.get("space", None)

    v = rs if rs is not None and str(rs).strip() else sp
    return "" if v is None else str(v).strip()


def make_floor_group_name(floor: int) -> str:
    """
    Формирование name для группы этажа (русское отображение):
        "Весь 1-й этаж", "Весь 2-й этаж", ...
    """
    return f"Весь {floor}-й этаж"


def make_floor_group_unique_id(floor: int) -> str:
    """
    Формирование unique_id для группы этажа:
        "floor_1_all", "floor_2_all", ...
    """
    return f"floor_{floor}_all"

def build_floor_entities_from_spaces(spaces_df: pd.DataFrame) -> tuple[Dict[int, Set[str]], Dict[int, Set[str]]]:
    """
    Собрать 2 структуры:
      - floor_all: этаж -> множество entity_id общих групп ВСЕХ помещений этажа
      - floor_tech: этаж -> множество entity_id общих групп ТЕХНИЧЕСКИХ помещений этажа (по card_type)

    Источник данных: spaces.parquet (уже агрегирован по помещениям).
    """
    total_rows = len(spaces_df)

    # Контракт данных: необходимые колонки в spaces.parquet
    required_cols = ["floor", "card_type", "general_light_entity", "room_slug", "space"]
    for c in required_cols:
        if c not in spaces_df.columns:
            raise ValueError(f"В spaces.parquet нет обязательной колонки: '{c}'")

    df = spaces_df.copy()

    # floor приводим к int (через numeric на случай NaN/строк)
    df["__floor"] = pd.to_numeric(df["floor"], errors="coerce")
    df = df[~df["__floor"].isna()]
    df["__floor"] = df["__floor"].astype(int)

    # ключ помещения для фильтров: room_slug предпочтительнее, иначе space
    df["__space_key"] = df["room_slug"].fillna("").astype(str).str.strip()
    df.loc[df["__space_key"] == "", "__space_key"] = df["space"].fillna("").astype(str).str.strip()

    # card_type нормализуем
    df["__card_type"] = df["card_type"].fillna("").astype(str).str.strip()

    # general_light_entity нормализуем
    df["__general"] = df["general_light_entity"].fillna("").astype(str).str.strip()

    # Базовая фильтрация: должны быть ключ помещения + general entity
    df = df[(df["__space_key"] != "") & (df["__general"] != "")]
    rows_after_basic = len(df)

    spaces_before_filters = list(dict.fromkeys(df["__space_key"]))

    # --- фильтры пользователя (как в других генераторах) ---

    # 1) SPACES_FILTER
    if SPACES_FILTER:
        df = df[df["__space_key"].isin(SPACES_FILTER)]

    df = df.copy()

    # 2) INCLUDE_FLOORS / EXCLUDE_FLOORS
    if INCLUDE_FLOORS:
        include_set = set(int(x) for x in INCLUDE_FLOORS)
        df = df[df["__floor"].isin(include_set)]

    if EXCLUDE_FLOORS:
        exclude_set = set(int(x) for x in EXCLUDE_FLOORS)
        df = df[~df["__floor"].isin(exclude_set)]

    # 3) EXCLUDE_SPACE_CONTAINS
    if EXCLUDE_SPACE_CONTAINS:
        subs = [s.lower() for s in EXCLUDE_SPACE_CONTAINS]

        def space_allowed(space_name: str) -> bool:
            s = str(space_name).lower()
            return not any(sub in s for sub in subs)

        df = df[df["__space_key"].apply(space_allowed)]

    rows_after_filters = len(df)

    if df.empty:
        print("⚠ После всех фильтров не осталось строк. Группы этажей не будут сгенерированы.")
        print(f"  Всего строк в spaces.parquet:          {total_rows}")
        print(f"  После базовой фильтрации:             {rows_after_basic}")
        return {}, {}

    # Уникальные строки по помещениям (spaces.parquet и так агрегирован, но на всякий случай)
    df_rooms = df[["__floor", "__space_key", "__card_type", "__general"]].drop_duplicates()

    # floor -> entities (all)
    floor_all: Dict[int, Set[str]] = {}
    # floor -> entities (tech)
    floor_tech: Dict[int, Set[str]] = {}

    for floor, sdf in df_rooms.groupby("__floor", sort=False):
        f = int(floor)

        # Все помещения этажа
        all_ents = set(sdf["__general"].tolist())
        floor_all[f] = all_ents

        # Только тех.помещения этажа
        tech_sdf = sdf[sdf["__card_type"].isin(TECHNICAL_CARD_TYPES)]
        tech_ents = set(tech_sdf["__general"].tolist())
        floor_tech[f] = tech_ents

    # --- отчёт ---
    spaces_after_filters = list(dict.fromkeys(df_rooms["__space_key"]))
    excluded_spaces = [s for s in spaces_before_filters if s not in spaces_after_filters]

    print("📊 Статистика по группам этажей (из spaces.parquet):")
    print(f"  Версия:                                 {__version__}")
    print(f"  Всего строк в spaces.parquet:           {total_rows}")
    print(f"  После базовой фильтрации:               {rows_after_basic}")
    print(f"  После всех фильтров (строк):            {rows_after_filters}")
    print(f"  Этажей найдено:                         {len(floor_all)}")

    total_entities_all = sum(len(s) for s in floor_all.values())
    print(f"  Всего сущностей в группах этажей:       {total_entities_all}")

    if GENERATE_TECH_GROUPS:
        tech_floors = len([f for f in floor_tech.keys() if len(floor_tech[f]) > 0])
        total_entities_tech = sum(len(s) for s in floor_tech.values())
        print(f"  Тех. этажей (не пустых):                {tech_floors}")
        print(f"  Всего сущностей в тех. группах:         {total_entities_tech}")
    else:
        print("  Генерация тех. групп:                   выключена (GENERATE_TECH_GROUPS=0)")

    if excluded_spaces:
        print(f"  Пространства, исключённые фильтрами:    {len(excluded_spaces)} шт")
    else:
        print("  Пространства, исключённые фильтрами:    нет")

    return floor_all, floor_tech

def make_tech_floor_group_name(floor: int) -> str:
    """
    Формирование name для тех.группы этажа:
        "Тех.пом 4-й этаж"
    """
    return f"Тех.пом {floor}-й этаж"


def make_tech_floor_group_unique_id(floor: int) -> str:
    """
    Формирование unique_id для тех.группы этажа:
        "tex_floor_4"
    """
    return f"tex_floor_{floor}"

def render_floor_groups_yaml(floor_all: Dict[int, Set[str]], floor_tech: Dict[int, Set[str]]) -> str:
    """
    Собрать YAML-текст для групп по этажам.
      - всегда: группа "Весь N-й этаж"
      - опционально: "Тех.пом N-й этаж" если GENERATE_TECH_GROUPS=1 и список не пуст
    Формат результата:

        lights_floor_group:
          light:
            #Группа для всего 1-го этажа
            - platform: group
              name: "Весь 1-й этаж"
              unique_id: "floor_1_all"
              entities:
                - light.101_kabinet_obshchii
                - light.102_kabinet_obshchii
                ...

    Этажи сортируем по возрастанию, entity_id внутри — тоже сортируем для стабильности.
    """
    if not floor_all:
        return "# Нет данных для формирования групп по этажам\n"

    lines: List[str] = []
    lines.append("lights_floor_group:")
    lines.append("  light:")

    for floor in sorted(floor_all.keys()):
        # --- 1) Весь этаж ---
        ents_all = sorted(floor_all.get(floor, set()))

        comment_all = f"  #Группа для всего {floor}-го этажа"
        name_all = make_floor_group_name(floor)
        unique_id_all = make_floor_group_unique_id(floor)

        lines.append(comment_all)
        lines.append("    - platform: group")
        lines.append(f'      name: "{name_all}"')
        lines.append(f'      unique_id: "{unique_id_all}"')
        lines.append("      entities:")

        for ent in ents_all:
            lines.append(f"        - {ent}")

        lines.append("")

        # --- 2) Тех.помещения этажа (по флагу) ---
        if GENERATE_TECH_GROUPS:
            ents_tech = sorted(floor_tech.get(floor, set()))

            # если на этаже нет тех.помещений — блок не выводим
            if ents_tech:
                comment_tech = f"  #Группа для тех помещений {floor}-го этажа"
                name_tech = make_tech_floor_group_name(floor)
                unique_id_tech = make_tech_floor_group_unique_id(floor)

                lines.append(comment_tech)
                lines.append("    - platform: group")
                lines.append(f'      name: "{name_tech}"')
                lines.append(f'      unique_id: "{unique_id_tech}"')
                lines.append("      entities:")

                for ent in ents_tech:
                    lines.append(f"        - {ent}")

                lines.append("")

    # убрать пустой хвост
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


# === ТОЧКА ВХОДА ===

def main() -> None:
    # Загружаем агрегированные помещения (spaces.parquet)
    spaces_df = pd.read_parquet(SPACES_PARQUET)

    # Собираем 2 набора: "весь этаж" и "тех этаж"
    floor_all, floor_tech = build_floor_entities_from_spaces(spaces_df)

    # Рендерим YAML (тех-блоки добавляются по флагу GENERATE_TECH_GROUPS)
    yaml_text = render_floor_groups_yaml(floor_all, floor_tech)

    # создаём папку data/light_groups если её нет
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # записываем YAML
    OUTPUT_PATH.write_text(yaml_text, encoding="utf-8")
    print(f"Готово! Файл с группами по этажам записан в: {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()