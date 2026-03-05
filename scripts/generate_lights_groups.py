# generate_lights_groups.py
# ------------------------------------------------------------
# v2.0.1
# Генератор lights_group.yaml (подгруппы светильников)
# Источник данных: нормализованный parquet слой
#   data/normalized/device_rows.parquet
#
# Выход:
#   lights_group.yaml
#
# Логика сохранена:
# - группируем по помещению -> group_id
# - внутри группы выводим лампы (lamp_id -> light.l_<...>)
# - печатаем отчёт + поддерживаем фильтры SPACES_FILTER / EXCLUDE_FLOORS / EXCLUDE_SPACE_CONTAINS
# ------------------------------------------------------------

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

from pathlib import Path
from typing import List
from scripts._lib.canon import normalize_lamp_id_to_entity

import pandas as pd


__version__ = "2.0.1"

# === НАСТРОЙКИ ===

# Корень проекта (чтобы запуск из PyCharm / терминала работал одинаково)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Вход: нормализованные строки устройств
DEVICE_ROWS_PARQUET = PROJECT_ROOT / "data" / "normalized" / "device_rows.parquet"

# Папка для YAML групп света
OUTPUT_DIR = PROJECT_ROOT / "data" / "light_groups"

# Финальный файл
OUTPUT_PATH = OUTPUT_DIR / "lights_group.yaml"

# Фильтры (оставляем как ты привык)

# Ограничить генерацию только перечисленными пространствами
# Рекомендуемое значение: room_slug из parquet, например "403_ka...".
SPACES_FILTER: List[str] = []  # например ["403_kabinet_medits", "404_kabinet"]

# Исключить все пространства определённых этажей (берём floor из parquet)
EXCLUDE_FLOORS: List[int] = []  # например [4] чтобы исключить весь 4-й этаж

# Исключить пространства, в названии которых встречаются подстроки (без учёта регистра)
EXCLUDE_SPACE_CONTAINS: List[str] = []  # например ["kabinet"]


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def _space_key(row: pd.Series) -> str:
    """
    Ключ помещения для группировки/фильтров.
    Берём room_slug (стабильный), если его нет — space.
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

    df = pd.read_parquet(path)
    return df


def build_groups(df: pd.DataFrame) -> str:
    """
    Собрать YAML-текст для lights_group из нормализованного DataFrame.

    Ожидаемые колонки в df:
      - group_id
      - lamp_id
      - floor (опционально, но желательно для EXCLUDE_FLOORS)
      - room_slug / space (для группировки и комментария)

    Вывод (как раньше):
      lights_group:
        light:
        #Группы для <space>
          - platform: group
            name: "<group_id>"
            unique_id: <group_id>
            entities:
              - light.l_...
    """
    total_rows = len(df)

    # --- проверка контракта данных (чтобы сразу было понятно, почему упало) ---
    required_cols = ["group_id", "lamp_id"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"В device_rows.parquet нет обязательной колонки: '{c}'")

    # --- подготовка нормализованных служебных колонок ---
    df = df.copy()

    # ключ помещения для группировки/фильтров
    df["__space_key"] = df.apply(_space_key, axis=1)

    # group_id / lamp_id как строки
    df["__group"] = df["group_id"].fillna("").astype(str).str.strip()
    df["__lamp"] = df["lamp_id"].fillna("").astype(str).str.strip()

    # floor может быть Int64/float/None — приводим к числу, чтобы фильтровать корректно
    if "floor" in df.columns:
        df["__floor"] = pd.to_numeric(df["floor"], errors="coerce")
    else:
        df["__floor"] = pd.NA

    # --- базовая фильтрация: нужны строки с group_id и lamp_id ---
    df = df[(df["__group"] != "") & (df["__lamp"] != "")]
    rows_after_basic = len(df)

    # Список пространств после базовой фильтрации
    spaces_before_filters = list(dict.fromkeys(df["__space_key"]))

    # --- фильтры пользователя ---

    # 1) SPACES_FILTER
    if SPACES_FILTER:
        df = df[df["__space_key"].isin(SPACES_FILTER)]

    # Явная копия после фильтров, чтобы не ловить SettingWithCopyWarning
    df = df.copy()

    # 2) EXCLUDE_FLOORS
    if EXCLUDE_FLOORS:
        floors = set(int(x) for x in EXCLUDE_FLOORS)
        # пропускаем строки, где этаж распознан и входит в исключение
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
        print("⚠ После всех фильтров не осталось строк. YAML не будет сгенерирован.")
        print(f"  Всего строк в parquet:                 {total_rows}")
        print(f"  После базовой фильтрации (lamp+group): {rows_after_basic}")
        return "# Нет данных для генерации групп\n"

    # --- уникальности и статистика ---
    spaces_after_filters = list(dict.fromkeys(df["__space_key"]))
    groups_after_filters = list(dict.fromkeys(df["__group"]))
    excluded_spaces = [s for s in spaces_before_filters if s not in spaces_after_filters]

    print("📊 Статистика по данным для генерации lights_group:")
    print(f"  Версия:                                {__version__}")
    print(f"  Всего строк в parquet:                 {total_rows}")
    print(f"  После базовой фильтрации (lamp+group): {rows_after_basic}")
    print(f"  После всех фильтров (строк):           {rows_after_filters}")
    print(f"  Уникальных пространств:                {len(spaces_after_filters)}")
    print(f"  Уникальных групп:                      {len(groups_after_filters)}")
    if excluded_spaces:
        print(f"  Пространства, исключённые фильтрами:   {len(excluded_spaces)} шт")
    else:
        print("  Пространства, исключённые фильтрами:   нет")

    # --- генерация YAML ---
    lines: List[str] = []
    lines.append("lights_group:")
    lines.append("  light:")

    # Группируем: пространство -> группа
    for space_name, df_space in df.groupby("__space_key", sort=False):
        space_name_str = str(space_name).strip()
        if space_name_str:
            lines.append(f"  #Группы для {space_name_str}")

        for group_name, df_group in df_space.groupby("__group", sort=False):
            group_name_str = str(group_name).strip()
            if not group_name_str:
                continue

            lines.append("    - platform: group")
            lines.append(f'      name: "{group_name_str}"')
            lines.append(f"      unique_id: {group_name_str}")
            lines.append("      entities:")

            for lamp_raw in df_group["__lamp"]:
                lines.append(f"        - {normalize_lamp_id_to_entity(lamp_raw)}")

            # пустая строка между группами для читабельности
            lines.append("")

    # убираем лишний пустой хвост
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


# === ТОЧКА ВХОДА ===

def main() -> None:
    df = load_device_rows(DEVICE_ROWS_PARQUET)
    yaml_text = build_groups(df)

    # создаём папку если её нет
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    OUTPUT_PATH.write_text(yaml_text, encoding="utf-8")
    print(f"Готово! Файл с группами записан в: {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()