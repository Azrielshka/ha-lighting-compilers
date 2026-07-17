# -*- coding: utf-8 -*-
"""
yaml_render.py
Рендер YAML-блоков групп света.

YAML генерируется ТЕКСТОМ, а не сериализацией — это принцип проекта:
наладчик читает результат глазами и сверяет со своей таблицей, поэтому
важны и комментарии, и порядок, и отступы.

Все три генератора групп пишут одинаковый блок `platform: group`,
отличаются только корневым ключом и содержимым entities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence


# Отступы соответствуют формату, который ждёт Home Assistant в packages/.
INDENT_LIGHT = "  "
INDENT_ITEM = "    "
INDENT_FIELD = "      "
INDENT_ENTITY = "        "


@dataclass(frozen=True)
class LightGroup:
    """Одна группа света в YAML."""

    # object_id: попадёт и в name, и в unique_id, и (с доменом) в entity_id.
    unique_id: str

    # Отображаемое имя. У зон и общих групп совпадает с unique_id,
    # у групп этажа — русское («Весь 1-й этаж»).
    name: str

    # Сущности группы. Порядок сохраняется как в таблице.
    entities: Sequence[str]

    # Комментарий над блоком — чтобы наладчик находил нужное место глазами.
    comment: str = ""


def render_group(group: LightGroup) -> List[str]:
    """Отрендерить один блок platform: group."""
    lines: List[str] = []

    if group.comment:
        lines.append(f"{INDENT_LIGHT}#{group.comment}")

    lines.append(f"{INDENT_ITEM}- platform: group")
    lines.append(f'{INDENT_FIELD}name: "{group.name}"')
    lines.append(f'{INDENT_FIELD}unique_id: "{group.unique_id}"')
    lines.append(f"{INDENT_FIELD}entities:")

    for entity in group.entities:
        lines.append(f"{INDENT_ENTITY}- {entity}")

    lines.append("")  # пустая строка между блоками для читаемости
    return lines


def render_document(root_key: str, groups: Sequence[LightGroup], empty_note: str) -> str:
    """
    Собрать YAML-документ целиком.

    root_key — корневой ключ файла (lights_group / lights_general_group / ...).
    empty_note — что написать, если групп нет: пустой YAML-файл выглядит
    как поломка, а комментарий объясняет, что данных не было.
    """
    if not groups:
        return f"# {empty_note}\n"

    lines: List[str] = [f"{root_key}:", f"{INDENT_LIGHT}light:"]

    for group in groups:
        lines.extend(render_group(group))

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"
