# ha-lighting-compilers

Генератор конфигурации Home Assistant для управления освещением DALI на основе
одной Excel-таблицы. Запускается на машине наладчика (Windows), готовит YAML и
опционально доставляет его на HAOS. Это **не** интеграция Home Assistant.

---

# 1. Устройство проекта

## Идея

Проектировщик заполняет **одну** Excel-таблицу с именами будущих устройств.
Из неё пайплайн собирает всю конфигурацию HA: группы света, пространства,
помощников, скрипты, автоматизации, карточки — и кладёт на сервер.

```
Excel  →  проверка  →  нормализация  →  генераторы  →  YAML  →  деплой на HA
```

Excel читается **один раз** (в normalize). Дальше всё работает с parquet —
генераторы саму таблицу не открывают.

## Структура папок

```
ha-lighting-compilers/
├── scripts/              генераторы и деплой — вся логика здесь
│   └── _lib/             общее: canon.py (имена), schemas.py (схема parquet),
│                         ha_ssh/ha_ws/ha_views (транспорт и слияние views)
├── templates/            то, что правит владелец, не трогая код
│   ├── lovelace/         обёртки карточек по типам помещений + блоки
│   ├── scripts/          шаблоны скриптов HA
│   └── blueprints/       blueprint'ы автоматизаций
├── launcher/             GUI: окно, диалог деплоя, тема, графика
├── tests/                pytest; часть требует PySide6 и без него пропускается
├── tools/                make_icon.py — .ico для EXE, зовётся из CI
├── docs/                 документация (см. раздел 4)
├── data/                 ВХОД и ВЫХОД
│   ├── object_example.xlsx   рабочая фикстура v3
│   ├── example.xlsx          артефакт v1, пайплайн v3 на нём не работает
│   ├── normalized/           parquet — промежуточный слой
│   ├── light_groups/  areas/  helpers/  scripts/  automations/  blueprints/
│   ├── lovelace/             views дашборда
│   └── backups/              снимки дашборда (создаётся при первом бэкапе)
└── .github/workflows/    release.yml — сборка EXE по тегу
```

Содержимое `data/` (кроме таблиц) — результат работы, он в `.gitignore`.
`handoff/` в репозитории нет: это пакет на отдачу третьей стороне, собирается
отдельно.

## Ключевые понятия

**Устройство принадлежит группе, указанной в его строке.** Лампа, датчик и
панель в одной строке Excel — это разные устройства одной группы. У группы
может быть 0..N датчиков и панелей.

**Единица обслуживания** (колонка «Блок»): помещение либо все помещения одного
блока. На каждую клонируется свой набор скриптов — один экземпляр скрипта в HA
это одна очередь, и при тысяче датчиков свет отставал бы от человека.

**Канон имён** живёт в `scripts/_lib/canon.py` — генераторы его не дублируют.

Предсказываем (создаёт сторонняя интеграция, имена гарантированы заказчиком):

| Объект | entity_id |
|---|---|
| лампа | `light.l_1_20_15` |
| датчик движения | `sensor.ms_1_20_3` |
| датчик освещённости | `sensor.il_1_20_3` |
| панель | `event.kp_1_1_1` |

Создаём сами — без нас этого в HA не появится:

| Объект | entity_id | Кто генерирует |
|---|---|---|
| зона | `light.<group_id>` | `generate_lights_groups` |
| общая группа помещения | `light.<room_slug>_obshchii` | `generate_general_groups` |
| группа этажа | `light.ves_<N>_i_etazh` | `generate_floor_groups` |
| группа тех.помещений | `light.tekh_pom_<N>_i_etazh` | `generate_floor_groups` |
| Area этажа | `ves_<N>_etazh` | `generate_areas` |
| помощники | `input_number.vacant_delay`, `input_button.but_back`, `input_boolean.regim_auto_<N>`, `input_select.nav_floor_<N>`, пресеты зала | `generate_helpers` |

⚠ **`unique_id` — это не `entity_id`.** У YAML-платформы `light: - platform:
group` идентификатор выводится из **имени** через slugify, а `unique_id` только
регистрирует запись в реестре. Группа с `name: «Весь 1-й этаж»` живёт как
`light.ves_1_i_etazh`; `light.floor_1_all` не существует. Ссылаться на наши
группы — только через билдеры канона. Подробности — `data_model.md`.

