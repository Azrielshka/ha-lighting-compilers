# Архитектура пайплайна генерации освещения (v2.0.x)

⚠️ Документ предназначен для разработчиков проекта.

Документ фиксирует архитектуру генераторов YAML и Lovelace карточек
в проекте ha-college-lighting начиная с версии 2.0.x.

---

# Архитектура пайплайна

Excel является единственным источником данных.

Pipeline работы системы:

Excel (.xlsx)
↓
normalize_excel.py
↓
data/normalized/
├ device_rows.parquet
├ spaces.parquet
└ normalized_meta.json
↓
Генераторы YAML
├ generate_lights_groups.py
├ generate_general_groups.py
└ generate_floor_groups.py
↓
data/light_groups/
├ lights_group.yaml
├ lights_general_groups.yaml
└ lights_floor_groups.yaml

---

# Нормализованный слой

## device_rows.parquet

Содержит строки устройств.

Используется для генерации:

* подгрупп света

Поля:

space
room_slug
floor
group_id
lamp_id
sensor_id
card_type

---

## spaces.parquet

Содержит агрегированные помещения.

Используется для генерации:

* общих групп помещений
* групп этажей
* Lovelace карточек

Поля:

space
room_slug
floor
card_type
groups
groups_count
general_light_entity
ms_sensors_by_group

---

# Канон проекта

Все правила нейминга находятся в:

scripts/_lib/canon.py

Там определены:

GENERAL_LIGHT_RULE
TECHNICAL_CARD_TYPES
normalize_lamp_id_to_entity()

Генераторы не должны дублировать правила.

---

# Иерархия групп света

лампы
↓
подгруппы света
↓
общая группа помещения
↓
группа этажа

---

# Подгруппы света

Генератор:

generate_lights_groups.py

Источник данных:

device_rows.parquet

Пример entity:

light.403_0
light.403_1
light.403_2

---

# Общая группа помещения

Генератор:

generate_general_groups.py

Entity:

light.<room_slug>_obshchii

Пример:

light.403_kabinet_medits_obshchii

---

# Группа всего этажа

Генератор:

generate_floor_groups.py

Пример:

name: "Весь 4-й этаж"
unique_id: "floor_4_all"

---

# Технические помещения этажа

Опциональная генерация:

GENERATE_TECH_GROUPS = 1

Пример:

name: "Тех.пом 4-й этаж"
unique_id: "tex_floor_4"

Типы технических помещений задаются:

TECHNICAL_CARD_TYPES

---

# Фильтры генераторов

Все генераторы поддерживают:

SPACES_FILTER
EXCLUDE_FLOORS
EXCLUDE_SPACE_CONTAINS

Дополнительно для этажей:

INCLUDE_FLOORS

---

# Выходные YAML

Все YAML генерируются в:

data/light_groups/

Структура:

lights_group.yaml
lights_general_groups.yaml
lights_floor_groups.yaml

---

# Lovelace генератор

Карточки генерируются скриптом:

generate_lovelace_cards_v2.py

Источник данных:

spaces.parquet

---

# Архитектурные принципы

1. Excel читается только один раз.
2. Все генераторы работают с parquet слоем.
3. Все правила нейминга находятся в canon.py.
4. Генераторы не читают Excel напрямую.
5. Генераторы не парсят YAML других генераторов.
6. YAML генерируется как текст.

---

# 🖥 Launcher (GUI execution layer)

## Назначение

Launcher является GUI-оболочкой для управления пайплайном генерации:

Excel → normalize → parquet → generators → YAML → Lovelace

Launcher НЕ содержит бизнес-логики и НЕ заменяет скрипты.

---

## Архитектурная роль

```text
Excel → normalize → parquet → generators → YAML → Lovelace
                        ↑
                     Launcher
```

Launcher:
- управляет запуском шагов
- передаёт параметры (например, путь к Excel)
- отображает лог выполнения
- НЕ вмешивается в обработку данных

---

## Принципы

1. Launcher не содержит бизнес-логики  
   Вся логика обработки данных находится только в `scripts/`

2. Launcher работает через subprocess  
   Каждый шаг pipeline запускается как отдельный Python-процесс

3. Launcher не читает Excel или parquet  
   Только передаёт параметры в CLI

4. Скрипты остаются CLI-first  
   Любой скрипт должен запускаться без launcher

5. Normalize поддерживает два режима  
   - standalone (внутренний путь)
   - launcher (`--excel`)

---

## Ограничения (v1)

- Синхронное выполнение (`subprocess.run`)
- UI блокируется во время выполнения
- `stdout/stderr` отображается после завершения процесса
- Возможна очередь пользовательских кликов (ограничение Qt event loop)

---

## Принятые решения

- НЕ использовать threading в v1
- НЕ внедрять бизнес-логику в launcher
- НЕ объединять pipeline в один процесс
- Launcher — только orchestration layer

---

## Будущее развитие (v2+)

- Переход на `QThread` или `QProcess`
- Streaming логов в реальном времени
- Полная блокировка пользовательского ввода
- Возможный отказ от subprocess в пользу import pipeline