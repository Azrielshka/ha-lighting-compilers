import pandas as pd
from pathlib import Path

# === НАСТРОЙКИ ===

# Путь к исходному файлу Excel (относительно проекта)
EXCEL_PATH = Path("data/Таблица_устройств_Химки.xlsx")

# Имя листа: 0 - первый лист, либо строкой, например "Лист1"
SHEET_NAME = "DALI_Pusk"

# Буквы колонок, как в описании
COL_SPACE = "B"   # Имя пространства (комментарий)
COL_LAMP = "E"    # Имя лампы (например 4.1.1)
COL_GROUP_N = "N" # Имя группы (предпочтительно)
COL_GROUP_D = "D" # Имя группы (альтернатива, если N пустой)

# Файл результата
OUTPUT_PATH = Path("lights_group.yaml")

# Можно ограничить генерацию только несколькими пространствами:
# оставь пустой список, чтобы обрабатывать все
SPACES_FILTER = []  # например ["403 кабинет медицинский", "404 кабинет"]

# Исключить все пространства определённых этажей.
# Этаж определяется по первой цифре в названии пространства (колонка B):
# "403 кабинет ..." -> этаж 4, "112_с/у..." -> этаж 1
EXCLUDE_FLOORS = []  # например [4] чтобы исключить все кабинеты 4-го этажа

# Исключить пространства, в названии которых встречаются эти подстроки (без учёта регистра)
EXCLUDE_SPACE_CONTAINS = []  # например ["кабинет"]

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def normalize_lamp_name(raw: str) -> str:
    """
    Преобразовать имя лампы из таблицы в entity_id.
    Пример: "4.1.1" -> "light.l_4_1_1"
    """
    if not isinstance(raw, str):
        raw = str(raw)
    raw = raw.strip()
    code = raw.replace(".", "_")
    return f"light.l_{code}"


def load_table(path: Path, sheet_name=0) -> pd.DataFrame:
    """
    Загрузить Excel в DataFrame, всё как строки (dtype=str),
    чтобы не словить проблемы с числами/NaN.
    """
    df = pd.read_excel(path, sheet_name=sheet_name, dtype=str)
    return df


