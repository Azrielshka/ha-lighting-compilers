# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.
This project follows Semantic Versioning.

---

## [3.0.0] - Unreleased

Переезд на новый формат входной таблицы. Работа идёт в ветке `feat/table-v2`.

> **Нумерация.** Теги релизов шли `v1.0.2 … v1.0.5`, а CHANGELOG дошёл до
> `2.1.0` — они разъехались. Следующий тег будет `v3.0.0`, и с него нумерация
> едина.

### ⚠ BREAKING

- **Формат входной таблицы несовместим со старым.** Читается лист
  «Проектная БД»; колонки `(авто)` и `card_type` исчезли, появились
  «Тип помещения» и «Блок». Старый `data/example.xlsx` остаётся в репозитории
  как исторический артефакт: пайплайн v3 на нём не работает — валидатор скажет
  «нет листа "Проектная БД"», и это ожидаемое поведение.
- **Устройство принадлежит группе из своей строки.** Раньше группа задавалась
  только на стартовой строке, а датчик привязывался к ней через `is_group_start`.
  Понятия `is_group_start` больше нет.
- **У группы 0..N датчиков и панелей.** Схема v1 хранила один датчик на группу
  и второй молча теряла — это был главный дефект, ради которого затевался
  переезд.
- **`device_rows.parquet` упразднён.** Нормализованный слой — `devices`,
  `groups`, `spaces`, `units` (`schema_version = 3`).
- **Тип `generic` и fallback `nearest_variant` упразднены.** Помещение без типа
  не подставляется в случайный шаблон, а честно пропускается на карточках; в
  группы света оно при этом попадает — лампы в нём физически существуют.
- **Фильтры генераторов переехали из констант в исходнике в CLI-флаги.**
  Раньше, чтобы исключить этаж, наладчику пришлось бы править код.

### Added

- **`scripts/validate_excel.py`** — новый первый шаг пайплайна. 16 блокирующих
  правил (`E01`–`E16`) и 8 предупреждений (`W01`–`W08`), флаг `--strict`,
  JSON-отчёт, коды возврата `0/1/2`.
- **Единицы обслуживания** (колонка «Блок») и датасет `units.parquet`. Единица —
  помещение либо все помещения одного блока.
- **`scripts/generate_scripts.py`** — клоны шаблонных скриптов по единицам.
  Один экземпляр скрипта в HA — это одна очередь; при тысяче датчиков вызовы
  копятся и свет отстаёт от человека, поэтому у каждой единицы свой набор.
- **`scripts/generate_automations.py`** — экземпляры blueprint'ов, по две на
  единицу (ON и OFF), плюс копии blueprint'ов для деплоя. Кладутся в **пакет**,
  а не в `automations.yaml`: туда HA пишет автоматизации, созданные через UI.
- **`scripts/generate_areas.py`** — пространства и этажи Home Assistant.
  Шаг офлайновый: готовит задание, в HA не пишет.
- **`scripts/show_normalized.py`** — просмотр parquet (бинарь, глазами не открыть).
- **`scripts/_lib/schemas.py`** — схемы Arrow, объявленные явно.
- **`scripts/_lib/normalized.py`** — чтение слоя со сверкой схемы.
- **`scripts/_lib/filters.py`**, **`_lib/yaml_render.py`** — общая логика,
  которая была скопирована в трёх генераторах дословно.
- **Тесты** — 250, включая приёмочные на реальной фикстуре и проверку
  замкнутости иерархии (лампы → зоны → общая группа → этаж; автоматизация →
  скрипт → blueprint).
- **Тип помещения `Hall`** и `sensor.il_*` (датчик освещённости) в каноне.
- Launcher: кнопки `Validate`, `Areas`, `Scripts`, `Automations`, галочка
  `Strict`, «Открыть папку с результатами». `Build All` — 8 шагов, офлайновый.

### Fixed

- **Висячие сущности в группах этажа.** У `generate_general_groups.py` стояло
  `EXCLUDE_SPACE_CONTAINS = ["koridor"]` — артефакт отладки перед ПНР. Коридоры
  не получали общую группу, но `generate_floor_groups.py` всё равно тянул их
  `general_light_entity` в группу этажа: в HA появлялась группа, ссылающаяся на
  несуществующую сущность.
