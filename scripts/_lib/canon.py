# -*- coding: utf-8 -*-
"""
canon.py
Общий "канон" проекта: ключи, правила и настройки, которые должны быть едиными для всех скриптов.

Зачем нужен файл:
- чтобы не копировать маппинги и константы в каждом скрипте
- чтобы при изменении правила оно менялось в одном месте
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


# Версия схемы нормализованных данных (для normalized_meta.json)
NORMALIZED_SCHEMA_VERSION: int = 1


# Ключи типов карточек (card_type) — должны совпадать с templates/manifest.yaml
# Здесь оставляем на будущее, если потребуется строгая валидация.
ALLOWED_CARD_TYPES = {
    "cabinet",
    "corridor",
    "su",
    "lestnitsa",
    "generic",
}

# Типы помещений, которые считаем "техническими" для отдельных групп на этаж
# Можно менять состав без правок генераторов.
TECHNICAL_CARD_TYPES = {
    "corridor",
    "su",
    "lestnitsa",
}

# Префиксы доменов Home Assistant (если позже понадобится расширять)
HA_LIGHT_DOMAIN: str = "light"
HA_SENSOR_DOMAIN: str = "sensor"

def normalize_lamp_id_to_entity(raw: str) -> str:
    """
    Преобразовать lamp_id (например "1.20.15" или "4.1.1") в HA entity_id светильника.

    Пример:
        "1.20.15" -> "light.l_1_20_15"
    """
    # Зачем: lamp_id в parquet хранится как код с точками, а entity_id в HA удобнее с '_'
    s = "" if raw is None else str(raw).strip()

    # Меняем разделители на underscore, чтобы получить "1_20_15"
    code = s.replace(".", "_").replace("-", "_")

    # Используем канонический домен света из canon.py
    return f"{HA_LIGHT_DOMAIN}.l_{code}"

@dataclass(frozen=True)
class GeneralLightNamingRule:
    """
    Правило формирования entity_id общего света по room_slug.
    Сейчас по договорённости: light.<room_slug>_obshchii

    Если позже понадобится особая логика/исключения — меняем тут, а не в генераторах.
    """
    suffix: str = "_obshchii"

    def build(self, room_slug: str) -> str:
        return f"{HA_LIGHT_DOMAIN}.{room_slug}{self.suffix}"


GENERAL_LIGHT_RULE = GeneralLightNamingRule()