---

# 2. Порядок работы

## Пайплайн — 9 шагов

| # | Скрипт | Делает |
|---|---|---|
| 1 | `validate_excel.py` | проверяет таблицу; на ошибках пайплайн останавливается |
| 2 | `normalize_excel.py` | Excel → `devices` / `groups` / `spaces` / `units` parquet |
| 3 | `generate_lights_groups.py` | подгруппы света (зоны) → `lights_group.yaml` |
| 4 | `generate_general_groups.py` | общие группы помещений → `lights_general_groups.yaml` |
| 5 | `generate_floor_groups.py` | группы этажей → `lights_floor_groups.yaml` |
| 6 | `generate_areas.py` | пространства и этажи HA → `areas.yaml` (офлайн) |
| 7 | `generate_helpers.py` | вспомогательные объекты → `lighting-compilers.yaml` (на HA `zm_`) |
| 8 | `generate_scripts.py` | клоны шаблонных скриптов → `scripts.yaml` |
| 9 | `generate_automations.py` | автоматизации из blueprint'ов → `automations.yaml` |

Каждый шаг запускается **отдельно**, из CLI или кнопкой лаунчера, и работает на
том, что уже лежит в `data/normalized/`. `Build All` прогоняет все девять.

**`Build All` офлайновый** — в живую систему не пишет ничего. Доставка на HA —
отдельный шаг (`deploy.py`), по явному действию.

## Вне `Build All`

| Скрипт | Делает |
|---|---|
| `generate_lovelace_cards.py` | карточки помещений → views дашборда в `data/lovelace/` |

Карточки собираются отдельной кнопкой: у каждого `space_type` своя раскладка,
а типы `zal` и `recreation` требуют HACS-карт (mushroom, card_mod).

Вспомогательные скрипты:

| Скрипт | Делает |
|---|---|
| `show_normalized.py` | просмотр parquet — бинарь, глазами не открыть |
| `check_sftp.py` | разведка канала деплоя на новом объекте |
| `backup_dashboard.py` | снимок конфига дашборда и восстановление (`--restore`) |

`backup_dashboard.py` — перед первым `deploy.py --targets lovelace`: деплой
карточек переписывает конфиг дашборда **целиком**.

## Деплой

Две цели — два транспорта:

| Что | Куда | Транспорт |
|---|---|---|
| YAML-файлы | `/config/includes/...`, `blueprints/` | **SFTP** (add-on «Advanced SSH & Web Terminal») |
| пространства, этажи, карточки | реестры HA и конфиг дашборда | **WebSocket API** |

Dry-run по умолчанию — показывает, что и куда поедет. `--live` отправляет.
Файлы на HA идут с префиксом `zm_`, views дашборда — с `zm-`: деплой
перезаписывает только своё и не трогает то, что наладчик сделал руками.

⚠ **Рестарт HA деплой не делает** — его выполняет человек. Без рестарта YAML не
применится. Карточек и пространств это не касается: они применяются сразу.

⚠ Для карточек нужен токен **администратора**: запись конфига дашборда обычному
пользователю запрещена.

Требования к SSH-аддону на объекте: `sftp: true`, `username: root`, порт наружу,
публичный ключ в `authorized_keys`. Проверить канал: `python scripts/check_sftp.py`.

---

# 3. Установка и запуск

## Пользователю — из релизного архива

Инженер и наладчик работают с **релизным ZIP**, а не с репозиторием: там
`launcher.exe`, `scripts/`, `templates/` и пример таблицы. Репозиторий им не
нужен.

Инструкция для них — [`README_RELEASE.txt`](README_RELEASE.txt); в архиве она
лежит как `INSTALL.txt`. Там установка Python и venv, проверка, что всё встало,
работа с окном, деплой на объект и разбор частых ошибок.

⚠ **README.md в архив не попадает.** Всё, что должен прочитать пользователь,
обязано быть в `README_RELEASE.txt` — дублировать сюда не надо, разъедется.

## Разработчику — из репозитория

```bash
git clone <репозиторий> && cd ha-lighting-compilers
python -m venv .venv

# Windows
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Linux / macOS
.venv/bin/python -m pip install -r requirements-dev.txt
```

⚠ Именно `python -m pip`, а не голый `pip`: тот ставит в окружение, которое
первым нашлось в PATH, обычно системное. Установка пройдёт, а лаунчер скажет,
что модуля нет.

