# -*- coding: utf-8 -*-
"""
canon.py
Общий "канон" проекта: ключи, правила и настройки, которые должны быть едиными для всех скриптов.

Зачем нужен файл:
- чтобы не копировать маппинги и константы в каждом скрипте
- чтобы при изменении правила оно менялось в одном месте

Модель данных v2 описана в docs/internal/data_model.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple

from scripts._lib.naming import slugify_room


# Версия схемы нормализованных данных (для normalized_meta.json).
# v3: колонка «Блок», тип hall, датасет units (единицы обслуживания).
NORMALIZED_SCHEMA_VERSION: int = 3


# ============================================================
# ДОМЕНЫ И ПРЕФИКСЫ HOME ASSISTANT
# ============================================================

HA_LIGHT_DOMAIN: str = "light"
HA_SENSOR_DOMAIN: str = "sensor"
HA_EVENT_DOMAIN: str = "event"

# Префиксы, которыми сторонняя интеграция именует сущности по адресу DALI.
LAMP_PREFIX: str = "l"
SENSOR_MOTION_PREFIX: str = "ms"
SENSOR_ILLUMINANCE_PREFIX: str = "il"
PANEL_PREFIX: str = "kp"


# ============================================================
# ТИПЫ ПОМЕЩЕНИЙ
# ============================================================

# Ключи типов помещений (колонка "Тип помещения"), нормализованные к нижнему регистру.
# Должны совпадать с templates/manifest.yaml.
ALLOWED_SPACE_TYPES: Set[str] = {
    "class",
    "korridor",   # именно так, не "corridor" — решение заказчика
    "recreation",
    "zal",
    "special",
    "hall",
}

# Типы, которые считаем "техническими" для отдельных групп на этаж (tex_floor_<n>).
# Проходные пространства, где никто не находится постоянно.
# Согласовано с владельцем 2026-07-13.
#
# За рамками: class (парты, люди сидят) и zal (управляется только с панелей).
TECHNICAL_SPACE_TYPES: Set[str] = {"korridor", "special", "recreation"}


def normalize_space_type(raw: object) -> Optional[str]:
    """
    Привести тип помещения к каноническому ключу: обрезать пробелы, снизить регистр.

    Пустое значение -> None (помещение без типа; это предупреждение, не ошибка).
    Неизвестный ключ возвращается как есть — валидацию делает validate_excel.py.
    """
    if raw is None:
        return None

    s = str(raw).strip().lower()
    return s or None


# ============================================================
# АДРЕСА DALI
# ============================================================

# Адрес устройства: X.Y.Z, где X — этаж, Y — шина, Z — проектный номер.
ADDR_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Токены, означающие "устройства по проекту нет".
# Пустая ячейка — это НЕ то же самое: она означает "в этой строке ничего не сказано".
NONE_TOKENS: Set[str] = {"none", "нет", "-", "–", "—"}


@dataclass(frozen=True)
class Addr:
    """Разобранный адрес DALI."""
    floor: int
    bus: int
    num: int

    @property
    def slug(self) -> str:
        """Часть entity_id: 1.20.15 -> 1_20_15."""
        return f"{self.floor}_{self.bus}_{self.num}"

    def __str__(self) -> str:
        return f"{self.floor}.{self.bus}.{self.num}"


def is_blank(raw: object) -> bool:
    """Пустая ячейка: None, NaN или строка из пробелов."""
    if raw is None:
        return True
    # pd.NA / float('nan') — сравнение с собой даёт False только у NaN,
    # но pd.NA бросает исключение при bool(), поэтому идём через str().
    s = str(raw).strip()
    return s == "" or s.lower() in {"nan", "<na>", "nat"}


def is_none_token(raw: object) -> bool:
    """Ячейка означает 'устройства нет' (None / нет / - / – / —)."""
    if is_blank(raw):
        return False
    return str(raw).strip().lower() in NONE_TOKENS


def parse_addr(raw: object) -> Addr:
    """
    Разобрать адрес 'X.Y.Z'.

    Бросает ValueError, если формат не подходит. Вызывающий код решает,
    ошибка это или предупреждение.
    """
    s = "" if raw is None else str(raw).strip()

    if not ADDR_RE.match(s):
        raise ValueError(f"адрес не в формате X.Y.Z: {s!r}")

    floor, bus, num = (int(p) for p in s.split("."))
    return Addr(floor=floor, bus=bus, num=num)


# ============================================================
# ПРАВИЛА НЕЙМИНГА СУЩНОСТЕЙ
# ============================================================
#
# Сущности ламп, датчиков и панелей создаёт сторонняя интеграция —
# мы их только предсказываем по адресу. Имена гарантированы заказчиком.
#
# Группы (зоны и общие группы помещений) создаём мы сами.

def _addr_slug(raw: object) -> str:
    """Адрес -> часть entity_id. Принимает и Addr, и сырую строку."""
    if isinstance(raw, Addr):
        return raw.slug
    return parse_addr(raw).slug


def lamp_entity(addr: object) -> str:
    """1.20.15 -> light.l_1_20_15"""
    return f"{HA_LIGHT_DOMAIN}.{LAMP_PREFIX}_{_addr_slug(addr)}"


def sensor_motion_entity(addr: object) -> str:
    """1.20.3 -> sensor.ms_1_20_3"""
    return f"{HA_SENSOR_DOMAIN}.{SENSOR_MOTION_PREFIX}_{_addr_slug(addr)}"


def sensor_illuminance_entity(addr: object) -> str:
    """1.20.3 -> sensor.il_1_20_3 (у каждого датчика есть обе сущности)"""
    return f"{HA_SENSOR_DOMAIN}.{SENSOR_ILLUMINANCE_PREFIX}_{_addr_slug(addr)}"


def panel_entity(addr: object) -> str:
    """1.1.1 -> event.kp_1_1_1"""
    return f"{HA_EVENT_DOMAIN}.{PANEL_PREFIX}_{_addr_slug(addr)}"


def zone_light_entity(group_id: str) -> str:
    """Группа (зона) помещения: 102_1 -> light.102_1"""
    return f"{HA_LIGHT_DOMAIN}.{str(group_id).strip()}"


@dataclass(frozen=True)
class GeneralLightNamingRule:
    """
    Правило формирования entity_id общего света по room_slug.
    По договорённости: light.<room_slug>_obshchii

    Если позже понадобится особая логика/исключения — меняем тут, а не в генераторах.
    """
    suffix: str = "_obshchii"

    def build(self, room_slug: str) -> str:
        return f"{HA_LIGHT_DOMAIN}.{room_slug}{self.suffix}"


GENERAL_LIGHT_RULE = GeneralLightNamingRule()


def general_light_entity(room_slug: str) -> str:
    """104_metodicheskii_kabinet -> light.104_metodicheskii_kabinet_obshchii"""
    return GENERAL_LIGHT_RULE.build(room_slug)


# ============================================================
# РЕЕСТРЫ HOME ASSISTANT: ПРОСТРАНСТВА И ЭТАЖИ
# ============================================================
#
# Areas и Floors — не YAML-конфигурация, а записи в реестрах HA.
# Создаются по WebSocket API на шаге деплоя.
#
# Имя пространства берём ПРЯМО из таблицы (колонка «Название помещения»):
# проектировщик уже написал его по-человечески, восстанавливать из транслита
# нечего. Транслит идёт в алиасы — чтобы в HA искалось и так, и так.

def space_label(space: str) -> str:
    """Помещение для показа человеку: «103_Вестибюль» -> «103 Вестибюль».

    Одно правило на весь проект. Им подписаны и заголовок карточки, и опции
    input_select навигации, и ключи карты «имя → слаг» в кнопке перехода.
    Разъедутся — навигация молча сломается: выбрал помещение, а кнопка говорит
    «выберите помещение». Поэтому правило живёт здесь, а не в генераторах.
    """
    return str(space).replace("_", " ").strip()


def area_name(space: str) -> str:
    """Имя Area = название помещения из таблицы: «103_Вестибюль»."""
    return str(space).strip()


def area_aliases(room_slug: str) -> list[str]:
    """Алиасы Area: транслит, чтобы помещение находилось и по нему."""
    slug = str(room_slug).strip()
    return [slug] if slug else []


def floor_name(floor: int) -> str:
    """Имя Floor в реестре HA: «1 этаж»."""
    return f"{int(floor)} этаж"


def floor_icon(floor: int) -> str:
    """
    Иконка этажа в HA: mdi:home-floor-1 ... mdi:home-floor-3.

    У Material Design Icons пронумерованы только этажи 1–3 (плюс 0 и -1),
    для остальных берём общую mdi:home-floor-a.
    """
    n = int(floor)
    if n == 0:
        return "mdi:home-floor-0"
    if n < 0:
        return "mdi:home-floor-negative-1"
    if 1 <= n <= 3:
        return f"mdi:home-floor-{n}"
    return "mdi:home-floor-a"


# Имена и идентификаторы групп этажа. Живут в каноне, а не в генераторе групп:
# на них ссылаются и generate_floor_groups.py (создаёт группы), и
# generate_lovelace_cards.py (кладёт группу этажа в бейдж). Два источника
# правды разъехались бы на первой же правке.
#
# ⚠ САМОЕ ВАЖНОЕ ЗДЕСЬ: unique_id — это НЕ entity_id.
# У YAML-платформы `light: - platform: group` идентификатор сущности HA
# генерирует из `name` через slugify, а unique_id лишь регистрирует сущность
# в реестре (чтобы её можно было переименовать через UI).
# Поэтому группа с name «Весь 1-й этаж» и unique_id «floor_1_all» живёт на
# объекте как light.ves_1_i_etazh, а никакого light.floor_1_all не существует.
# Общие группы помещений этой ловушки избегают случайно: у них name уже слаг
# (`101_tambur_obshchii`), и slugify для него — тождество.

def floor_group_name(floor: int) -> str:
    """«Весь 1-й этаж» — отображаемое имя группы всего этажа."""
    return f"Весь {int(floor)}-й этаж"


def tech_group_name(floor: int) -> str:
    """«Тех.пом 1-й этаж» — отображаемое имя группы технических помещений."""
    return f"Тех.пом {int(floor)}-й этаж"


def floor_group_unique_id(floor: int) -> str:
    """floor_1_all — ключ в реестре HA. НЕ entity_id, см. floor_light_entity."""
    return f"floor_{int(floor)}_all"


def tech_group_unique_id(floor: int) -> str:
    """tex_floor_1 — ключ в реестре HA. НЕ entity_id."""
    return f"tex_floor_{int(floor)}"


# Area, представляющая этаж целиком. Нужна карточке `type: area` на Главной:
# она умеет показывать только Area, карточки для Floor в HA нет.
#
# ⚠ На этаж приходятся ТРИ разные сущности с похожими именами — не путать:
#   Floor «1 этаж»              — запись реестра этажей, группирует Areas;
#   Area  «Весь 1 этаж»         — контейнер, куда владелец кладёт групповые
#                                 светильники этажа (у них нет устройства,
#                                 поэтому интеграция их никуда не разложит,
#                                 и конкуренции с комнатными Areas нет);
#   light «Весь 1-й этаж»       — сам выключатель этажа.

def floor_area_name(floor: int) -> str:
    """«Весь 1 этаж» — имя Area этажа."""
    return f"Весь {int(floor)} этаж"


def floor_area_id(floor: int) -> str:
    """ves_1_etazh — area_id так, как его сделает HA из имени.

    Тот же принцип, что у floor_light_entity: id генерируется из name через
    slugify, задать его напрямую при создании нельзя.
    """
    return slugify_room(floor_area_name(floor))


def floor_light_entity(floor: int) -> str:
    """light.ves_1_i_etazh — сущность группы «весь этаж» так, как её создаст HA.

    Выводим из того же имени, которое сами пишем в группу: тогда переименование
    группы автоматически тянет за собой и ссылку на неё, без ручной правки.

    ⚠ Оговорка: entity_id фиксируется при ПЕРВОМ создании сущности. Если имя
    группы поменять уже после деплоя, HA сохранит старый entity_id (сущность
    зарегистрирована по unique_id), и вычисленное здесь значение разойдётся
    с объектом. Меняете имя — проверьте entity_id на объекте.
    """
    return f"light.{slugify_room(floor_group_name(floor))}"


def tech_light_entity(floor: int) -> str:
    """light.tekh_pom_1_i_etazh — группа технических помещений этажа.

    Выводится из имени тем же способом, что и floor_light_entity, и с той же
    оговоркой про первое создание. ⚠ Группа необязательна: она отключается
    флагом `--no-tech-groups` у generate_floor_groups. Ссылаться на неё стоит
    только там, где её отсутствие не ломает карточку.
    """
    return f"light.{slugify_room(tech_group_name(floor))}"


# ============================================================
# ЕДИНИЦЫ ОБСЛУЖИВАНИЯ, СЕМЕЙСТВА, СКРИПТЫ
# ============================================================
#
# Один экземпляр скрипта в Home Assistant — это одна очередь. При тысяче
# датчиков вызовы копятся, и свет отстаёт от человека. Поэтому шаблонные
# скрипты КЛОНИРУЮТСЯ: у каждой единицы обслуживания свой набор, и они
# друг друга не ждут.
#
# Единица обслуживания:
#   - «Блок» пуст     -> помещение обслуживается само по себе
#   - «Блок» заполнен -> все помещения с этим значением обслуживаются вместе
#
# Что склеивать в блок, решает проектировщик, глядя на план: лестничный стояк,
# соседние санузлы, длинный коридор пополам. Вывести это из таблицы нельзя —
# номер помещения не говорит, какая лестница над какой.

# Семейство определяет, какие blueprint'ы и скрипты нужны единице.
# class и zal не автоматизируются: класс управляется панелью и поддержанием
# освещённости (вне нашей области), зал — только панелями.
FAMILY_BY_SPACE_TYPE: Dict[str, Optional[str]] = {
    "korridor": "default",
    "recreation": "default",
    "hall": "hall",
    "special": "special",
    "class": None,
    "zal": None,
}

# Какие скрипты клонируются для каждого семейства.
# Ключ — роль скрипта, значение — файл шаблона.
SCRIPTS_BY_FAMILY: Dict[str, Dict[str, str]] = {
    "default": {
        "on": "motion_on.yaml",
        "off": "motion_off.yaml",
        "near_off": "motion_near_off_json.yaml",
    },
    "hall": {
        "on": "motion_on.yaml",
        "off": "motion_off.yaml",
        "hall_near": "hall_near_off.yaml",
    },
    "special": {
        "on": "special_on.yaml",
        "off": "special_off.yaml",
    },
}

# Blueprint'ы семейства: (ON, OFF).
BLUEPRINTS_BY_FAMILY: Dict[str, Dict[str, str]] = {
    "default": {"on": "zm_default_on.yaml", "off": "zm_default_off.yaml"},
    "hall": {"on": "zm_hall_on.yaml", "off": "zm_hall_off.yaml"},
    "special": {"on": "zm_special_on.yaml", "off": "zm_special_off.yaml"},
}

# Куда blueprint'ы кладутся на Home Assistant.
# В use_blueprint путь считается от config/blueprints/automation/.
BLUEPRINT_DIR: str = "zone_manager"

# ============================================================
# Вспомогательные объекты (helpers)
# ============================================================
#
# Их создаёт generate_helpers.py -> includes/packages/zm_lighting-compilers.yaml.
# Пайплайн создаёт САМ ОБЪЕКТ, но не логику за ним: input_boolean — это
# выключатель, а что он включает, описывают автоматизации владельца.
# Исключение — vacant_delay и навигационные input_select: их читает наш код.
#
# ⚠ entity_id берётся из КЛЮЧА в YAML (`vacant_delay:` -> input_number.
# vacant_delay), поэтому предсказуем. Через UI он выводится из отображаемого
# имени — ловушка, на которой мы уже обжигались с группами этажа.

# input_number с задержкой перехода в vacant. Один на объект.
# На него ссылается КАЖДАЯ OFF-автоматизация.
VACANT_DELAY_ENTITY: str = "input_number.vacant_delay"
VACANT_DELAY_ID: str = "vacant_delay"
VACANT_DELAY_DEFAULT: int = 10     # секунд, согласовано с владельцем 2026-07-17
VACANT_DELAY_MIN: int = 0
VACANT_DELAY_MAX: int = 300        # 5 минут — задержка гашения света
VACANT_DELAY_STEP: int = 1

# ⚠ `initial` у input_number задаёт значение при КАЖДОМ старте HA, а не только
# при создании: «If you set a valid value for initial this integration will
# start with the state set to that value. Otherwise, it will restore the state
# it had before Home Assistant stopping» (доки input_number).
#
# Ставим осознанно: значение принадлежит пайплайну, как и группы света —
# хотите другое, меняете константу и передеплоиваете. Цена — правка в UI живёт
# до перезапуска. Взамен навсегда закрыт `unknown` на чистом объекте, из-за
# которого `for: seconds` ломался и свет не гас (главный известный долг).

BACK_BUTTON_ID: str = "but_back"
BACK_BUTTON_ENTITY: str = f"input_button.{BACK_BUTTON_ID}"

# Пресеты зала. Захардкожены в templates/lovelace/zal/wrapper.yaml (зал один
# на объект, имена произвольные). Список здесь — чтобы helpers их создал.
# ⚠ Два места обязаны совпадать; стережёт тест test_zal_presets_match_template:
# правите wrapper — правьте и здесь, иначе карточка сошлётся в пустоту.
ZAL_PRESETS: Dict[str, str] = {
    "rezhim_tetra": "Режим театра",
    "polnaia_iarkost": "Максимальная яркость",
    "priglushennoe_osveshchenie": "Приглушенный свет",
    "rezhim_meropriiatiia": "Режим мероприятия",
}


def floor_auto_mode_id(floor: int) -> str:
    """regim_auto_1 — object_id помощника режима этажа."""
    return f"regim_auto_{int(floor)}"


def floor_auto_mode_entity(floor: int) -> str:
    """input_boolean.regim_auto_1 — бейдж режима на этажном view."""
    return f"input_boolean.{floor_auto_mode_id(floor)}"


# Первая опция списка навигации — «ничего не выбрано».
#
# У input_select состояние всегда равно одной из options: пустого значения у
# него не бывает. Поэтому «пустое поле при загрузке» = заглушка первой опцией,
# и она СОЗНАТЕЛЬНО отсутствует в карте «имя → слаг» кнопки перехода: тогда
# map.get(room) вернёт пусто, и кнопка покажет «Выберите помещение из списка».
#
# Менять текст — здесь. Он не должен совпасть ни с одним именем помещения,
# иначе это помещение станет недостижимым.
NAV_PLACEHOLDER: str = "—"


def floor_nav_id(floor: int) -> str:
    """nav_floor_1 — object_id списка выбора помещения."""
    return f"nav_floor_{int(floor)}"


def floor_nav_entity(floor: int) -> str:
    """input_select.nav_floor_1 — список выбора помещения на Главной.

    Его опции генерируются из того же списка помещений, что и карта
    «имя → слаг» в markdown-кнопке перехода. Заполнять опции руками нельзя:
    расхождение на один символ молча ломает навигацию.
    """
    return f"input_select.{floor_nav_id(floor)}"


# Сервисные страницы дашборда: расписание и конфигурация.
#
# Штучные, из таблицы не выводятся — как пресеты зала. Блок кнопок на Главной
# захардкожен в templates/lovelace/_blocks/main_service_block.yaml, а список
# здесь нужен, чтобы деплой высеял сами страницы: кнопка на несуществующий
# view уводит в «view not found».
#
# ⚠ Путь НАМЕРЕННО без префикса `zm-`.
#
# Правило слияния однострочное: `zm-` — наше, перезаписываем целиком;
# не `zm-` — владельца, не трогаем никогда. Наполнять эти страницы будет
# владелец, значит они его. Дай им префикс `zm-` — и первая же регенерация
# карточек стёрла бы расписание, которое он туда занёс.
#
# Поэтому деплой их не генерирует, а ВЫСЕВАЕТ: нет такого пути на дашборде —
# создаём пустую заготовку, есть — оставляем как есть.
#
# ⚠ Тест стережёт отсутствие префикса: добавите его «для порядка» —
# потеряете чужую работу молча, узнаете об этом на объекте.
# ⚠ `heading` — короткий, в одно слово, и подписи у кнопки нет вовсе.
#
# Это не про краткость ради краткости. У блоков на Главной `rows: auto`, то есть
# высота считается по содержимому: стоит заголовку не влезть в колонку и
# перенестись на вторую строку — блок становится выше соседнего, и ряд едет.
# Так и случилось с «Настройка конфигурации» (2026-07-17).
#
# `title` — полный: это заголовок самой страницы, он живёт во вкладке, где
# места сколько угодно.
SERVICE_VIEWS: Tuple[Dict[str, str], ...] = (
    {
        "path": "raspisanie",
        "title": "Настройка расписания",
        "heading": "📆 Расписание",
        "icon": "mdi:calendar-clock",
    },
    {
        "path": "konfiguratsiia",
        "title": "Настройка конфигурации",
        "heading": "🔧 Конфигурация",
        "icon": "mdi:cog",
    },
)


# Какие входы принимает blueprint каждого семейства.
#
# ⚠ У special OFF вход ОДИН (off_script), у default и hall — два
# (off_script_1 = своя зона, off_script_2 = соседние). Имена входов различаются,
# поэтому описаны явно, а не выводятся из числа скриптов.
#
# Значение — какую роль скрипта подставить в этот вход.
# sensors — специальное значение: список датчиков единицы.
BLUEPRINT_INPUTS_BY_FAMILY: Dict[str, Dict[str, Dict[str, str]]] = {
    "default": {
        "on": {
            "motion_sensors": "sensors",
            "on_script": "on",
        },
        "off": {
            "vacancy_sensors": "sensors",
            "vacant_delay_input": "vacant_delay",
            "off_script_1": "off",
            "off_script_2": "near_off",
        },
    },
    "hall": {
        "on": {
            "motion_sensors": "sensors",
            "on_script": "on",
        },
        "off": {
            "vacancy_sensors": "sensors",
            "vacant_delay_input": "vacant_delay",
            "off_script_1": "off",
            "off_script_2": "hall_near",
        },
    },
    "special": {
        "on": {
            "motion_sensors": "sensors",
            "on_script": "on",
        },
        "off": {
            "vacancy_sensors": "sensors",
            "vacant_delay_input": "vacant_delay",
            "off_script": "off",
        },
    },
}


def automation_id(unit_id: str, role: str) -> str:
    """Уникальный id автоматизации: zm_103_vestibiul_on."""
    return f"zm_{str(unit_id).strip()}_{role}"


def blueprint_path(filename: str, directory: str = BLUEPRINT_DIR) -> str:
    """
    Путь для use_blueprint: считается от config/blueprints/automation/.

        zm_default_on.yaml -> zone_manager/zm_default_on.yaml
    """
    return f"{directory}/{filename}"

# Предел зашит в сами blueprint'ы: при большем числе датчиков автоматизация
# останавливается и пишет warning в лог HA. Валидатор предупреждает заранее.
MAX_SENSORS_PER_UNIT: int = 12


def family_for_space_type(space_type: Optional[str]) -> Optional[str]:
    """Семейство по типу помещения. None — автоматизации не нужны."""
    if not space_type:
        return None
    return FAMILY_BY_SPACE_TYPE.get(space_type)


def script_entity(unit_id: str, role: str) -> str:
    """
    Имя клонированного скрипта.

        ("103_vestibiul", "on")  -> script.103_vestibiul_on
        ("ladder_1", "near_off") -> script.ladder_1_near_off

    unit_id — это «Блок» из таблицы либо room_slug помещения, если блок пуст.
    """
    return f"script.{str(unit_id).strip()}_{role}"


def script_object_id(unit_id: str, role: str) -> str:
    """Корневой ключ в scripts.yaml — то же имя, но без домена."""
    return f"{str(unit_id).strip()}_{role}"
