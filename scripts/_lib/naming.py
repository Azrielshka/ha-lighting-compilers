# -*- coding: utf-8 -*-
"""
naming.py
Единые функции нейминга (slugify/translit) для всего проекта.

Почему выносим:
- разные скрипты должны получать одинаковые entity_id/slug при одинаковом входе
- правим в одном месте, а не размазываем по коду
"""

from __future__ import annotations

import re
from typing import Dict


# Базовая таблица транслитерации RU -> EN (приближённая, достаточная для slug)
# При необходимости можно расширять.
_RU_TO_EN: Dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "iu", "я": "ia",
}

# Разрешённые символы в slug (Home Assistant entity_id дружит с a-z0-9_).
_ALLOWED_RE = re.compile(r"[^a-z0-9_]+")


def translit_ru_to_en(text: str) -> str:
    """
    Транслитерация русских букв в латиницу.
    - сохраняем цифры, латиницу и символ '_' как есть
    - остальное пытаемся транслитерировать/упростить
    """
    if text is None:
        return ""

    s = str(text).strip().lower()
    out = []
    for ch in s:
        if "a" <= ch <= "z" or "0" <= ch <= "9" or ch == "_":
            out.append(ch)
            continue
        if ch in _RU_TO_EN:
            out.append(_RU_TO_EN[ch])
            continue
        # Пробелы и дефисы — в underscore (удобно для entity_id)
        if ch in {" ", "-", "—", "–", "/"}:
            out.append("_")
            continue
        # Остальное — выбрасываем
        out.append("_")
    return "".join(out)


def slugify_room(text: str) -> str:
    """
    Делает room_slug:
    - RU -> EN
    - заменяет любые запрещённые символы на '_'
    - сжимает повторяющиеся '_'
    - обрезает '_' по краям
    """
    base = translit_ru_to_en(text)
    base = _ALLOWED_RE.sub("_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    return base