- **Плавающая схема parquet.** `pa.Table.from_pandas()` выводил типы из данных:
  на объекте без единой панели `panels_by_group` получал тип `list<list<null>>`
  вместо `list<list<string>>`. Схема файла зависела от объекта — сломалось бы
  не у разработчика, а у наладчика.
- **`"None"` превращался в `NaN`.** Строка `None` входит в `na_values` pandas по
  умолчанию, и различие между «устройства нет» и «ячейка не заполнена» исчезало
  при чтении.
- Порядок сущностей в YAML — как в таблице (раньше `generate_floor_groups.py`
  сортировал по алфавиту). Наладчик сверяет YAML со своим Excel.

### Known limitations

Система собрана, но на объекте не заработает, пока не появятся две вещи —
обе вне пайплайна по решению владельца:

- **`input_number.vacant_delay`** никто не создаёт → OFF-триггер вернёт
  `unknown` → свет не будет гаснуть.
- **JSON Zone Manager** собирается вручную → `get_sensor_config` вернёт
  `found: false` → свет не будет включаться.

Не переехал генератор карточек Lovelace (ждёт новые шаблоны). Деплой не сделан.

---

## [2.1.0] - 2026-03-18

### Added

- Реализован **Launcher v1 (GUI на PySide6)** для управления пайплайном генерации.
- Добавлена структура модуля launcher:
  - `launcher/main.py` — точка входа
  - `launcher/ui/main_window.py` — пользовательский интерфейс
  - `launcher/services/process_runner.py` — запуск subprocess
  - `launcher/services/config_store.py` — сохранение конфигурации

- Добавлен запуск отдельных этапов pipeline из GUI:
  - `normalize_excel`
  - `generate_lights_groups`
  - `generate_general_groups`
  - `generate_floor_groups`
  - `generate_lovelace_cards_v2`

- Добавлен режим **Build All** (последовательное выполнение pipeline).

- Добавлено сохранение конфигурации между запусками:
  - `Project Root`
  - `Excel File Path`
  - хранение в `launcher/config/launcher_config.json`

- Добавлено автоматическое определение Python интерпретатора:
  ```text
  <project_root>/.venv/Scripts/python.exe
  ```

- Добавлена поддержка dual-mode для `normalize_excel.py`:
  - standalone режим (внутренний путь)
  - launcher режим (`--excel`)

- Добавлены элементы GUI:
  - окно логов выполнения
  - кнопка `Clear Log`
  - выбор файлов и папок через диалоги

- Добавлена сборка launcher в EXE через PyInstaller.

### Changed

- Упрощён UI launcher:
  - удалено поле `Python Interpreter`
  - используется автоматическое определение Python

- Улучшено логирование:
  - добавлены стартовые сообщения перед выполнением
  - улучшена читаемость pipeline
  - добавлена очистка логов

- Добавлена автоподстановка стартовых путей:
  - `Project Root`
  - `Excel File Path`

### Fixed

- Исправлена проблема кодировки при запуске subprocess из GUI на Windows:
  - принудительно включён UTF-8 режим для дочерних Python-процессов

- Исправлена проблема позднего отображения стартовых сообщений в логе:
  - добавлен принудительный flush UI перед запуском блокирующего subprocess

### Notes

- Launcher реализован как orchestration layer и не содержит бизнес-логики обработки данных.
- `normalize_excel.py` продолжает поддерживать прямой CLI-запуск без launcher.
- Текущая версия launcher использует синхронное выполнение через `subprocess.run`.

### Known limitations

- Выполнение синхронное (`subprocess.run`)
- `stdout/stderr` выводится после завершения процесса
- UI блокируется во время выполнения
- Возможна очередь пользовательских кликов при быстром вводе

## [2.0.2] - 2026-03-05

### Added
- Optional generation of technical room groups per floor in `generate_floor_groups.py`.
- New flag `GENERATE_TECH_GROUPS` to enable/disable technical floor groups.
- Canonical rule `TECHNICAL_CARD_TYPES` added to `scripts/_lib/canon.py`.
- Added helper `scripts/_lib/bootstrap.py` to ensure project root is added to PYTHONPATH when running generators directly.

