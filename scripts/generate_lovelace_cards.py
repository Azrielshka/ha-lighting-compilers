# generate_lovelace_cards.py
# ------------------------------------------------------------
# Генератор Lovelace-карточек (YAML-вставки) на основе:
# 1) Excel-таблицы устройств (пространства / группы / датчики)
# 2) Файла-глоссария с образцовыми карточками (txt с {{ ... }} блоками)
#
# Выход:
#   TXT-файл, где для каждого помещения будет вставка:
#       {{
#       ...yaml карточки...
#       }}
#
# Исправления:
# 1) "лестница" -> lestnitsa (транслит): 'ц' => 'ts'
# 2) Отступы entity сохраняем как в шаблоне (не ломаем YAML)
# 3) sensor_id из G нормализуем: точки '.' -> '_' (1.3.5 -> 1_3_5)
#
# Зависимости:
#   pip install pandas openpyxl
# ------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections import Counter
import re
import pandas as pd


# -----------------------------
# НАСТРОЙКИ / ПУТИ
# -----------------------------

EXCEL_PATH = Path("data/Таблица_устройств_Химки.xlsx")
GLOSSARY_PATH = Path("data/Глоссарий карточек.txt")
OUTPUT_TXT = Path("lovelace_cards_generated.txt")

SHEET_NAME = 0

# Буквы колонок
COL_SPACE = "B"      # Помещение / пространство
COL_SENSOR_ID = "G"  # Идентификатор датчика (например 1_22_0 или 1.3.5)
COL_GROUP_N = "N"    # Имя группы (предпочтительно)
COL_GROUP_D = "D"    # Имя группы (если N пустой)

# -----------------------------
# ФИЛЬТРЫ
# -----------------------------

SPACES_FILTER: list[str] = []       # точный список помещений B
INCLUDE_FLOORS: list[int] = [1]      # например [1, 2]
EXCLUDE_FLOORS: list[int] = []      # например [4]
INCLUDE_SPACE_TYPES: list[str] = [] # corridor, stairs, cabinet, tambour, su


# -----------------------------
# КЛАССИФИКАЦИЯ ПОМЕЩЕНИЙ
# -----------------------------

TYPE_RULES = {
    "corridor": ["коридор", "вестибюль", "загрузочная"],
    "stairs": ["лестница", "лестничная"],
    "cabinet": ["кабинет", "лаб", "лаборатория", "кабин", "класс"],
    "tambour": ["тамбур"],
    "su": ["с/у", "су", "умывальная", "туалет", "комната", "раздевалка"],
}

TYPE_TITLE_RU = {
    "corridor": "Коридор",
    "stairs": "Лестница",
    "cabinet": "Кабинет",
    "tambour": "Тамбур",
    "su": "С/у",
}

TYPE_EMOJI = {
    "corridor": "🏰",
    "stairs": "🌈",
    "cabinet": "🏢",
    "tambour": "🏛️",
    "su": "🚽",
}


# -----------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# -----------------------------

def col_by_letter(df: pd.DataFrame, letter: str) -> str:
    cols = list(df.columns)
    idx = ord(letter.upper()) - ord("A")
    if idx < 0 or idx >= len(cols):
        raise ValueError(f"В таблице нет колонки {letter}")
    return cols[idx]


def normalize_space_name(s: str) -> str:
    return str(s).strip()


def extract_room_number(space_name: str) -> int | None:
    m = re.match(r"^\s*(\d{2,4})", str(space_name))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def extract_floor(space_name: str) -> int | None:
    room = extract_room_number(space_name)
    if room is None:
        return None
    return room // 100


def detect_space_type(space_name: str) -> str | None:
    s = str(space_name).lower()
    for t, keys in TYPE_RULES.items():
        if any(k in s for k in keys):
            return t
    return None


