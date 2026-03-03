import warnings
from pathlib import Path

import pandas as pd

# Если warning от openpyxl не мешает — этот блок можно удалить
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    module="openpyxl.worksheet._reader"
)

# === НАСТРОЙКИ ===

# Корень проекта (на уровень выше папки scripts)
BASE_DIR = Path(__file__).resolve().parent.parent

# Таблица лежит в папке data в корне проекта
EXCEL_PATH = BASE_DIR / "data" / "Таблица_устройств_Химки.xlsx"

# Имя листа: 0 - первый лист, либо строкой, например "Лист1"
SHEET_NAME = 0

# Буквы колонок в таблице
COL_SPACE = "B"   # Имя пространства (комментарий)
COL_LAMP = "E"    # Имя лампы (нам тут почти не нужен, но оставим для симметрии)
COL_GROUP_N = "N" # Имя подгруппы (предпочтительно)
COL_GROUP_D = "D" # Имя подгруппы (альтернатива, если N пустой)

# Выходной YAML кладём в корень проекта (как у тебя на скриншоте)
OUTPUT_PATH = BASE_DIR / "lights_general_groups.yaml"   # для generate_general_groups.py

# Фильтры, как в предыдущем скрипте

# Ограничить генерацию только перечисленными пространствами (по колонке B)
SPACES_FILTER = []  # например ["403 кабинет медицинский", "404 кабинет"]

# Исключить все пространства определённых этажей.
# Этаж определяется по первой цифре в названии пространства (колонка B):
# "403 кабинет ..." -> этаж 4, "112_с/у..." -> этаж 1
EXCLUDE_FLOORS = []  # например [4] чтобы исключить все 4-й этаж