### Changed
- Generators now call `setup_project_path()` before importing project modules.
- `generate_floor_groups.py` now reads `spaces.parquet` instead of `device_rows.parquet`.
- Floor grouping uses canonical `general_light_entity` values from normalized data.

## [2.0.1] - 2026-03-05

### Changed
- `generate_lights_groups.py` now reads normalized data from `data/normalized/device_rows.parquet` instead of Excel.
- Lamp entity generation moved to canonical rule `normalize_lamp_id_to_entity()` in `scripts/_lib/canon.py`.
- `generate_general_groups.py` refactored to read normalized data from `data/normalized/device_rows.parquet` instead of Excel.
- Output moved to `data/light_groups/lights_general_groups.yaml`.
- General light group IDs now follow canonical rule `<room_slug>_obshchii` (via `GENERAL_LIGHT_RULE`).
- `generate_floor_groups.py` refactored to read normalized data from `data/normalized/device_rows.parquet` instead of parsing `lights_general_groups.yaml`.
- Output moved to `data/light_groups/lights_floor_groups.yaml`.
- Floor groups now include canonical general room groups (`light.<room_slug>_obshchii`) built via `GENERAL_LIGHT_RULE`.
2) Команды в терминале PyCharm
### Added
- Shared naming rule `normalize_lamp_id_to_entity()` for consistent Home Assistant entity IDs across generators.

## [2.0.0] - 2026-03-05

### Added

- Introduced **data normalization layer** (`normalize_excel.py`).
- Added canonical dataset generation:
  - `data/normalized/device_rows.parquet`
  - `data/normalized/spaces.parquet`
  - `data/normalized/normalized_meta.json`
- Added parquet-based data pipeline for further generators.
- Added support for **template-based Lovelace card generation**.
- Implemented `manifest.yaml` + YAML template system ("Card Bestiary").
- Added automatic placeholder replacement in templates:
  - `[[HEADING]]`
  - `[[SPACE]]`
  - `[[GENERAL_LIGHT_ENTITY]]`
  - `[[ZONE_LIGHT_i]]`
  - `[[MS_SENSOR_i]]`
- Added `lovelace_cards_report.json` generation for debugging template selection.
- Added project `requirements.txt`.

---

### Changed

- Lovelace card generation now uses **normalized parquet data** instead of direct Excel parsing.
- Sensor entity naming updated: sensor.1_20_3 → sensor.ms_1_20_3

- Motion sensors now explicitly marked with `ms_` prefix.
- Normalizer now guarantees **unique motion sensors per zone**.
- Improved logging when running `normalize_excel.py`.

---

### Technical

- Added project-wide canonical rules in `scripts/_lib`:
  - `canon.py`
  - `naming.py`
  - `excel_schema.py`
- Added support for running scripts both via:
  - PyCharm Run button
  - CLI execution

---

### Notes

- `general_light_entity` naming remains: light.<room_slug>_obshchii

Example:
light.403_kabinet_medits_obshchii
light.404_lestnitsa_obshchi

- Motion sensors are generated as: sensor.ms_<id>

Example: sensor.ms_1_20_3

## [1.1.2] - 2026-03-03

### Fixed
- Fixed incorrect relative paths when running scripts from /scripts directory
- Implemented BASE_DIR project root resolution for all generators
- Resolved FileNotFoundError when executing via PyCharm

### Improved
- Updated transliteration logic to match Home Assistant slug rules
  - щ → shch
  - ц → ts
  - х → kh
- Reduced entity_id mismatches (~15% → 0%)

---

## [1.1.1] - 2026-03-03

### Attempted Fix
- Added BASE_DIR path resolution (contained structural error)

---

## [1.1.0] - 2026-03-03

### Added
- HA-compatible transliteration logic in generate_floor_groups
- Improved entity_id consistency

---

## [1.0.0] - 2026-01-14

### Initial Release
- generate_general_groups.py
- generate_lights_groups.py
- generate_floor_groups.py
- YAML generation from Excel table