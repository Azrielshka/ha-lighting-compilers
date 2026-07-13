# -*- coding: utf-8 -*-
"""
schemas.py
Схемы нормализованного слоя (parquet), объявленные ЯВНО.

Зачем этот файл существует
--------------------------
pa.Table.from_pandas() выводит типы из данных. Если колонка пуста во всей
таблице, выводить не из чего — и Arrow ставит туда тип `null`.

Практический результат: на объекте без единой панели `panels_by_group`
получал тип list<list<null>> вместо list<list<string>>, а `warnings` менял
тип в зависимости от того, были ли предупреждения. То есть СХЕМА ФАЙЛА
ЗАВИСЕЛА ОТ ДАННЫХ, и генератор, читающий такой файл, ломался бы не у нас,
а у наладчика на объекте, который мы никогда не видели.

Поэтому схема здесь прибита гвоздями. normalize пишет строго по ней:
если данные схеме противоречат, Arrow падает при записи — это и нужно.

Этот файл — единственный ответ на вопрос «что лежит в нормализованном слое».
Человеческое описание: docs/internal/data_model_v2.md
"""

from __future__ import annotations

from typing import Dict

import pyarrow as pa

# Списки entity_id. Отдельными константами, чтобы вложенность
# sensors_by_group читалась глазами, а не расшифровывалась.
_ENTITY_LIST = pa.list_(pa.string())
_ENTITY_LIST_BY_GROUP = pa.list_(_ENTITY_LIST)


# ============================================================
# devices.parquet — строка = ОДНО устройство
# ============================================================

DEVICES_SCHEMA = pa.schema([
    # Номер строки в Excel: чтобы наладчик мог вернуться к своей таблице.
    ("row_id",      pa.int64()),

    # lamp | sensor | panel
    ("kind",        pa.string()),

    # Адрес DALI как в таблице, и он же разобранный.
    # Именно адрес — истина об этаже и шине (колонки Excel справочные).
    ("addr",        pa.string()),
    ("addr_floor",  pa.int64()),
    ("addr_bus",    pa.int64()),
    ("addr_num",    pa.int64()),

    # Предсказанные сущности HA. entity_id_2 заполнен ТОЛЬКО у датчиков
    # (sensor.il_*) — у ламп и панелей он null, но тип всё равно string.
    ("entity_id",   pa.string()),
    ("entity_id_2", pa.string()),

    # Группа из этой же строки Excel — сердце модели v2.
    ("group_id",    pa.string()),

    ("space",       pa.string()),
    ("room_slug",   pa.string()),

    # Из колонки «Этаж». Именно она идёт в floor_<n>_all.
    ("floor",       pa.int64()),

    # null, если тип помещения не указан.
    ("space_type",  pa.string()),

    # Справочно, в генерации не участвует.
    ("dali_bus",    pa.string()),
])


# ============================================================
# groups.parquet — строка = группа света (зона)
# ============================================================

GROUPS_SCHEMA = pa.schema([
    ("group_id",          pa.string()),
    ("space",             pa.string()),
    ("room_slug",         pa.string()),
    ("floor",             pa.int64()),
    ("space_type",        pa.string()),

    # light.<group_id>
    ("zone_light_entity", pa.string()),

    # Порядок элементов — как в Excel: наладчик сверяет YAML со своей таблицей.
    ("lamps",             _ENTITY_LIST),

    # 0..N датчиков на группу. sensors_il параллелен sensors_ms:
    # один адрес датчика даёт обе сущности.
    ("sensors_ms",        _ENTITY_LIST),
    ("sensors_il",        _ENTITY_LIST),

    # 0..N панелей на группу.
    ("panels",            _ENTITY_LIST),

    ("lamp_count",        pa.int64()),
    ("sensor_count",      pa.int64()),
    ("panel_count",       pa.int64()),
])


# ============================================================
# spaces.parquet — строка = помещение
# ============================================================

SPACES_SCHEMA = pa.schema([
    ("space",                pa.string()),
    ("room_slug",            pa.string()),
    ("floor",                pa.int64()),
    ("space_type",           pa.string()),

    # Ворота для карточек: False -> Lovelace не рисуем,
    # но группы света всё равно создаём (лампы физически есть).
    ("has_valid_type",       pa.bool_()),

    ("groups",               _ENTITY_LIST),
    ("groups_count",         pa.int64()),

    # light.<room_slug>_obshchii
    ("general_light_entity", pa.string()),
    ("zone_light_entities",  _ENTITY_LIST),

    # sensors_by_group[i] относится к groups[i].
    # Пустой вложенный список = у группы нет датчиков (норма для zal).
    ("sensors_by_group",     _ENTITY_LIST_BY_GROUP),
    ("panels_by_group",      _ENTITY_LIST_BY_GROUP),

    ("sensors_unique",       _ENTITY_LIST),

    # missing_space_type | unknown_space_type:<что было в таблице>
    ("warnings",             _ENTITY_LIST),
])


# Имя датасета -> схема. Порядок задаёт порядок записи и вывода.
SCHEMAS: Dict[str, pa.Schema] = {
    "devices": DEVICES_SCHEMA,
    "groups": GROUPS_SCHEMA,
    "spaces": SPACES_SCHEMA,
}

DATASET_NAMES = tuple(SCHEMAS)