def build_groups(df: pd.DataFrame) -> str:
    """
    Собрать YAML-текст для lights_group из DataFrame.

    Логика:
    - Пространство (B) тянем вниз: пустые строки наследуют значение сверху.
    - Группу берём из N, если пусто — из D.
    - Фильтруем строки по:
        * SPACES_FILTER (если не пустой),
        * EXCLUDE_FLOORS (по первой цифре в названии пространства),
        * EXCLUDE_SPACE_CONTAINS (подстрока в названии пространства).
    - Группируем по пространству, внутри по имени группы.
    - Комментарий "#Группы для <пространство>" выводим один раз перед первой группой этого пространства.
    """

    original_cols = list(df.columns)
    total_rows = len(df)  # всего строк в исходной таблице

    def col_by_letter(letter: str) -> str:
        idx = ord(letter.upper()) - ord("A")
        try:
            return original_cols[idx]
        except IndexError:
            raise ValueError(f"В таблице нет колонки {letter}")

    col_space = col_by_letter(COL_SPACE)
    col_lamp = col_by_letter(COL_LAMP)
    col_group_n = col_by_letter(COL_GROUP_N)
    col_group_d = col_by_letter(COL_GROUP_D)

    # --- Приводим исходные данные к строкам + чистим NaN ---

    # Пространство (B)
    space_raw = df[col_space]
    df["__space"] = space_raw.fillna("").astype(str).str.strip()

    # Имя лампы (E)
    lamp_raw = df[col_lamp]
    df["__lamp"] = lamp_raw.fillna("").astype(str).str.strip()

    # Имя группы: сначала N, если пусто → D
    group_n = df[col_group_n].fillna("").astype(str).str.strip()
    group_d = df[col_group_d].fillna("").astype(str).str.strip()
    df["__group"] = group_n.where(group_n != "", group_d)
    df["__group"] = df["__group"].fillna("").astype(str).str.strip()

    # --- Тянем пространство вниз: пустые B наследуют значение сверху ---
    df["__space"] = df["__space"].replace("", pd.NA).ffill().fillna("")

    # --- Базовая фильтрация: нужны строки с непустой лампой и группой ---
    df = df[(df["__lamp"] != "") & (df["__group"] != "")]
    rows_after_basic = len(df)

    # Список пространств после базовой фильтрации
    spaces_before_filters = list(dict.fromkeys(df["__space"]))

    # Фильтр включения: если SPACES_FILTER не пустой — берём только эти пространства
    if SPACES_FILTER:
        df = df[df["__space"].isin(SPACES_FILTER)]

    # После фильтраций делаем явную копию, чтобы избежать SettingWithCopyWarning
    df = df.copy()

    # Фильтр по этажам: EXCLUDE_FLOORS
    # Этаж определяем по первой цифре в названии пространства: "403 ..." -> 4
    if EXCLUDE_FLOORS:
        floors_str = [str(f) for f in EXCLUDE_FLOORS]
        df["__floor_digit"] = (
            df["__space"]
            .str.extract(r"^\s*(\d)", expand=False)  # первая цифра в начале строки
            .fillna("")
        )
        df = df[~df["__floor_digit"].isin(floors_str)]

    # Фильтр по подстрокам в названии пространства: EXCLUDE_SPACE_CONTAINS
    if EXCLUDE_SPACE_CONTAINS:
        subs = [s.lower() for s in EXCLUDE_SPACE_CONTAINS]

        def space_allowed(space_name: str) -> bool:
            s = str(space_name).lower()
            return not any(sub in s for sub in subs)

        df = df[df["__space"].apply(space_allowed)]

    rows_after_filters = len(df)

    if df.empty:
        print("⚠ После всех фильтров не осталось строк. YAML не будет сгенерирован.")
        print(f"  Всего строк в таблице:             {total_rows}")
        print(f"  После базовой фильтрации (лампа+группа): {rows_after_basic}")
        return "# Нет данных для генерации групп\n"

    # --- Статистика по пространствам и группам после фильтров ---
    spaces_after_filters = list(dict.fromkeys(df["__space"]))
    groups_after_filters = list(dict.fromkeys(df["__group"]))

    excluded_spaces = [s for s in spaces_before_filters if s not in spaces_after_filters]

    print("📊 Статистика по данным для генерации групп:")
    print(f"  Всего строк в таблице:                  {total_rows}")
    print(f"  После базовой фильтрации (лампа+группа): {rows_after_basic}")
    print(f"  После всех фильтров (строк):            {rows_after_filters}")
    print(f"  Уникальных пространств (после фильтров): {len(spaces_after_filters)}")
    print(f"  Уникальных групп (после фильтров):      {len(groups_after_filters)}")
    print(f"  Пространства: Урезали (много, не печатаем)")
    print(f"  Группы:       Урезали (много, не печатаем)")

    # Пространства, которые не попали в итоговый YAML
    if excluded_spaces:
        max_excluded_show = 50
        print(f"  Пространства, исключённые фильтрами ({len(excluded_spaces)} шт):")
        if len(excluded_spaces) <= max_excluded_show:
            print("    " + ", ".join(str(s) for s in excluded_spaces))
        else:
            head = ", ".join(str(s) for s in excluded_spaces[:max_excluded_show])
            print("    " + head + f", ... (+{len(excluded_spaces) - max_excluded_show} ещё)")
    else:
        print("  Пространства, исключённые фильтрами: нет")

    # --- Генерация YAML ---

    lines = []
    lines.append("lights_group:")
    lines.append("  light:")

    # Группируем СПЕРВА по пространству, затем по группе (сохраняем порядок)
    for space_name, df_space in df.groupby("__space", sort=False):
        space_name = str(space_name).strip()

        # Комментарий только ОДИН раз на пространство
        if space_name:
            lines.append(f"  #Группы для {space_name}")

        # Внутри пространства — по имени группы
        for group_name, df_group in df_space.groupby("__group", sort=False):
            group_name_str = str(group_name).strip()
            if not group_name_str:
                continue

            lines.append("    - platform: group")
            lines.append(f'      name: "{group_name_str}"')
            lines.append(f"      unique_id: {group_name_str}")
            lines.append("      entities:")

            for lamp_raw in df_group["__lamp"]:
                entity_id = normalize_lamp_name(lamp_raw)
                lines.append(f"        - {entity_id}")

            # пустая строка между группами для читабельности
            lines.append("")

    # убираем возможный лишний пустой хвост
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"

# === ТОЧКА ВХОДА ===

def main():
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"Файл не найден: {EXCEL_PATH}")

    df = load_table(EXCEL_PATH, sheet_name=SHEET_NAME)
    yaml_text = build_groups(df)

    OUTPUT_PATH.write_text(yaml_text, encoding="utf-8")
    print(f"Готово! Файл с группами записан в: {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
