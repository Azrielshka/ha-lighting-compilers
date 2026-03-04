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


# Префиксы доменов Home Assistant (если позже понадобится расширять)
HA_LIGHT_DOMAIN: str = "light"
HA_SENSOR_DOMAIN: str = "sensor"


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