# Исключить пространства, в названии которых встречаются эти подстроки (без учёта регистра)
EXCLUDE_SPACE_CONTAINS = []  # например ["кабинет"]


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def transliterate_ru_to_en(text: str) -> str:
    """
    Очень простой транслит кириллицы в латиницу для формирования id.
    Не претендует на идеальность — при необходимости можно поправить под себя.
    """
    mapping = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
        "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
        "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch",
        "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
        " ": "_", "-": "_", "/": "_",
    }
    out = []
    for ch in text.lower():
        if ch in mapping:
            out.append(mapping[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def make_general_group_name(space_name: str) -> str:
    """
    Из имени пространства (колонка B) делаем РУССКОЕ name для общей группы.

    Правило:
      "<номер>_<остальное>" -> "<номер> Общий <остальное с пробелами>"

    Примеры:
      "113_учебный_кабинет" -> "113 Общий учебный кабинет"
      "171_лестница"        -> "171 Общий лестница"
      "126_с/у"             -> "126 Общий с/у"
    """
    raw = str(space_name).strip()
    if not raw:
        return "Общий"

    import re

    # Пытаемся отдельно вытащить номер в начале
    m = re.match(r"^\s*(\d+)[_ ]*(.*)$", raw)
    if m:
        room = m.group(1)              # "113"
        rest = m.group(2).strip()      # "учебный_кабинет" или "с/у" и т.п.
    else:
        room = ""
        rest = raw

    # В остатке заменяем "_" на пробелы
    rest_clean = rest.replace("_", " ").strip()

    if room:
        if rest_clean:
            # "113 Общий учебный кабинет"
            return f"{room} Общий {rest_clean}"
        else:
            # Если вдруг нет хвоста: "113 Общий"
            return f"{room} Общий"
    else:
        # Если нет номера в начале
        if rest_clean:
            return f"Общий {rest_clean}"
        else:
            return "Общий"



def load_table(path: Path, sheet_name=0) -> pd.DataFrame:
    """
    Загрузить Excel в DataFrame.
    """
    df = pd.read_excel(path, sheet_name=sheet_name, dtype=str)
    return df


def build_general_groups(df: pd.DataFrame) -> str:
    """
    Собрать YAML-текст с общими группами по пространствам.

    На входе: таблица с колонками B (пространство), N/D (подгруппа).
    На выходе: для каждого пространства — одна общая группа,
    включающая все подгруппы (light.<значение N/D>).
    """

    original_cols = list(df.columns)
    total_rows = len(df)

    def col_by_letter(letter: str) -> str:
        idx = ord(letter.upper()) - ord("A")
        try:
            return original_cols[idx]
        except IndexError:
            raise ValueError(f"В таблице нет колонки {letter}")

    col_space = col_by_letter(COL_SPACE)
    col_group_n = col_by_letter(COL_GROUP_N)
    col_group_d = col_by_letter(COL_GROUP_D)

    # --- Подготовка данных ---

    # Пространство (B)
    space_raw = df[col_space]
    df["__space"] = space_raw.fillna("").astype(str).str.strip()

    # Имя подгруппы: сначала N, если пусто — D
    group_n = df[col_group_n].fillna("").astype(str).str.strip()
    group_d = df[col_group_d].fillna("").astype(str).str.strip()
    df["__group"] = group_n.where(group_n != "", group_d)
    df["__group"] = df["__group"].fillna("").astype(str).str.strip()

    # Тянем пространство вниз: пустые B наследуют значение сверху
    df["__space"] = df["__space"].replace("", pd.NA).ffill().fillna("")

    # Нужны только строки, где есть пространство и группа
    df = df[(df["__space"] != "") & (df["__group"] != "")]
    rows_after_basic = len(df)

    # Список пространств после базовой фильтрации
    spaces_before_filters = list(dict.fromkeys(df["__space"]))

    # Фильтр включения по SPACES_FILTER
    if SPACES_FILTER:
        df = df[df["__space"].isin(SPACES_FILTER)]

    df = df.copy()  # чтобы не ловить SettingWithCopyWarning

    # Фильтр по этажам: EXCLUDE_FLOORS (первая цифра в начале имени пространства)
    if EXCLUDE_FLOORS:
        floors_str = [str(f) for f in EXCLUDE_FLOORS]
        df["__floor_digit"] = (
            df["__space"]
            .str.extract(r"^\s*(\d)", expand=False)
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
        print("⚠ После всех фильтров не осталось строк. Общие группы не будут сгенерированы.")
        print(f"  Всего строк в таблице:             {total_rows}")
        print(f"  После базовой фильтрации:          {rows_after_basic}")
        return "# Нет данных для генерации общих групп\n"

    # Нам нужны уникальные пары (пространство, подгруппа)
    df_pairs = df[["__space", "__group"]].drop_duplicates()

    # Статистика
    spaces_after_filters = list(dict.fromkeys(df_pairs["__space"]))
    groups_after_filters = list(dict.fromkeys(df_pairs["__group"]))
    excluded_spaces = [s for s in spaces_before_filters if s not in spaces_after_filters]

    print("📊 Статистика по общим группам:")
    print(f"  Всего строк в таблице:                  {total_rows}")
    print(f"  После базовой фильтрации (space+group): {rows_after_basic}")
    print(f"  После всех фильтров (строк):            {rows_after_filters}")
    print(f"  Уникальных пространств (после фильтров): {len(spaces_after_filters)}")
    print(f"  Уникальных подгрупп (после фильтров):    {len(groups_after_filters)}")
    if excluded_spaces:
        print(f"  Пространства, исключённые фильтрами: {len(excluded_spaces)} шт (список не печатаем, чтобы не захламлять вывод)")
    else:
        print("  Пространства, исключённые фильтрами: нет")

    # --- Генерация YAML ---

    lines = []
    lines.append("lights_general_group:")
    lines.append("  light:")

    # Группируем по пространству (в порядке появления)
    for space_name, df_space in df_pairs.groupby("__space", sort=False):
        space_name_str = str(space_name).strip()
        if not space_name_str:
            continue

        # Комментарий к блоку
        lines.append(f"  #Общая группа для {space_name_str}")

        # Русское имя общей группы для name/unique_id
        general_name = make_general_group_name(space_name_str)

        # Одна общая группа на пространство
        lines.append("    - platform: group")
        lines.append(f'      name: "{general_name}"')
        lines.append(f'      unique_id: "{general_name}"')
        lines.append("      entities:")


        # Все подгруппы этого пространства
        for group_name in df_space["__group"]:
            group_name_str = str(group_name).strip()
            if not group_name_str:
                continue
            lines.append(f"        - light.{group_name_str}")

        # пустая строка между общими группами
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
    yaml_text = build_general_groups(df)

    OUTPUT_PATH.write_text(yaml_text, encoding="utf-8")
    print(f"Готово! Файл с общими группами записан в: {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