def normalize_sensor_id(sensor_id: str) -> str:
    """
    Приводим идентификатор из колонки G к виду для entity_id:
      - точки -> подчёркивания
      - пробелы убираем
    Пример: "1.3.5" -> "1_3_5"
    """
    sid = str(sensor_id).strip()
    sid = sid.replace(".", "_")
    sid = re.sub(r"\s+", "", sid)
    sid = re.sub(r"_+", "_", sid).strip("_")
    return sid


def slugify_ru_to_en(text: str) -> str:
    """
    Приближенный slugify (как в HA):
    - русские -> латиница (упрощённый транслит)
    - пробелы/символы -> underscore

    ВАЖНОЕ ИСПРАВЛЕНИЕ:
      'ц' => 'ts' (иначе "лестница" получалось "lestnica", а нужно "lestnitsa")
    """
    mapping = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
        "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
        "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "h",
        "ц": "ts",  # <-- FIX
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
        " ": "_", "-": "_", "/": "_", ".": "_",
    }
    out = []
    for ch in str(text).lower():
        if ch in mapping:
            out.append(mapping[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def general_light_entity_from_space(space_name: str) -> str | None:
    """
    Формируем entity_id общей группы помещения:
      "403_кабинет_медиц" -> light.403_obshchii_kabinet_medits
      "210_лестница"      -> light.210_obshchii_lestnitsa
    """
    space = normalize_space_name(space_name)
    room = extract_room_number(space)
    if room is None:
        return None
    # хвост после номера
    tail = re.sub(r"^\s*\d+\s*[_ ]*", "", space).strip()
    tail = tail.replace("_", " ").strip()
    # --- ТУТ вставляем точечные исключения ---
    tail_lower = tail.lower()
    # точечные словари-исключения под твой нейминг
    tail_lower = tail_lower.replace("вестибюль", "vestibiul")
    tail_lower = tail_lower.replace("вестибюля", "vestibiul")
    tail_lower = tail_lower.replace("вестибюле", "vestibiul")
    tail_lower = tail_lower.replace("умывальная", "umyvalnaia")
    tail_lower = tail_lower.replace("загрузочная", "zagruzochnaia")
    tail_slug = slugify_ru_to_en(tail_lower) if tail_lower else ""

    if tail_slug:
        return f"light.{room}_obshchii_{tail_slug}"
    return f"light.{room}_obshchii"


def ms_sensor_entity(sensor_id: str) -> str:
    sid = normalize_sensor_id(sensor_id)
    return f"sensor.ms_{sid}_state"


def il_sensor_entity(sensor_id: str) -> str:
    sid = normalize_sensor_id(sensor_id)
    return f"sensor.il_{sid}_state"


def il_switch_entity(sensor_id: str) -> str:
    sid = normalize_sensor_id(sensor_id)
    return f"switch.il_{sid}_sensor_enable"


def choose_template(space_type: str, group_count: int, templates: dict[tuple[str,int], Template]) -> tuple[str,int] | None:
    # 1) точное совпадение
    if (space_type, group_count) in templates:
        return (space_type, group_count)

    # 2) ближайший по доступным вариантам этого типа
    available = sorted([n for (t, n) in templates.keys() if t == space_type])
    if not available:
        return None

    nearest = min(available, key=lambda n: abs(n - group_count))
    return (space_type, nearest)



def replace_in_order(text: str, pattern: str, replacements: list[str]) -> str:
    it = iter(replacements)

    def repl(m: re.Match) -> str:
        try:
            return next(it)
        except StopIteration:
            return m.group(0)

    return re.sub(pattern, repl, text)


# -----------------------------
# ГЛОССАРИЙ -> ШАБЛОНЫ
# -----------------------------

@dataclass
class Template:
    space_type: str
    group_variant: int
    raw: str  # YAML внутри карточки (между {{ и }})


def parse_glossary_templates(glossary_text: str) -> dict[tuple[str, int], Template]:
    """
    Парсим глоссарий только по строкам "{{" и "}}", чтобы НЕ ловить Jinja {{...}} внутри markdown.
    """
    lines = glossary_text.splitlines()

    def type_from_line(line: str) -> str | None:
        l = line.lower().strip()
        if l.startswith("1."):
            return "corridor"
        if l.startswith("2."):
            return "stairs"
        if l.startswith("3."):
            return "cabinet"
        if l.startswith("4."):
            return "tambour"
        if l.startswith("5."):
            return "su"
        return None

    templates: dict[tuple[str, int], Template] = {}
    current_type: str | None = None
    pending_variant: int | None = None

    in_block = False
    block_buf: list[str] = []

    for ln in lines:
        t = type_from_line(ln)
        if t:
            current_type = t

        m = re.search(r"на\s+(\d+)\s+групп", ln.lower())
        if m and current_type:
            pending_variant = int(m.group(1))
            continue

        if ln.strip() == "{{" and not in_block:
            in_block = True
            block_buf = []
            continue

        if ln.strip() == "}}" and in_block:
            in_block = False
            raw_yaml = "\n".join(block_buf).strip()
            if current_type and pending_variant is not None:
                templates[(current_type, pending_variant)] = Template(
                    space_type=current_type,
                    group_variant=pending_variant,
                    raw=raw_yaml
                )
            block_buf = []
            continue

        if in_block:
            block_buf.append(ln)

    return templates


# -----------------------------
# EXCEL -> ДАННЫЕ ПО ПОМЕЩЕНИЯМ
# -----------------------------

@dataclass
class SpaceInfo:
    space_name: str
    space_type: str
    room: int
    floor: int
    group_count: int
    group_ids_ordered: list[str]
    sensor_ids_ordered: list[str]


def load_spaces_from_excel(df: pd.DataFrame) -> tuple[list[SpaceInfo], list[str]]:
    """
    Количество групп = число уникальных group_id в помещении (N если есть, иначе D).
    Датчики:
      для каждого group_id берём ПЕРВЫЙ встретившийся sensor_id (G),
      затем формируем список в порядке групп.
    """
    col_space = col_by_letter(df, COL_SPACE)
    col_sensor = col_by_letter(df, COL_SENSOR_ID)
    col_group_n = col_by_letter(df, COL_GROUP_N)
    col_group_d = col_by_letter(df, COL_GROUP_D)

    df["__space"] = df[col_space].fillna("").astype(str).str.strip()
    df["__sensor_id"] = df[col_sensor].fillna("").astype(str).str.strip()

    g_n = df[col_group_n].fillna("").astype(str).str.strip()
    g_d = df[col_group_d].fillna("").astype(str).str.strip()
    df["__group_id"] = g_n.where(g_n != "", g_d).fillna("").astype(str).str.strip()

    df["__space"] = df["__space"].replace("", pd.NA).ffill().fillna("")

    df2 = df[df["__group_id"] != ""].copy()
    spaces_ordered = list(dict.fromkeys(df2["__space"]))

    result: list[SpaceInfo] = []
    skipped: list[str] = []

    for space_name in spaces_ordered:
        sp = normalize_space_name(space_name)
        if not sp:
            continue

        if SPACES_FILTER and sp not in SPACES_FILTER:
            continue

        room = extract_room_number(sp)
        floor = extract_floor(sp) if room is not None else None
        stype = detect_space_type(sp)

        if room is None or floor is None or stype is None:
            skipped.append(sp)
            continue

        if INCLUDE_FLOORS and floor not in INCLUDE_FLOORS:
            continue
        if EXCLUDE_FLOORS and floor in EXCLUDE_FLOORS:
            continue
        if INCLUDE_SPACE_TYPES and stype not in INCLUDE_SPACE_TYPES:
            continue

        df_sp = df2[df2["__space"] == sp].copy()

        # группы по порядку появления
        group_ids_ordered: list[str] = []
        for gid in df_sp["__group_id"].tolist():
            gid = str(gid).strip()
            if gid and gid.lower() != "nan" and gid not in group_ids_ordered:
                group_ids_ordered.append(gid)

        group_count = max(1, min(len(group_ids_ordered), 12))

        # первый датчик на группу
        sensor_by_group: dict[str, str] = {}
        for _, row in df_sp.iterrows():
            gid = str(row["__group_id"]).strip()
            sid = str(row["__sensor_id"]).strip()
            if not gid or gid.lower() == "nan":
                continue
            if not sid or sid.lower() == "nan":
                continue
            if gid not in sensor_by_group:
                sensor_by_group[gid] = sid

        sensor_ids_ordered = [sensor_by_group.get(gid, "") for gid in group_ids_ordered]

        result.append(SpaceInfo(
            space_name=sp,
            space_type=stype,
            room=room,
            floor=floor,
            group_count=group_count,
            group_ids_ordered=group_ids_ordered,
            sensor_ids_ordered=sensor_ids_ordered,
        ))

    return result, skipped


# -----------------------------
# РЕНДЕР ШАБЛОНА -> КАРТОЧКА
# -----------------------------

def render_card_from_template(tpl: Template, space: SpaceInfo) -> str:
    """
    Подстановка:
      - heading
      - entity общей группы помещения (с сохранением отступа!)
      - подгруппы (заменяем номер помещения)
      - датчики ms/il/switch.il (точки -> _)
    """
    yaml_text = tpl.raw

    # heading
    emoji = TYPE_EMOJI.get(space.space_type, "💡")
    title_ru = TYPE_TITLE_RU.get(space.space_type, "Помещение")

    tail = re.sub(r"^\s*\d+\s*[_ ]*", "", space.space_name).replace("_", " ").strip()
    heading_value = f"{emoji} {title_ru} {space.room}" + (f" — {tail}" if tail else "")

    yaml_text = re.sub(
        r"(?m)^(\s*)heading:\s*.*$",
        fr"\1heading: {heading_value}",
        yaml_text,
        count=1
    )

    # entity общей группы помещения — ВАЖНО: сохраняем исходный отступ (\1)
    general_entity = general_light_entity_from_space(space.space_name)
    if general_entity:
        yaml_text = re.sub(
            r"(?m)^(\s*)entity:\s*light\.\d+_obshchii_[a-z0-9_]+",
            fr"\1entity: {general_entity}",
            yaml_text,
            count=1
        )
    # 2b) Для тамбура: поправить name: у tile'а с общей группой
    # В шаблоне тамбура name задаётся отдельно и иначе остаётся "Тамбур 136".
    # Меняем name только рядом с entity общей группы, чтобы не портить другие name.
    if space.space_type == "tambour":
        # базовая подпись без хвоста (как в твоём примере)
        tile_name = f"Тамбур {space.room}"
        # Ищем блок, где встречается entity: light.<room>_obshchii_... и следующий name:
        # (работает, потому что у тебя name находится ниже entity в этом tile)
        yaml_text = re.sub(
            rf"(?ms)^(\s*entity:\s*{re.escape(general_entity)}\s*.*?\n)(\s*name:\s*).*$",
            rf"\1\2{tile_name}",
            yaml_text,
            count=1
        )

    # подгруппы: light.210_0 -> light.<room>_0
    yaml_text = re.sub(r"light\.\d+_(\d+)", fr"light.{space.room}_\1", yaml_text)

    # датчики в порядке групп; sensor_id нормализуем ('.' -> '_')
    ms_list = [ms_sensor_entity(sid) for sid in space.sensor_ids_ordered if sid]
    il_list = [il_sensor_entity(sid) for sid in space.sensor_ids_ordered if sid]
    sw_list = [il_switch_entity(sid) for sid in space.sensor_ids_ordered if sid]

    yaml_text = replace_in_order(yaml_text, r"sensor\.ms_[0-9_\.]+_state", ms_list)
    yaml_text = replace_in_order(yaml_text, r"sensor\.il_[0-9_\.]+_state", il_list)
    yaml_text = replace_in_order(yaml_text, r"switch\.il_[0-9_\.]+_sensor_enable", sw_list)

    return yaml_text.strip()


# -----------------------------
# ВЫХОД + ЛОГ
# -----------------------------

def build_output_txt(
    templates: dict[tuple[str, int], Template],
    spaces: list[SpaceInfo]
) -> tuple[str, list[str]]:
    """
    Собираем итоговый TXT с блоками {{ ... }} для каждого помещения.

    Выбор шаблона:
      - используем внешнюю функцию choose_template(space_type, group_count, templates)
      - она пытается взять точный шаблон (тип, N), иначе выбирает ближайший по N
      - автомасштабирования НЕТ (как договорились)

    Возвращаем:
      - текст файла
      - список помещений, которые пропущены (нет шаблонов для их типа)
    """
    out_lines: list[str] = []
    skipped_no_template: list[str] = []

    for sp in spaces:
        # ✅ ВМЕСТО pick_template_key(...) используем choose_template(...)
        key = choose_template(sp.space_type, sp.group_count, templates)
        if not key:
            skipped_no_template.append(sp.space_name)
            continue

        tpl = templates[key]

        # Рендер карточки (подстановка room, датчиков и т.п.)
        card_yaml = render_card_from_template(tpl, sp)

        # Границы карточки как в глоссарии
        out_lines.append(
            f"### {sp.space_name}  (тип={sp.space_type}, групп={sp.group_count}, шаблон={key[0]}:{key[1]})"
        )
        out_lines.append("{{")
        out_lines.append(card_yaml)
        out_lines.append("}}")
        out_lines.append("")  # пустая строка между карточками

    return "\n".join(out_lines).rstrip() + "\n", skipped_no_template



def log_summary(spaces: list[SpaceInfo], skipped_raw: list[str], skipped_no_template: list[str],
                templates_found: dict[tuple[str, int], Template]) -> None:
    print("📚 Шаблоны из глоссария найдены:")
    for k in sorted(templates_found.keys()):
        print(f"  - {k[0]}: {k[1]} групп")

    cnt_by_type = Counter([s.space_type for s in spaces])
    print("\n📊 Помещения, попавшие в обработку (после фильтров):")
    for t, c in cnt_by_type.items():
        print(f"  - {t}: {c}")

    if skipped_raw:
        print("\n⚠ Пропущенные помещения (не смогли определить номер/тип или нет данных):")
        print(f"  Всего: {len(skipped_raw)}")
        for s in skipped_raw[:50]:
            print(f"   - {s}")
        if len(skipped_raw) > 50:
            print(f"   ... (+{len(skipped_raw)-50} ещё)")

    if skipped_no_template:
        print("\n⚠ Пропущенные помещения (нет подходящего шаблона в глоссарии):")
        print(f"  Всего: {len(skipped_no_template)}")
        for s in skipped_no_template[:50]:
            print(f"   - {s}")
        if len(skipped_no_template) > 50:
            print(f"   ... (+{len(skipped_no_template)-50} ещё)")


def main():
    if not GLOSSARY_PATH.exists():
        raise FileNotFoundError(f"Глоссарий не найден: {GLOSSARY_PATH}")

    glossary_text = GLOSSARY_PATH.read_text(encoding="utf-8")
    templates = parse_glossary_templates(glossary_text)

    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"Excel не найден: {EXCEL_PATH}")

    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, dtype=str)

    spaces, skipped_raw = load_spaces_from_excel(df)

    txt, skipped_no_template = build_output_txt(templates, spaces)
    OUTPUT_TXT.write_text(txt, encoding="utf-8")

    log_summary(spaces, skipped_raw, skipped_no_template, templates)
    print(f"\n✅ Готово! Файл карточек записан в: {OUTPUT_TXT.resolve()}")


if __name__ == "__main__":
    main()
