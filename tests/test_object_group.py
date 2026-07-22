# -*- coding: utf-8 -*-
"""
Группа всего объекта: «Весь объект» = свет всех этажей.

Собрана ВЛОЖЕННО — из групп этажей, а не из общих групп помещений (решение
владельца 2026-07-20). У вложенности два принятых допущения, и оба таковы, что
без теста о них забудут:

  1. техгруппы в состав НЕ входят — они подмножество этажных, и техпомещение
     попало бы в объект дважды;
  2. помещение без этажа не попадёт вообще — оно не попало ни в одну этажную.

Плюс капкан, на котором проект уже обжигался: `unique_id` — это не `entity_id`.
Бейдж на Главной ссылается на entity_id, и сослаться на `light.object_all`
означало бы повесить его в пустоту.
"""

from __future__ import annotations

import io
import contextlib
from pathlib import Path

import pytest
import yaml

import generate_floor_groups as FLOOR
import generate_lovelace_cards as G
import normalize_excel as N
from conftest import make_book
from scripts._lib import canon as C
from scripts._lib.filters import Filters
from scripts._lib.naming import slugify_room
from scripts._lib.normalized import load_dataset


@pytest.fixture
def object_layer(tmp_path, object_example) -> Path:
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


def _groups(layer: Path) -> dict:
    """Группы из фактического YAML генератора: {unique_id: группа}.

    ⚠ Без этажей генератор отдаёт документ из одного комментария, и safe_load
    возвращает None — не пустой словарь. Пустой результат здесь законен: он и
    означает «групп нет».
    """
    spaces = load_dataset(layer, "spaces")
    with contextlib.redirect_stdout(io.StringIO()):
        doc = yaml.safe_load(FLOOR.build_yaml(spaces, Filters()))
    if not doc:
        return {}
    return {g["unique_id"]: g for g in doc[FLOOR.ROOT_KEY]["light"]}


# ============================================================
# Состав
# ============================================================

def test_object_group_is_created(object_layer):
    groups = _groups(object_layer)

    assert C.object_group_unique_id() in groups
    assert groups[C.object_group_unique_id()]["name"] == C.object_group_name()


def test_object_group_holds_exactly_the_floor_groups(object_layer):
    """Состав = группы этажей. Ни больше, ни меньше.

    Сверяем с ДРУГИМИ группами того же файла, а не с каноном: канон подтвердил
    бы имя и у этажа, которого генератор не создал.
    """
    groups = _groups(object_layer)

    floor_entities = {
        f"light.{slugify_room(g['name'])}"
        for uid, g in groups.items() if uid.startswith("floor_")
    }
    assert floor_entities, "в фикстуре нет ни одной этажной группы"

    assert set(groups[C.object_group_unique_id()]["entities"]) == floor_entities


def test_tech_groups_are_not_included(object_layer):
    """Техгруппы — ПОДМНОЖЕСТВО этажных.

    Возьми кто-нибудь «все группы из файла» скопом, техпомещение попало бы в
    объект дважды и перекосило яркость. Ошибка тихая: сумма светится, состав
    глазами не виден.
    """
    groups = _groups(object_layer)

    tech_entities = {
        f"light.{slugify_room(g['name'])}"
        for uid, g in groups.items() if uid.startswith("tex_")
    }
    assert tech_entities, "в фикстуре нет техгрупп — тест ничего не стережёт"

    inside = set(groups[C.object_group_unique_id()]["entities"]) & tech_entities
    assert not inside, f"техгруппы попали в объект: {sorted(inside)}"


def test_no_room_is_counted_twice(object_layer):
    """Ни одно помещение не учтено дважды при разворачивании иерархии."""
    groups = _groups(object_layer)

    rooms = []
    for entity in groups[C.object_group_unique_id()]["entities"]:
        floor_group = next(g for uid, g in groups.items()
                           if uid.startswith("floor_")
                           and f"light.{slugify_room(g['name'])}" == entity)
        rooms += floor_group["entities"]

    assert len(rooms) == len(set(rooms)), \
        f"дубли при разворачивании: {sorted({r for r in rooms if rooms.count(r) > 1})}"


def test_object_group_covers_every_room_with_a_floor(object_layer):
    """Все помещения, у которых есть этаж, попали в объект — через свой этаж."""
    spaces = load_dataset(object_layer, "spaces")
    with_floor = {str(e) for e, f in
                  zip(spaces["general_light_entity"], spaces["floor"]) if not pd_isna(f)}

    groups = _groups(object_layer)
    covered = set()
    for entity in groups[C.object_group_unique_id()]["entities"]:
        fg = next(g for uid, g in groups.items()
                  if uid.startswith("floor_")
                  and f"light.{slugify_room(g['name'])}" == entity)
        covered |= set(fg["entities"])

    assert covered == with_floor