Три файла зависимостей — по тому, кому что нужно:

| Файл | Что внутри | Кому |
|---|---|---|
| `requirements.txt` | pandas, pyarrow, openpyxl, PyYAML, paramiko, websockets | рантайм скриптов; **едет в релизный архив** |
| `requirements-gui.txt` | PySide6 | лаунчер из исходников и сборка EXE |
| `requirements-dev.txt` | оба выше + pytest + pyinstaller | разработка и CI |

⚠ **PySide6 в `requirements.txt` намеренно нет.** Ни один скрипт его не
импортирует; пользователю релизного архива он не нужен — оконная библиотека
уже внутри `launcher.exe`. Держали его там до 2026-07-20, и каждый объект качал
0.62 ГБ Qt впустую. Вернёте — вернёте и это.

```bash
python -m pytest tests/ -q          # тесты
python launcher/main.py             # окно
```

⚠ **На Linux PySide6 не импортируется без `libEGL`.** Лаунчер не запустится, а
GUI-тесты сами себя пропустят — остальные пройдут. На Windows такого нет.

Полная шпаргалка команд — [`bash_command.txt`](bash_command.txt).

---

# 4. Документация

| Файл | О чём |
|---|---|
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | статус: что сделано, что осталось, известный долг, открытые вопросы |
| [`docs/internal/decisions.md`](docs/internal/decisions.md) | **почему так**: разбор решений, из чего выбирали, капканы |
| [`docs/internal/data_model.md`](docs/internal/data_model.md) | правила модели, канон имён, единицы обслуживания |
| [`docs/internal/parquet_reference.md`](docs/internal/parquet_reference.md) | что лежит в каждой колонке parquet |
| [`scripts/_lib/schemas.py`](scripts/_lib/schemas.py) | машиночитаемая схема; при расхождении с документами верна она |
| [`bash_command.txt`](bash_command.txt) | шпаргалка команд |
| [`THIRD-PARTY-LICENSES.md`](THIRD-PARTY-LICENSES.md) | чужое в составе продукта. Сейчас — иконки Lucide (ISC) |
| [`README_RELEASE.txt`](README_RELEASE.txt) | инструкция наладчика; уезжает в релизный архив как `INSTALL.txt` |
| [`CHANGELOG.md`](CHANGELOG.md) | история версий |

Архивные указатели на доки v1: `docs/internal/architecture_rules.md`,
`docs/internal/project_context.md`.

---

## Релизы

**Тег → EXE, других EXE не бывает.**

```bash
# 1. прогнать тесты: CI их НЕ гоняет (решение владельца)
python -m pytest tests/ -q

# 2. версия в launcher/__init__.py обязана совпасть с тегом
# 3. тег публикует: сборка + ПУБЛИЧНЫЙ GitHub Release с EXE
git tag v3.0.0 && git push origin v3.0.0
```

Сборку делает GitHub Actions на чистой `windows-latest`
(`.github/workflows/release.yml`): по любому EXE можно сказать, из какого он
коммита. Собранный локально приходит с чьей-то машины в неизвестном состоянии,
и доказать его состав нечем — а лаунчер показывает версию в шапке именно затем,
чтобы на вопрос «что стоит на объекте» был ответ. Локальная сборка — только для
отладки самой сборки, не для раздачи.

CI сверяет тег с `launcher.__version__` и падает при расхождении: раздать
сборку, которая называет себя не своим именем, хуже, чем не собрать.

---

## ⚠ Важно

Пайплайн собирает **конфигурацию**, но на объекте свет не включится, пока не
появится **JSON Zone Manager** — автоматизация вызовет
`zone_manager.get_sensor_config`, получит `found: false`, и включения не будет.
Он собирается вручную; помощником не является, шагом `generate_helpers.py` не
закрывается. Подробности — ROADMAP → «Известный долг».

`input_number.vacant_delay` (без него свет не **гаснет**) раньше был второй
такой вещью — с 2026-07-17 его создаёт `generate_helpers.py`.

**Помощники: объект создаём, логику — нет.** `input_boolean` пресетов зала и
режимов этажей появятся, но это выключатели: что они делают, описывают ваши
автоматизации. Исключение — `vacant_delay` и `input_select.nav_floor_<N>`:
их читает сгенерированный код.
