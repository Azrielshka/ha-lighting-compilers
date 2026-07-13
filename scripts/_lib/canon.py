# -*- coding: utf-8 -*-
"""
canon.py
Общий "канон" проекта: ключи, правила и настройки, которые должны быть едиными для всех скриптов.

Зачем нужен файл:
- чтобы не копировать маппинги и константы в каждом скрипте
- чтобы при изменении правила оно менялось в одном месте

Модель данных v2 описана в docs/internal/data_model_v2.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Set


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

# input_number с задержкой перехода в vacant. Один на объект.
# ⚠ Пайплайн его НЕ создаёт (договорённость с владельцем, 2026-07-13).
# Без него OFF-автоматизации соберутся, но триггер не сработает:
# `for: seconds: {{ states(...) }}` вернёт unknown, и свет не будет гаснуть.
VACANT_DELAY_ENTITY: str = "input_number.vacant_delay"


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
