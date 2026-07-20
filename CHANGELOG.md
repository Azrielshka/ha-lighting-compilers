# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.
This project follows Semantic Versioning.

---

## [3.0.0] - 2026-07-20

Переезд на новый формат входной таблицы. Влит в `main` 2026-07-17 (`9c0fffd`),
выпущен тегом `v3.0.0` на `3b3b840`.

Релиз проверен на чистой машине: EXE самодостаточен (открывается без PySide6 в
окружении), 331 МБ рантайма достаточно, все 9 шагов пайплайна и деплой на
объект работают.

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
  правил (`E01`–`E16`) и 9 предупреждений (`W01`–`W09`), флаг `--strict`,
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
- **`scripts/generate_helpers.py`** — вспомогательные объекты одним пакетом
  (`includes/packages/zm_lighting-compilers.yaml`): `input_number.vacant_delay`
  (`initial: 10`, `mode: box`, 0–300 с), `input_button.but_back`,
  `input_boolean.regim_auto_<N>` на этаж, 4 пресета зала и
  `input_select.nav_floor_<N>` с опциями-помещениями этажа. Раньше их заводил
  наладчик руками, и забытый всплывал уже на объекте. Пайплайн создаёт **сам
  объект, но не логику за ним** — исключение `vacant_delay` и `nav_floor_<N>`,
  их читает наш код. В `Build All` (шаг 7 из 9).
- **Area на каждый этаж** (`Весь <N> этаж`) — нужна карточке `type: area` на
  Главной: она показывает только Area, карточки для Floor в HA нет. Идут в
  конце списка, чтобы не сдвигать порядок помещений из таблицы. Комнатным
  Areas не конкурент: те наполняет интеграция по устройствам, а групповые
  светильники этажа — YAML-группы без устройства, и попасть могут только сюда.
- **`scripts/deploy.py`** — доставка на Home Assistant. Файлы по **SFTP**
  (add-on «Advanced SSH & Web Terminal»), пространства и этажи по **WebSocket
  API**. Dry-run по умолчанию, `--live` отправляет; идемпотентно. Проверено на
  живом объекте. Рестарт HA деплой не делает — по решению владельца.
  File Editor как транспорт не годится: прокси `/api/hassio/` закрыт белым
  списком (401 при любом токене).
- **`scripts/generate_lovelace_cards.py`** — карточки Lovelace, у каждого
  `space_type` своя раскладка. Сборка «обёртка на тип + атомарные блоки»
  (`templates/lovelace/`): korridor/hall — пары «свет\|датчик» с балансной
  нарезкой по 3 зоны и переносом; special — список пар; class — грид «свет/
  датчик/подпись» (подпись — заглушка); zal — группы + захардкоженные пресеты;
  recreation — узкие группы + датчики в 2 колонки. «Датчиков ≠ зон» решено
  структурно. zal/recreation требуют HACS-карт (mushroom/card_mod). Шаг
  офлайновый, в Build All не входит.
- **Views дашборда вместо экспорта в `.txt`.** Генератор раскладывает карточки
  по views: `zm-floor-<N>` (компактные карточки помещений этажа) и
  `zm-space-<room_slug>` (`subview: true`, полная карточка). Новая компактная
  карточка — заголовок + общий свет + кнопка «Подробнее» с `navigate` в subview.
  Выход — файл на view в `data/lovelace/`; `--dashboard` задаёт url_path.
- **Главная страница** (`templates/lovelace/main/view.yaml`) — генерируется
  целиком: шапка с именем объекта (`--title`) и блок на каждый этаж — карточка
  `type: area` с переходом на этажный view, свет этажа и тех.помещений, список
  выбора помещения и кнопка перехода. Убраны кастомный фон, карточка режима
  работы и виджеты шапки — по решению владельца.
- **Навигация с Главной: 76 карточек `conditional` → одна markdown на этаж.**
  `navigation_path` у штатных карточек статичен, шаблоны в него не
  подставляются — отсюда и брались условия по одному на помещение. Markdown
  поддерживает Jinja и внутренние ссылки: одна карточка, карта «имя → слаг»
  генерируется. Ключи карты и опции `input_select` строятся одним правилом
  (`canon.space_label`) — расхождение на символ молча ломает навигацию, поэтому
  правило одно на проект и покрыто тестом.
