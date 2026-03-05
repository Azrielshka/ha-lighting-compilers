# generate_general_groups.py
# ------------------------------------------------------------
# v2.0.1
# Генератор общих групп света (general light groups)
#
# Источник данных: нормализованный parquet слой
#   data/normalized/device_rows.parquet
#
# Выход:
#   data/light_groups/lights_general_groups.yaml
#
# Логика:
# - для каждого помещения (room_slug/space) собрать список подгрупп (group_id)
# - сгенерировать одну общую группу: <room_slug>_obshchii
#   entities:
#     - light.<group_id_0>
#     - light.<group_id_1>
# ------------------------------------------------------------

from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd

# Канон проекта (единые правила нейминга)
from scripts._lib.canon import GENERAL_LIGHT_RULE, HA_LIGHT_DOMAIN


__version__ = "2.0.1"

# === НАСТРОЙКИ ===

# Корень проекта (чтобы запуск из PyCharm/терминала работал одинаково)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Вход: нормализованные строки устройств
DEVICE_ROWS_PARQUET = PROJECT_ROOT / "data" / "normalized" / "device_rows.parquet"

# Выход: папка и файл
OUTPUT_DIR = PROJECT_ROOT / "data" / "light_groups"
OUTPUT_PATH = OUTPUT_DIR / "lights_general_groups.yaml"

# Фильтры (оставляем как в других генераторах)

# Ограничить генерацию только перечисленными пространствами.
# Рекомендуется указывать room_slug (стабильный), но можно и space.
SPACES_FILTER: List[str] = []  # например ["403_kabinet_medits", "402_kabinet"]

# Исключить все пространства определённых этажей (берём floor из parquet)
EXCLUDE_FLOORS: List[int] = []  # например [4] чтобы исключить весь 4-й этаж

# Исключить пространства, в названии которых встречаются подстроки (без учёта регистра)
EXCLUDE_SPACE_CONTAINS: List[str] = ["koridor"]  # например ["sklad", "server"]


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def _space_key(row: pd.Series) -> str:
    """
    Ключ помещения для группировки/фильтров.
    Берём room_slug (стабильный), если его нет — space (человекочитаемое).
    """
    rs = row.get("room_slug", None)
    sp = row.get("space", None)

    v = rs if rs is not None and str(rs).strip() else sp
    return "" if v is None else str(v).strip()


def load_device_rows(path: Path) -> pd.DataFrame:
    """
    Загрузить device_rows.parquet в DataFrame.
    """
    if not path.exists():
        raise FileNotFoundError(f"Parquet не найден: {path}")

    return pd.read_parquet(path)


