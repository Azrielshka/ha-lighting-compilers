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
from typing import Optional, Set


# Версия схемы нормализованных данных (для normalized_meta.json)
NORMALIZED_SCHEMA_VERSION: int = 2


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
}

# Типы, которые считаем "техническими" для отдельных групп на этаж.
# ЗАГЛУШКА: в таксономии v2 su/lestnitsa исчезли, лестница стала korridor.
# Состав уточняется при переезде generate_floor_groups.py (см. docs/ROADMAP.md).
TECHNICAL_SPACE_TYPES: Set[str] = {"korridor"}


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
# LEGACY (схема v1) — удаляется вместе с переездом генераторов
# ============================================================
# Оставлено, чтобы старые генераторы импортировались до своего переезда
# (см. docs/ROADMAP.md, этап 4). Новый код этим не пользуется.

ALLOWED_CARD_TYPES = {"cabinet", "corridor", "su", "lestnitsa", "generic"}
TECHNICAL_CARD_TYPES = {"corridor", "su", "lestnitsa"}


def normalize_lamp_id_to_entity(raw: str) -> str:
    """LEGACY: 1.20.15 -> light.l_1_20_15 (без валидации формата)."""
    s = "" if raw is None else str(raw).strip()
    code = s.replace(".", "_").replace("-", "_")
    return f"{HA_LIGHT_DOMAIN}.{LAMP_PREFIX}_{code}"