- **`INSERT_AT` 1 → 0.** Главную теперь генерируем мы, и она обязана быть первым
  view: дашборд открывается на первом, и туда же ведёт кнопка «назад» с этажей.
- **Шапка и бейджи этажного view** — шаблон `templates/lovelace/floor/view.yaml`
  (правится владельцем, как обёртки помещений): markdown-заголовок «# N Этаж»,
  бейдж света этажа (`light.ves_<N>_i_etazh`), бейдж режима
  (`input_boolean.regim_auto_<N>`) и кнопка «назад» на корень дашборда.
  `path` подставляет код: по префиксу `zm-` деплой отличает свои views, и
  опечатка в нём размножила бы дубли вместо замены.
- **`canon.floor_group_unique_id` / `tech_group_unique_id` / `floor_light_entity`** —
  конвенция entity_id групп этажа переехала из `generate_floor_groups.py` в канон:
  на неё ссылаются два генератора (один создаёт группу, второй кладёт её в бейдж),
  а два источника правды разъехались бы на первой правке.
- **`scripts/_lib/ha_views.py`** — чистая логика views: пути, порядок, слияние
  с конфигом дашборда. Вынесена отдельно и покрыта тестами, потому что
  `lovelace/config/save` перезаписывает дашборд целиком.
- **Деплой карточек** — цель `lovelace` в `deploy.py`, канал WebSocket:
  прочитать конфиг дашборда → слить (свои views по префиксу `zm-` заменить,
  ручные views владельца сохранить, наши поставить в начало) → записать. Дашборд остаётся UI-редактируемым, рестарт не нужен.
  Требует токен **администратора**.
- **`scripts/show_normalized.py`** — просмотр parquet (бинарь, глазами не открыть).
- **`scripts/_lib/schemas.py`** — схемы Arrow, объявленные явно.
- **`scripts/_lib/normalized.py`** — чтение слоя со сверкой схемы.
- **`scripts/_lib/filters.py`**, **`_lib/yaml_render.py`** — общая логика,
  которая была скопирована в трёх генераторах дословно.
- **Тесты** — 460, включая приёмочные на реальной фикстуре и проверку
  замкнутости иерархии (лампы → зоны → общая группа → этаж; автоматизация →
  скрипт → blueprint).
- **Тип помещения `Hall`** и `sensor.il_*` (датчик освещённости) в каноне.
- Launcher: кнопки `Validate`, `Areas`, `Scripts`, `Automations`, галочка
  `Strict`, «Открыть папку с результатами». `Build All` — 9 шагов, офлайновый.
- **Секция «Сервис» на Главной** — кнопки на страницы расписания и
  конфигурации (`canon.SERVICE_VIEWS`). Штучные, из таблицы не выводятся.
  Вспомогательных объектов не требуют: навигация статическая.
- **Посев страниц вместо генерации.** Заготовки сервисных страниц деплой
  создаёт, только если их ещё нет, и больше не трогает никогда. Пути у них
  намеренно **без** префикса `zm-`: наполняет их владелец, значит они его, а
  правило слияния «`zm-` — наше, перезаписываем» остаётся однострочным, без
  исключений. Расписание высевается как `type: panel` («Панель, 1 карточка»).
- **Оформление лаунчера** (`launcher/ui/theme.py`) — светлая база, приборная
  геометрия, моноширинный лог. Два акцента с разными ролями: циан — структура,
  пурпур — только действие (наведение, фокус, нажатие). В покое окно холодное.
  Правило держится тестом, который разбирает QSS.
- **Шапка окна** (`launcher/ui/widgets.py`) — имя, версия (`launcher.__version__`)
  и декаль. Версия на экране затем, чтобы наладчик называл её, а не искал в
  свойствах файла. Плюс иконка окна: раньше в панели задач стояла заглушка Qt.