def build_general_groups(df: pd.DataFrame) -> str:
    """
    Собрать YAML-текст с общими группами по помещениям.

    Ожидаемые колонки:
      - group_id
      - room_slug / space
      - floor (желательно, для EXCLUDE_FLOORS)

    Выход:
      lights_general_group:
        light:
        #Общая группа для <space>
          - platform: group
            name: "<room_slug>_obshchii"
            unique_id: "<room_slug>_obshchii"
            entities:
              - light.<group_id_0>
              - light.<group_id_1>
    """
    total_rows = len(df)

    # --- проверка контракта данных ---
    required_cols = ["group_id"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"В device_rows.parquet нет обязательной колонки: '{c}'")

    df = df.copy()

    # ключ помещения для группировки/фильтров
    df["__space_key"] = df.apply(_space_key, axis=1)

    # room_slug отдельно — он нужен, чтобы собрать стабильное имя общей группы
    if "room_slug" in df.columns:
        df["__room_slug"] = df["room_slug"].fillna("").astype(str).str.strip()
    else:
        df["__room_slug"] = ""

    # group_id как строка
    df["__group"] = df["group_id"].fillna("").astype(str).str.strip()

    # floor для фильтра по этажам
    if "floor" in df.columns:
        df["__floor"] = pd.to_numeric(df["floor"], errors="coerce")
    else:
        df["__floor"] = pd.NA

    # Базовая фильтрация: нужны space_key + group_id
    df = df[(df["__space_key"] != "") & (df["__group"] != "")]
    rows_after_basic = len(df)

    spaces_before_filters = list(dict.fromkeys(df["__space_key"]))

    # --- фильтры пользователя ---

    # 1) SPACES_FILTER
    if SPACES_FILTER:
        df = df[df["__space_key"].isin(SPACES_FILTER)]

    df = df.copy()

    # 2) EXCLUDE_FLOORS
    if EXCLUDE_FLOORS:
        floors = set(int(x) for x in EXCLUDE_FLOORS)
        df = df[~df["__floor"].apply(lambda x: (not pd.isna(x)) and int(x) in floors)]

    # 3) EXCLUDE_SPACE_CONTAINS
    if EXCLUDE_SPACE_CONTAINS:
        subs = [s.lower() for s in EXCLUDE_SPACE_CONTAINS]

        def space_allowed(space_name: str) -> bool:
            s = str(space_name).lower()
            return not any(sub in s for sub in subs)

        df = df[df["__space_key"].apply(space_allowed)]

    rows_after_filters = len(df)

    if df.empty:
        print("⚠ После всех фильтров не осталось строк. Общие группы не будут сгенерированы.")
        print(f"  Всего строк в parquet:                 {total_rows}")
        print(f"  После базовой фильтрации (space+group): {rows_after_basic}")
        return "# Нет данных для генерации общих групп\n"

    # Уникальные пары (помещение, подгруппа)
    df_pairs = df[["__space_key", "__room_slug", "__group"]].drop_duplicates()
    spaces_after_filters = list(dict.fromkeys(df_pairs["__space_key"]))
    groups_after_filters = list(dict.fromkeys(df_pairs["__group"]))
    excluded_spaces = [s for s in spaces_before_filters if s not in spaces_after_filters]

    # --- отчёт ---
    print("📊 Статистика по общим группам света:")
    print(f"  Версия:                                 {__version__}")
    print(f"  Всего строк в parquet:                  {total_rows}")
    print(f"  После базовой фильтрации (space+group): {rows_after_basic}")
    print(f"  После всех фильтров (строк):            {rows_after_filters}")
    print(f"  Уникальных пространств:                 {len(spaces_after_filters)}")
    print(f"  Уникальных подгрупп:                    {len(groups_after_filters)}")
    if excluded_spaces:
        print(f"  Пространства, исключённые фильтрами:    {len(excluded_spaces)} шт")
    else:
        print("  Пространства, исключённые фильтрами:    нет")

    # --- генерация YAML ---
    lines: List[str] = []
    lines.append("lights_general_group:")
    lines.append("  light:")

    # Группируем по помещению (в порядке появления)
    for space_key, df_space in df_pairs.groupby("__space_key", sort=False):
        space_key_str = str(space_key).strip()
        if not space_key_str:
            continue

        # room_slug нужен для стабильного object_id общей группы
        # Если room_slug пуст (нежелательно), fallback на space_key
        room_slug = (
            df_space["__room_slug"].iloc[0]
            if "__room_slug" in df_space.columns and str(df_space["__room_slug"].iloc[0]).strip()
            else space_key_str
        )

        # object_id общей группы: "<room_slug>_obshchii"
        # (чтобы entity_id стал "light.<room_slug>_obshchii")
        general_object_id = f"{room_slug}{GENERAL_LIGHT_RULE.suffix}"

        # Комментарий к блоку
        lines.append(f"  #Общая группа для {space_key_str}")

        lines.append("    - platform: group")
        lines.append(f'      name: "{general_object_id}"')
        lines.append(f'      unique_id: "{general_object_id}"')
        lines.append("      entities:")

        # Все подгруппы этого помещения: light.<group_id>
        for group_name in df_space["__group"]:
            group_name_str = str(group_name).strip()
            if not group_name_str:
                continue
            lines.append(f"        - {HA_LIGHT_DOMAIN}.{group_name_str}")

        # пустая строка между группами
        lines.append("")

    # убрать пустой хвост
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


# === ТОЧКА ВХОДА ===

def main() -> None:
    df = load_device_rows(DEVICE_ROWS_PARQUET)
    yaml_text = build_general_groups(df)

    # создаём папку data/light_groups если её нет
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # записываем YAML
    OUTPUT_PATH.write_text(yaml_text, encoding="utf-8")
    print(f"Готово! Файл с общими группами записан в: {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()