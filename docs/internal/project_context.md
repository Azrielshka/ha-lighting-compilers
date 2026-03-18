# Project Context — ha-college-lighting

## Назначение проекта

Проект **ha-college-lighting** генерирует конфигурацию освещения для **Home Assistant** на основе Excel-таблицы.

Pipeline проекта:

```
Excel → normalize → parquet → generators → YAML → Lovelace
```

Excel является **единственным источником данных**.

---

# Архитектура пайплайна

```
Excel (.xlsx)
      ↓
scripts/normalize_excel.py
      ↓
data/normalized/
    device_rows.parquet
    spaces.parquet
    normalized_meta.json
      ↓
генераторы
    generate_lights_groups.py
    generate_general_groups.py
    generate_floor_groups.py
    generate_lovelace_cards_v2.py
      ↓
data/light_groups/
    lights_group.yaml
    lights_general_groups.yaml
    lights_floor_groups.yaml
```

---

# Основные принципы архитектуры

1. Excel читается **только один раз** (в normalize_excel.py)

2. Все генераторы работают только с **parquet слоем**

3. Правила нейминга централизованы

4. Генераторы не должны:
   - читать Excel
   - парсить YAML других генераторов
   - дублировать правила канона

5. YAML генерируется **текстом**, а не сериализацией

---

# Нормализованный слой данных

## device_rows.parquet

Содержит строки устройств

Используется для генерации:
- подгрупп света

Основные поля:

```
space
room_slug
floor
group_id
lamp_id
sensor_id
card_type
```

---

## spaces.parquet

Агрегированные данные помещений

Используется для:
- генерации общих групп помещений
- генерации групп этажей
- генерации Lovelace карточек

Основные поля:

```
space
room_slug
floor
card_type
groups
groups_count
general_light_entity
ms_sensors_by_group
```

---

# Канон проекта

Все правила нейминга находятся в:

```
scripts/_lib/canon.py
```

---

## Entity лампы

```
lamp_id: 1.20.15
→ light.l_1_20_15
```

Функция:

```
normalize_lamp_id_to_entity()
```

---

## Общая группа помещения

```
light.<room_slug>_obshchii
```

пример:

```
403_kabinet_medits
→ light.403_kabinet_medits_obshchii
```

---

## Технические помещения

Типы технических помещений задаются:

```
TECHNICAL_CARD_TYPES
```

пример:

```
corridor
su
lestnitsa
```

---

# Иерархия групп света

```
лампы
   ↓
подгруппы света
   ↓
общая группа помещения
   ↓
группа этажа
```

---

# Генераторы

## normalize_excel.py

Назначение:
- читает Excel
- нормализует данные
- сохраняет parquet

Выход:

```
data/normalized/
```

---

## generate_lights_groups.py

Создаёт:

```
light.<group_id>
```

пример:

```
light.403_0
light.403_1
light.403_2
```

Источник:

```
device_rows.parquet
```

---

## generate_general_groups.py

Создаёт общую группу помещения:

```
light.<room_slug>_obshchii
```

Источник:

```
device_rows.parquet
```

---

## generate_floor_groups.py

Создаёт:

### группу всего этажа

```
floor_<n>_all
```

### группу технических помещений

```
tex_floor_<n>
```

Источник:

```
spaces.parquet
```

---

## generate_lovelace_cards_v2.py

Генерирует карточки Lovelace

Источник:

```
spaces.parquet
```

Использует:

```
templates/
manifest.yaml
```

---

# Launcher v1 (GUI)

## Назначение

Launcher — это GUI-оболочка для управления pipeline.

Он позволяет запускать генерацию без терминала.

---

## Архитектурная роль

```
Excel → normalize → parquet → generators → YAML → Lovelace
                        ↑
                     Launcher
```

Launcher:
- управляет запуском шагов
- передаёт параметры
- отображает лог
- не содержит бизнес-логики

---

## Расположение

```
launcher/
├── main.py
├── ui/
│   └── main_window.py
├── services/
│   ├── process_runner.py
│   └── config_store.py
```

---

## Возможности

- выбор Project Root
- выбор Excel файла
- запуск отдельных шагов
- запуск Build All
- лог выполнения
- очистка логов
- сохранение конфигурации

---

## Execution model

- запуск через `subprocess`
- каждый шаг = отдельный Python процесс
- pipeline выполняется последовательно

---

## Определение Python

```
<Project Root>/.venv/Scripts/python.exe
```

---

## Конфигурация

```
launcher/config/launcher_config.json
```

---

## Ограничения

- синхронное выполнение
- UI блокируется во время выполнения
- лог появляется после завершения шага
- возможна очередь кликов

---

## EXE сборка

```
pyinstaller --noconfirm --windowed --name ha_launcher_v1 launcher/main.py
```

Результат:

```
dist/ha_launcher_v1/
```

---

## Важно

Launcher:
- не автономный
- требует проект
- использует `.venv`
- является orchestration layer

---

# Bootstrap для CLI

CLI-скрипты используют:

```
scripts/_lib/bootstrap.py
```

Добавляет корень проекта в `sys.path`

---

# Структура проекта

```
ha-college-lighting/

data/
  normalized/
  light_groups/

docs/
  internal/
    architecture_rules.md
    project_context.md

launcher/
  main.py
  ui/
  services/
  config/

scripts/
  normalize_excel.py
  generate_lights_groups.py
  generate_general_groups.py
  generate_floor_groups.py
  generate_lovelace_cards_v2.py

scripts/_lib/
  bootstrap.py
  canon.py
  naming.py
  excel_schema.py

templates/

CHANGELOG.md
README.md
requirements.txt
```

---

# Краткое описание проекта (30 секунд)

Проект генерирует конфигурацию освещения Home Assistant из Excel.

Pipeline:

```
Excel
→ normalize_excel
→ parquet
→ generators
→ YAML
→ Lovelace cards
```

Все генераторы работают с **нормализованным parquet слоем**, а не с Excel.

Launcher предоставляет GUI для управления этим pipeline.