- **`tools/make_icon.py`** — `.ico` для EXE из того же SVG, что красит окно.
  Собирается в CI, в репозиторий не коммитится: производная, второй источник
  правды. ⚠ `--icon` (файл в Проводнике) и `setWindowIcon` (окно запущенной
  программы) — разные вещи, нужны обе.
- **Сверка версии с тегом в CI.** Тег `v3.0.0` при `__version__ = "3.0.0-dev"`
  раздал бы сборку, которая называет себя не своим именем. Сборка падает.
- **Зависимости разведены на три файла** (2026-07-20): `requirements.txt` —
  рантайм скриптов, едет в релизный архив; `requirements-gui.txt` — PySide6 для
  лаунчера из исходников и сборки EXE; `requirements-dev.txt` — всё плюс pytest
  и pyinstaller. Пользователь ставит **331 МБ вместо 993**: PySide6 ему не нужен
  вовсе — ни один скрипт его не импортирует, а в архив едет собранный
  `launcher.exe` с уже упакованной библиотекой. Проверено прогоном всех 14
  скриптов в чистом окружении без PySide6.
- **`THIRD-PARTY-LICENSES.md`** — декаль собрана из иконок [Lucide](https://lucide.dev)
  (ISC). ⚠ ISC требует копирайт и текст лицензии **во всех копиях**: текст лежит
  строкой в `decals.LUCIDE_NOTICE` (внутри EXE) и файлом в релизном архиве.
  Файл-ресурс потребовал бы `--add-data`, и забытый флаг превратил бы нарушение
  лицензии в тихую ошибку сборки.

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
- **Конфиг лаунчера стирал сам себя.** `ConfigStore.save()` перезаписывает файл
  целиком, а окно сохраняло через него свои три поля — и при каждом старте,
  закрытии и правке пути из конфига вылетали хост, ключ, токен и имя объекта.
  Молча: наладчик просто вводил их заново каждый запуск. Добавлен
  `ConfigStore.update()`; `save()` остался полной перезаписью — это его контракт.
- **Поля «Объект» и «Дашборд» переехали в главное окно.** Стояли в диалоге
  Deploy, а читает их **генерация** карточек: правишь имя, жмёшь Deploy — а в
  шапке старое, потому что деплой ничего не генерирует, он льёт готовые файлы.
- **Текст кнопок обрезался на маленьком экране.** Четырнадцать кнопок требовали
  панели 689px, окну — 1016px. На 1366x768 оконный менеджер ужимал окно ниже
  его же минимума, layout сплющивал кнопки, и от подписи оставалась полоска по
  центру. Кнопки уехали в `QScrollArea`, минимум окна 1016 → 472px.
- **Декаль масштабировалась дважды.** `setDevicePixelRatio` уже переводит
  координаты в логические, а отрисовка шла в прямоугольник `width * ratio`.
  При 150% рисунок раздувался и обрезался: из пяти иконок было видно три.
  На 100% дефект невидим — оба этих бага нашёл владелец, не разработка.
- **Плитка тех.помещений висела на этажах без такой группы.** Ставилась
  безусловно, а `generate_floor_groups` заводит группу только там, где есть
  korridor / special / recreation.
- **Заголовок этажного бейджа ссылался на несуществующую сущность.**
  `unique_id` — это **не** `entity_id`: у YAML-платформы `light: - platform:
  group` идентификатор выводится из `name` через slugify, поэтому группа с
  `name: «Весь 1-й этаж»` живёт как `light.ves_1_i_etazh`, а `light.floor_1_all`
  не существует вовсе.

### Known limitations

Система собрана, но на объекте свет не включится, пока не появится одна вещь
вне пайплайна:

- **JSON Zone Manager** собирается вручную → `get_sensor_config` вернёт
  `found: false` → свет не будет включаться. Помощником не является — шагом
  `generate_helpers.py` не закрывается.

`input_number.vacant_delay` из этого списка **ушёл**: с 2026-07-17 его создаёт
`generate_helpers.py` со значением по умолчанию.

Карточки типов `zal` и `recreation` требуют HACS-карт (mushroom, card_mod):
без них view отрисуется с ошибкой.

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