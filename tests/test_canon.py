# -*- coding: utf-8 -*-
"""Канон нейминга и разбор адресов."""

from __future__ import annotations

import pytest

from scripts._lib.canon import (
    ALLOWED_SPACE_TYPES,
    general_light_entity,
    is_blank,
    is_none_token,
    lamp_entity,
    normalize_space_type,
    panel_entity,
    parse_addr,
    sensor_illuminance_entity,
    sensor_motion_entity,
    zone_light_entity,
)


def test_parse_addr():
    addr = parse_addr("1.20.15")
    assert (addr.floor, addr.bus, addr.num) == (1, 20, 15)
    assert addr.slug == "1_20_15"
    assert str(addr) == "1.20.15"


@pytest.mark.parametrize("raw", ["", "1.20", "1.20.15.3", "a.b.c", "1-20-15", "None", "1.20.x"])
def test_parse_addr_rejects(raw):
    with pytest.raises(ValueError):
        parse_addr(raw)


def test_parse_addr_strips_whitespace():
    assert parse_addr("  1.1.1  ").slug == "1_1_1"


def test_entity_naming():
    assert lamp_entity("1.20.15") == "light.l_1_20_15"
    assert sensor_motion_entity("1.20.3") == "sensor.ms_1_20_3"
    assert sensor_illuminance_entity("1.20.3") == "sensor.il_1_20_3"
    assert panel_entity("1.1.1") == "event.kp_1_1_1"
    assert zone_light_entity("102_1") == "light.102_1"
    assert general_light_entity("104_metodicheskii_kabinet") == "light.104_metodicheskii_kabinet_obshchii"


def test_one_sensor_address_yields_two_entities():
    """Датчик даёт и движение, и освещённость — это две разные сущности HA."""
    assert sensor_motion_entity("1.1.2") != sensor_illuminance_entity("1.1.2")


def test_entity_builders_accept_addr_object():
    addr = parse_addr("2.3.4")
    assert lamp_entity(addr) == "light.l_2_3_4"


@pytest.mark.parametrize("raw,expected", [
    ("Korridor", "korridor"),
    (" Class ", "class"),
    ("ZAL", "zal"),
    ("", None),
    ("   ", None),
    (None, None),
])
def test_normalize_space_type(raw, expected):
    assert normalize_space_type(raw) == expected


def test_space_types_are_lowercase_keys():
    assert all(t == t.lower() for t in ALLOWED_SPACE_TYPES)
    assert "korridor" in ALLOWED_SPACE_TYPES  # именно так, не corridor
    assert "generic" not in ALLOWED_SPACE_TYPES


@pytest.mark.parametrize("raw", ["None", "none", "НЕТ", "нет", "-", "–", "—", " None "])
def test_none_tokens(raw):
    assert is_none_token(raw)
    assert not is_blank(raw)


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_blank_is_not_none_token(raw):
    """Пустая ячейка и None — разные вещи: пустая ничего не утверждает."""
    assert is_blank(raw)
    assert not is_none_token(raw)


def test_address_is_not_none_token():
    assert not is_none_token("1.1.1")


# ============================================================
# ГРУППЫ ЭТАЖА: unique_id — это НЕ entity_id
# ============================================================

def test_floor_light_entity_comes_from_name_not_unique_id():
    """У YAML-группы света entity_id генерируется из `name`, а не из unique_id.

    На этом уже обожглись: бейдж этажа ссылался на light.floor_1_all, которого
    на объекте не существует — группа с name «Весь 1-й этаж» живёт как
    light.ves_1_i_etazh. unique_id лишь регистрирует сущность в реестре.
    """
    from scripts._lib.canon import floor_group_unique_id, floor_light_entity

    assert floor_light_entity(1) == "light.ves_1_i_etazh"
    assert floor_light_entity(2) == "light.ves_2_i_etazh"

    # именно то, что перепутали: unique_id живёт своей жизнью
    assert floor_group_unique_id(1) == "floor_1_all"
    assert floor_light_entity(1) != f"light.{floor_group_unique_id(1)}"


def test_floor_light_entity_follows_group_name():
    """Ссылка выводится из имени, поэтому переименование группы её не ломает."""
    from scripts._lib.canon import floor_group_name, floor_light_entity
    from scripts._lib.naming import slugify_room

    for floor in (1, 2, 3, 11):
        assert floor_light_entity(floor) == f"light.{slugify_room(floor_group_name(floor))}"
