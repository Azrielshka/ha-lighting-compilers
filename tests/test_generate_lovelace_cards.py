# -*- coding: utf-8 -*-
"""
Генератор карточек Lovelace (v3). У каждого space_type своя раскладка.

Шаг офлайновый: к HA не подключается, собирает текст карточек для дашборда.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import generate_lovelace_cards as G
import normalize_excel as N
from conftest import make_book
from scripts._lib.filters import Filters


# ============================================================
# Блоки-плитки (реальные из templates/lovelace/_blocks)
# ============================================================

@pytest.fixture(scope="module")
def blocks() -> dict:
    return {name: G._load_block(G.DEFAULT_TEMPLATES_DIR, name) for name in G.BLOCK_NAMES}


def _lights(n):
    return [f"light.z_{i}" for i in range(n)]


def _one_sensor_each(n):
    return [[f"sensor.ms_{i}"] for i in range(n)]


# ============================================================
# balanced_sizes — балансная нарезка (без одинокого хвоста)
# ============================================================

@pytest.mark.parametrize("n,expected", [
    (1, [1]),
    (3, [3]),
    (4, [2, 2]),      # не [3, 1]
    (5, [3, 2]),
    (6, [3, 3]),
    (7, [3, 2, 2]),   # не [3, 3, 1]
    (8, [3, 3, 2]),
    (9, [3, 3, 3]),
])
def test_balanced_sizes(n, expected):
    assert G.balanced_sizes(n) == expected
    assert sum(G.balanced_sizes(n)) == n
    assert all(s <= G.ZONES_PER_GRID for s in G.balanced_sizes(n))


# ============================================================
# korridor — сетки-тройки, пары свет|датчик, перенос по рядам
# ============================================================

def test_korridor_single_grid_no_stack(blocks):
    """≤3 зон → одна сетка, без horizontal-stack (во всю ширину, как эталон)."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(3), _one_sensor_each(3))
    assert len(res) == 1
    assert res[0]["type"] == "grid"
    # 2 заголовка + 3 пары = 8 карточек
    assert len(res[0]["cards"]) == 2 + 3 * 2


def test_korridor_4_zones_balanced(blocks):
    """4 зоны → [2,2]: две сетки в одном horizontal-stack."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(4), _one_sensor_each(4))
    assert len(res) == 1                       # один ряд
    assert res[0]["type"] == "horizontal-stack"
    grids = res[0]["cards"]
    assert len(grids) == 2
    # каждая сетка: 2 заголовка + 2 пары
    assert all(len(g["cards"]) == 2 + 2 * 2 for g in grids)


def test_korridor_9_zones_wraps_and_pads(blocks):
    """9 зон → 3 сетки [3,3,3], макс 2 в ряд → 2 ряда, добор пустой карточкой."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(9), _one_sensor_each(9))
    assert len(res) == 2                        # два ряда
    assert res[0]["cards"][0]["type"] == "grid"
    assert len(res[0]["cards"]) == 2            # первый ряд — 2 сетки
    # второй ряд: сетка + заглушка-добор (чтобы не растягивалась)
    assert len(res[1]["cards"]) == 2
    assert res[1]["cards"][0]["type"] == "grid"
    assert res[1]["cards"][1]["type"] == "markdown"