def pd_isna(value) -> bool:
    import pandas as pd
    return bool(pd.isna(value))


# ============================================================
# entity_id, а не unique_id
# ============================================================

def test_entity_id_comes_from_name_not_unique_id(object_layer):
    """Тот самый капкан: HA выводит entity_id из ИМЕНИ через slugify.

    `light.object_all` не существует. Проверяем не через канон (это была бы
    тавтология), а через фактическое имя в YAML генератора.
    """
    group = _groups(object_layer)[C.object_group_unique_id()]

    assert C.object_light_entity() == f"light.{slugify_room(group['name'])}"
    assert C.object_light_entity() != f"light.{group['unique_id']}"


# ============================================================
# Бейдж на Главной
# ============================================================

def test_main_badge_points_at_a_group_that_exists(object_layer, tmp_path):
    """Бейдж ссылается на сущность, которую РЕАЛЬНО создаёт генератор групп.

    Сверка между двумя генераторами: карточки строит один, группу — другой.
    Разъедутся — бейдж покажет «сущность недоступна», и причину будут искать в
    дашборде, а не в группах.
    """
    out_dir = tmp_path / "lovelace"
    G.generate_cards(
        spaces_parquet=object_layer / "spaces.parquet",
        templates_dir=G.DEFAULT_TEMPLATES_DIR,
        out_dir=out_dir,
        report_json=tmp_path / "report.json",
        filters=Filters(),
        dashboard="dash-test",
        title="Объект-тест",
    )
    main = yaml.safe_load((out_dir / "zm-main.yaml").read_text(encoding="utf-8"))

    badges = main.get("badges", [])
    assert badges, "на Главной нет бейджей"

    groups = _groups(object_layer)
    real = {f"light.{slugify_room(g['name'])}" for g in groups.values()}

    entities = [b["entity"] for b in badges]
    assert C.object_light_entity() in entities
    for entity in entities:
        assert entity in real, f"бейдж ссылается на несозданную группу: {entity}"


# ============================================================
# Края
# ============================================================

def _layer_with_floors(tmp_path: Path, floors: int) -> Path:
    rows = [{
        "Этаж": f, "Название помещения": f"{f}01_Коридор", "Тип помещения": "Korridor",
        "Шина DALI": 1, "Группа": f"{f}01_1", "Лампа": f"{f}.1.1",
        "Датчик": f"{f}.1.1", "Панель": "None",
    } for f in range(1, floors + 1)]
    out = tmp_path / f"norm{floors}"
    with contextlib.redirect_stdout(io.StringIO()):
        N.normalize(make_book(tmp_path / f"t{floors}.xlsx", rows), out)
    return out


def test_single_floor_still_gets_the_group(tmp_path):
    """На одноэтажном объекте группа дублирует единственную этажную — и всё равно есть.

    Бейдж на Главной захардкожен: без сущности он покажет «недоступна». Дубль
    безвреден, отсутствие — заметно.
    """
    groups = _groups(_layer_with_floors(tmp_path, 1))

    assert C.object_group_unique_id() in groups
    assert groups[C.object_group_unique_id()]["entities"] == [C.floor_light_entity(1)]


def test_group_scales_with_the_table(tmp_path):
    """Состав идёт ОТ ТАБЛИЦЫ, а не от числа в коде."""
    for n in (1, 3, 5):
        groups = _groups(_layer_with_floors(tmp_path, n))
        entities = groups[C.object_group_unique_id()]["entities"]
        assert entities == [C.floor_light_entity(f) for f in range(1, n + 1)], n


def test_no_floors_no_group(tmp_path):
    """Нет этажей — нет и пустой группы: пустышек не плодим."""
    rows = [{
        "Название помещения": "101_Тамбур", "Тип помещения": "Special",
        "Шина DALI": 1, "Группа": "101_1", "Лампа": "1.1.1",
        "Датчик": "1.1.1", "Панель": "None",
    }]
    out = tmp_path / "nofloor"
    with contextlib.redirect_stdout(io.StringIO()):
        N.normalize(make_book(tmp_path / "nf.xlsx", rows), out)

    assert C.object_group_unique_id() not in _groups(out)