def test_korridor_zero_sensor_is_spacer(blocks):
    """Зона без датчика → пустая ячейка (пары не сбиваются)."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(1), [[]])
    cards = res[0]["cards"]
    sensor_cell = cards[3]                       # [заг, заг, свет, датчик]
    assert sensor_cell["type"] == "markdown"
    assert sensor_cell["content"] == ""


def test_korridor_multi_sensor_stacked(blocks):
    """Зона с >1 датчиком → датчики стопкой в одной ячейке (пара сохраняется)."""
    res = G.build_korridor(blocks["light_tile"], blocks["sensor_tile"],
                           _lights(1), [["sensor.a", "sensor.b"]])
    sensor_cell = res[0]["cards"][3]
    assert sensor_cell["type"] == "vertical-stack"
    assert len(sensor_cell["cards"]) == 2


# ============================================================
# special / class / recreation / zal — специфика типов
# ============================================================

def test_special_pairs(blocks):
    res = G.build_special(blocks["light_tile"], blocks["sensor_tile"],
                          _lights(2), [["sensor.a", "sensor.b"], ["sensor.c"]])
    assert all(r["type"] == "horizontal-stack" for r in res)
    # первая зона: свет + 2 датчика
    assert len(res[0]["cards"]) == 3
    assert len(res[1]["cards"]) == 2


def test_class_columns_order_and_placeholder(blocks):
    res = G.build_class_columns(blocks["light_tile"], blocks["sensor_tile"],
                                blocks["class_label"], _lights(2), _one_sensor_each(2))
    # порядок: свет, свет, датчик, датчик, подпись, подпись
    assert [c["type"] for c in res] == ["tile", "tile", "tile", "tile", "markdown", "markdown"]
    assert res[-1]["content"] == G.LABEL_PLACEHOLDER


def test_recreation_groups_are_mushroom(blocks):
    res = G.build_recreation_groups(blocks["recreation_group"], _lights(2))
    assert all(c["type"] == "custom:mushroom-light-card" for c in res)
    assert res[0]["entity"] == "light.z_0"


def test_zal_lights_have_toggle_and_vertical():
    res = G.build_zal_lights(["light.a", "light.b"])
    assert all(c["vertical"] is True for c in res)
    assert all({"type": "toggle"} in c["features"] for c in res)


# ============================================================
# Интеграция на объектной фикстуре: всё собирается и валидно
# ============================================================

@pytest.fixture
def object_layer(tmp_path, object_example) -> Path:
    out = tmp_path / "normalized"
    N.normalize(object_example, out)
    return out


DASHBOARD = "dash-test"
DASHBOARD_TITLE = "Объект-тест"


def _generate(object_layer, tmp_path) -> dict:
    """Сгенерировать views в файлы; вернуть {path: view}."""
    out_dir = tmp_path / "lovelace"
    G.generate_cards(
        spaces_parquet=object_layer / "spaces.parquet",
        templates_dir=G.DEFAULT_TEMPLATES_DIR,
        out_dir=out_dir,
        report_json=tmp_path / "report.json",
        filters=Filters(),
        dashboard=DASHBOARD,
        title=DASHBOARD_TITLE,
    )
    views = {}
    for f in sorted(out_dir.glob("*.yaml")):
        v = yaml.safe_load(f.read_text(encoding="utf-8"))
        views[v["path"]] = v
    return views


def test_every_view_is_valid_and_sectioned(object_layer, tmp_path):
    """Каждый view — валидный YAML типа sections (наши карточки иначе не лягут)."""
    views = _generate(object_layer, tmp_path)
    assert views, "ни одного view не собрано"
    for view in views.values():
        assert view["type"] == "sections"
        assert view["sections"][0]["type"] == "grid"


def test_floor_view_holds_compact_cards_with_navigation(object_layer, tmp_path):
    """На этажном view — компактные карточки, каждая ведёт в свой subview."""
    views = _generate(object_layer, tmp_path)
    floor = views["zm-floor-1"]
    cards = floor["sections"][0]["cards"]
    assert cards, "этажный view пуст"

    for card in cards:
        button = card["cards"][-1]
        assert button["type"] == "button"
        path = button["tap_action"]["navigation_path"]
        assert path.startswith(f"/{DASHBOARD}/zm-space-")
        # ссылка ведёт на реально существующий subview
        assert path.rsplit("/", 1)[1] in views


def test_card_spans_full_section_width(object_layer, tmp_path):
    """Карточка помещения занимает всю ширину секции при любом column_span.

    Сетка секции = base(12) * column_span, поэтому `columns: 12` дал бы половину
    ширины у типов с column_span: 2 (korridor, zal). Спасает только `full`
    (grid-column: 1/-1). Ловим, если кто-то вернёт число.
    """
    views = _generate(object_layer, tmp_path)
    subviews = [v for p, v in views.items() if p.startswith("zm-space-")]
    assert subviews

    for view in subviews:
        card = view["sections"][0]["cards"][0]
        assert card["grid_options"]["columns"] == "full", view["path"]


def test_compact_button_keeps_card_mod_css(object_layer, tmp_path):
    """CSS кнопки «Подробнее» доезжает до view дословно.

    Он выверен на живом объекте (без `!important` раскладка не применяется —
    стили кнопки лежат в adopted stylesheets и выигрывают у card_mod), поэтому
    потерять или исказить его при сборке нельзя.
    """
    views = _generate(object_layer, tmp_path)
    button = views["zm-floor-1"]["sections"][0]["cards"][0]["cards"][-1]

    css = button["card_mod"]["style"]
    assert "flex-direction: row-reverse !important" in css
    assert "width: 36px !important" in css        # иначе иконка займёт 40% ширины

    # ровно тот CSS, что лежит в редактируемом блоке — без «улучшений» по пути
    block = G._load_block(G.DEFAULT_TEMPLATES_DIR, "compact_card")
    assert css == block["cards"][-1]["card_mod"]["style"]


def test_space_subview_is_hidden_and_has_full_card(object_layer, tmp_path):
    views = _generate(object_layer, tmp_path)
    sub = views["zm-space-103_vestibiul"]
    assert sub["subview"] is True
    assert sub["title"] == "103 Вестибюль"
    assert len(sub["sections"][0]["cards"]) == 1     # ровно полная карточка


def test_hall_uses_korridor_layout(object_layer, tmp_path):
    """Холл рисуется как коридор: заголовки колонок + пары «свет|датчик».

    До появления холла в фикстуре эту ветку можно было проверить только
    форс-прогоном на чужих данных.
    """
    views = _generate(object_layer, tmp_path)
    hall = views["zm-space-208_vkhodnoi_tambur"]["sections"][0]["cards"][0]

    grid = next(c for c in hall["cards"] if c.get("type") == "grid")
    kinds = [c["type"] for c in grid["cards"]]
    assert kinds[:2] == ["heading", "heading"]        # Группы | Датчики
    # дальше строго чередование свет, датчик
    entities = [c.get("entity") for c in grid["cards"][2:]]
    assert entities == ["light.208_1", "sensor.ms_2_1_1",
                        "light.208_2", "sensor.ms_2_1_2"]


def test_recreation_uses_mushroom_groups(object_layer, tmp_path):
    """Рекреация: узкие группы mushroom + датчики в гриде на 2 колонки."""
    views = _generate(object_layer, tmp_path)
    rec = views["zm-space-107_rekreatsiia"]["sections"][0]["cards"][0]

    groups = [c for c in rec["cards"] if c["type"] == "custom:mushroom-light-card"]
    assert [g["entity"] for g in groups] == ["light.107_1", "light.107_2"]

    sensors_grid = next(c for c in rec["cards"] if c.get("type") == "grid")
    assert sensors_grid["columns"] == 2
    assert all(c["type"] == "tile" for c in sensors_grid["cards"])


def test_second_floor_gets_its_own_view(object_layer, tmp_path):
    """Каждый этаж из колонки «Этаж» — свой view со своей иконкой."""
    views = _generate(object_layer, tmp_path)

    assert views["zm-floor-2"]["icon"] == "mdi:home-floor-2"
    assert views["zm-floor-2"]["max_columns"] == 3
    assert views["zm-floor-2"]["sections"][0]["column_span"] == 3
    # 208-е помещение попало на второй этаж, а не к первому
    cards = views["zm-floor-2"]["sections"][0]["cards"]
    paths = [c["cards"][-1]["tap_action"]["navigation_path"] for c in cards]
    assert paths == [f"/{DASHBOARD}/zm-space-208_vkhodnoi_tambur"]


def test_floor_header_and_badges(object_layer, tmp_path):
    """Шапка и бейджи этажа собираются из шаблона с нашими сущностями."""
    views = _generate(object_layer, tmp_path)
    floor = views["zm-floor-1"]

    assert floor["header"]["card"]["content"] == "# 1 Этаж"
    assert floor["header"]["badges_position"] == "top"

    badges = {b["entity"]: b for b in floor["badges"]}
    # свет этажа — наша группа. Имя сущности идёт от `name` группы через
    # slugify, а не от её unique_id: light.ves_1_i_etazh, не light.floor_1_all.
    assert "light.ves_1_i_etazh" in badges
    assert badges["light.ves_1_i_etazh"]["name"] == "Управление светом 1-го этажа"
    # помощники владельца — по конвенции от номера этажа
    assert "input_boolean.regim_auto_1" in badges
    assert "input_button.but_back" in badges


def test_floor_badge_points_at_really_existing_entity(object_layer, tmp_path):
    """Бейдж ссылается на сущность, которую HA реально создаст из нашей группы.

    Ловит ошибку, которая уже случилась: unique_id — это НЕ entity_id.
    У YAML-платформы `light: - platform: group` идентификатор генерируется из
    `name` через slugify, поэтому группа с name «Весь 1-й этаж» и
    unique_id «floor_1_all» живёт как light.ves_1_i_etazh, а light.floor_1_all
    не существует вовсе. Бейдж с ним висел бы в пустоте, и на объекте это
    выглядит как «сущность недоступна» без всяких подсказок почему.

    Проверяем не через canon (это была бы тавтология), а через фактический
    YAML соседнего генератора: имя группы → slugify → entity_id бейджа.
    """
    import generate_floor_groups as FLOOR
    from scripts._lib.filters import Filters
    from scripts._lib.naming import slugify_room
    from scripts._lib.normalized import load_dataset

    spaces = load_dataset(object_layer, "spaces")
    floor_yaml = yaml.safe_load(FLOOR.build_yaml(spaces, Filters()))
    groups = floor_yaml[FLOOR.ROOT_KEY]["light"]

    # entity_id так, как его сделает HA: из name, а не из unique_id
    real = {slugify_room(g["name"]): g["unique_id"] for g in groups}

    views = _generate(object_layer, tmp_path)
    for floor in (1, 2):
        badges = [b.get("entity") for b in views[f"zm-floor-{floor}"]["badges"]]
        light = next(b for b in badges if str(b).startswith("light."))
        assert light[len("light."):] in real, (
            f"бейдж {light} не соответствует ни одной созданной группе: "
            f"есть только {sorted(real)}"
        )


def test_back_badge_leads_to_dashboard_root(object_layer, tmp_path):
    """«Назад» ведёт на корень дашборда — там первый view, то есть Главная."""
    views = _generate(object_layer, tmp_path)
    back = next(b for b in views["zm-floor-1"]["badges"]
                if b["entity"] == "input_button.but_back")

    assert back["tap_action"]["navigation_path"] == f"/{DASHBOARD}"


def test_floor_view_path_comes_from_code_not_template(object_layer, tmp_path):
    """Путь этажа задаёт код: по префиксу zm- деплой отличает свои views.

    Оставь его на усмотрение шаблона — опечатка превратила бы замену view
    в размножение дублей на дашборде владельца.
    """
    from scripts._lib import ha_views as V

    views = _generate(object_layer, tmp_path)
    for floor in (1, 2):
        assert views[V.floor_view_path(floor)]["path"] == f"zm-floor-{floor}"


def test_zal_lights_are_in_one_row(object_layer, tmp_path):
    """Весь свет зала — одной строкой, а не столбиком во всю ширину."""
    views = _generate(object_layer, tmp_path)
    zal = views["zm-space-105_aktovyi_zal"]["sections"][0]["cards"][0]

    row = next(c for c in zal["cards"] if c["type"] == "horizontal-stack")
    entities = [c["entity"] for c in row["cards"]]

    assert "light.105_aktovyi_zal_obshchii" in entities   # общий свет
    assert "light.105_1" in entities and "light.105_2" in entities   # группы
    # ни одна плитка света не осталась отдельным ребёнком внешнего грида
    assert not [c for c in zal["cards"] if c["type"] == "tile"]


def test_zal_presets_survive_generation(object_layer, tmp_path):
    """Хардкод-пресеты зала не теряются при сборке в view."""
    views = _generate(object_layer, tmp_path)
    dumped = yaml.safe_dump(views["zm-space-105_aktovyi_zal"], allow_unicode=True)
    assert "input_boolean.rezhim_tetra" in dumped
    assert "custom:mushroom-template-card" in dumped


def test_space_without_valid_type_skipped(tmp_path):
    """Помещение без валидного типа не даёт ни subview, ни карточки на этаже."""
    rows = [
        {"Этаж": 1, "Название помещения": "201_Никакой", "Тип помещения": "None",
         "Шина DALI": 1, "Группа": "201_1", "Лампа": "1.1.1",
         "Датчик": "1.1.1", "Панель": "None"},
    ]
    out = tmp_path / "normalized"
    N.normalize(make_book(tmp_path / "t.xlsx", rows), out)
    assert _generate(out, tmp_path) == {}


def test_regeneration_removes_stale_views(object_layer, tmp_path):
    """Исчезнувшее помещение не оставляет за собой файл view."""
    out_dir = tmp_path / "lovelace"
    _generate(object_layer, tmp_path)
    stale = out_dir / "zm-space-999_prizrak.yaml"
    stale.write_text("path: zm-space-999_prizrak\n", encoding="utf-8")

    _generate(object_layer, tmp_path)
    assert not stale.exists()


# ============================================================
# ГЛАВНАЯ СТРАНИЦА
# ============================================================

def _main_view(views: dict) -> dict:
    return views["zm-main"]


def _floor_blocks(main: dict) -> list:
    return [c for c in main["sections"][0]["cards"] if c.get("type") == "vertical-stack"]


def test_main_view_is_generated_and_first(object_layer, tmp_path):
    """Главная — наша и обязана быть первой: дашборд открывается на первом view."""
    from scripts._lib import ha_views as V

    views = _generate(object_layer, tmp_path)
    assert "zm-main" in views

    ordered = V.order_views(list(views.values()))
    assert ordered[0]["path"] == "zm-main"
    # и merge ставит наши в начало, а не после чужого view
    merged = V.merge_views([{"path": "energy"}], ordered)
    assert merged[0]["path"] == "zm-main"


def test_main_has_one_block_per_floor(object_layer, tmp_path):
    blocks = _floor_blocks(_main_view(_generate(object_layer, tmp_path)))

    assert len(blocks) == 2          # в фикстуре два этажа
    areas = [b["cards"][0]["area"] for b in blocks]
    assert areas == ["ves_1_etazh", "ves_2_etazh"]


def test_main_floor_card_points_at_generated_area(object_layer, tmp_path):
    """Карточка этажа ссылается на Area, которую создаёт generate_areas.

    type: area показывает только Area — на Floor она не встанет. Если id
    разойдётся с тем, что создаёт generate_areas, карточка будет пустой.
    """
    from scripts._lib.canon import floor_area_id

    blocks = _floor_blocks(_main_view(_generate(object_layer, tmp_path)))
    for floor, block in zip((1, 2), blocks):
        assert block["cards"][0]["area"] == floor_area_id(floor)
        assert block["cards"][0]["navigation_path"] == f"/{DASHBOARD}/zm-floor-{floor}"


def test_main_floor_lights_are_generated_groups(object_layer, tmp_path):
    """Обе плитки света — наши группы этажа, выведенные из их же имён."""
    from scripts._lib.canon import floor_light_entity, tech_light_entity

    blocks = _floor_blocks(_main_view(_generate(object_layer, tmp_path)))
    for floor, block in zip((1, 2), blocks):
        entities = [t["entity"] for t in block["cards"][1]["cards"]]
        assert entities == [floor_light_entity(floor), tech_light_entity(floor)]


def test_nav_map_matches_helper_options(object_layer, tmp_path):
    """Карта «имя → слаг» и опции input_select строятся из одного источника.

    Сверка идёт по строке состояния: разойдутся на символ — кнопка молча
    покажет «выберите помещение» при выбранном помещении. Поймать это глазами
    почти нельзя, поэтому держим тестом.
    """
    import generate_helpers as HELPERS
    from scripts._lib.filters import Filters
    from scripts._lib.normalized import load_dataset

    helpers = HELPERS.build_payload(load_dataset(object_layer, "spaces"), Filters())
    blocks = _floor_blocks(_main_view(_generate(object_layer, tmp_path)))

    for floor, block in zip((1, 2), blocks):
        options = helpers["input_select"][f"nav_floor_{floor}"]["options"]
        content = block["cards"][3]["content"]

        assert block["cards"][2]["entity"] == f"input_select.nav_floor_{floor}"
        for option in options:
            assert f"'{option}':" in content, (
                f"опции списка нет в карте перехода: {option!r}"
            )


def test_nav_map_slugs_point_at_existing_subviews(object_layer, tmp_path):
    """Каждая ссылка карты ведёт на реально созданный subview."""
    import re

    views = _generate(object_layer, tmp_path)
    blocks = _floor_blocks(_main_view(views))

    for block in blocks:
        for slug in re.findall(r"': '([a-z0-9_]+)'", block["cards"][3]["content"]):
            assert f"zm-space-{slug}" in views, slug


def test_main_title_from_flag(object_layer, tmp_path):
    """Имя объекта в таблице не хранится — приходит флагом."""
    main = _main_view(_generate(object_layer, tmp_path))

    assert main["header"]["card"]["content"] == f"# {DASHBOARD_TITLE}"


def test_main_nav_button_keeps_card_mod(object_layer, tmp_path):
    """CSS кнопки перехода доезжает дословно, в словарной форме с `$`.

    Ссылка живёт внутри ha-markdown со своим shadow-root — строковый style
    до неё не дойдёт, и кнопка останется голой ссылкой.
    """
    blocks = _floor_blocks(_main_view(_generate(object_layer, tmp_path)))
    style = blocks[0]["cards"][3]["card_mod"]["style"]

    assert "ha-markdown$" in style
    assert "display: block" in style["ha-markdown$"]
