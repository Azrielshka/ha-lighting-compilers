# ha-lighting-compilers

Генератор конфигурации Home Assistant для управления освещением DALI на основе
одной Excel-таблицы. Запускается на машине наладчика (Windows), готовит YAML и
опционально доставляет его на HAOS. Это **не** интеграция Home Assistant.

---

## Идея

Проектировщик заполняет **одну** Excel-таблицу с именами будущих устройств.
Из неё пайплайн собирает всю конфигурацию HA: группы света, пространства,
скрипты, автоматизации — и кладёт на сервер.

```
Excel  →  проверка  →  нормализация  →  генераторы  →  YAML  →  деплой на HA
```

Excel читается **один раз** (в normalize). Дальше всё работает с parquet —
генераторы саму таблицу не открывают.

---

## Пайплайн (8 шагов)

| # | Скрипт | Делает |
|---|---|---|
| 1 | `validate_excel.py` | проверяет таблицу; на ошибках пайплайн останавливается |
| 2 | `normalize_excel.py` | Excel → `devices` / `groups` / `spaces` / `units` parquet |
| 3 | `generate_lights_groups.py` | подгруппы света (зоны) → `lights_group.yaml` |
| 4 | `generate_general_groups.py` | общие группы помещений → `lights_general_groups.yaml` |
| 5 | `generate_floor_groups.py` | группы этажей → `lights_floor_groups.yaml` |
| 6 | `generate_areas.py` | пространства и этажи HA → `areas.yaml` (офлайн) |
| 7 | `generate_scripts.py` | клоны шаблонных скриптов → `scripts.yaml` |
| 8 | `generate_automations.py` | автоматизации из blueprint'ов → `automations.yaml` |

Каждый шаг запускается **отдельно**, из CLI или кнопкой лаунчера, и работает на
том, что уже лежит в `data/normalized/`. `Build All` прогоняет все восемь.

**`Build All` офлайновый** — в живую систему не пишет ничего. Доставка на HA —
отдельный шаг (`deploy.py`), по явному действию.

### Вне `Build All`

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

---

## Ключевые понятия

**Устройство принадлежит группе, указанной в его строке.** Лампа, датчик и
панель в одной строке Excel — это разные устройства одной группы. У группы
может быть 0..N датчиков и панелей.

**Единица обслуживания** (колонка «Блок»): помещение либо все помещения одного
блока. На каждую клонируется свой набор скриптов — один экземпляр скрипта в HA
это одна очередь, и при тысяче датчиков свет отставал бы от человека.

**Канон имён** живёт в `scripts/_lib/canon.py` — генераторы его не дублируют:

| Объект | entity_id |
|---|---|
| лампа | `light.l_1_20_15` |
| датчик движения | `sensor.ms_1_20_3` |
| датчик освещённости | `sensor.il_1_20_3` |
| панель | `event.kp_1_1_1` |
| зона | `light.<group_id>` |
| общая группа | `light.<room_slug>_obshchii` |

---

## Деплой

Две цели — два транспорта:

| Что | Куда | Транспорт |
|---|---|---|
| YAML-файлы | `/config/includes/...`, `blueprints/` | **SFTP** (add-on «Advanced SSH & Web Terminal») |
| пространства, этажи | реестры HA | **WebSocket API** |

Dry-run по умолчанию — показывает, что и куда поедет. `--live` отправляет.
Файлы с префиксом `zm_`: деплой перезаписывает только своё и не трогает файлы
наладчика. Рестарт HA деплой **не делает** — его выполняет человек.

Требования к SSH-аддону на объекте: `sftp: true`, `username: root`, порт наружу,
публичный ключ в `authorized_keys`. Проверить канал: `python scripts/check_sftp.py`.

---

## Установка и запуск

Окружение (Windows, машина наладчика):

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

CLI:

```bash
python scripts/validate_excel.py --excel data/object_example.xlsx
python scripts/normalize_excel.py --excel data/object_example.xlsx
python scripts/generate_lights_groups.py
# ... остальные генераторы
python scripts/deploy.py                       # dry-run
python scripts/deploy.py --live --host ... --key ...
```

Лаунчер (GUI):

```bash
python launcher/main.py
```

Тесты (нужен `requirements-dev.txt`):

```bash
python -m pytest tests/ -q
```

---

## Документация

| Файл | О чём |
|---|---|
| `docs/ROADMAP.md` | что сделано, что осталось, известный долг, открытые вопросы |
| `docs/internal/data_model.md` | правила модели, канон имён, единицы обслуживания |
| `docs/internal/parquet_reference.md` | что лежит в каждой колонке parquet |
| `scripts/_lib/schemas.py` | машиночитаемая схема; при расхождении верна она |

---

## ⚠ Важно

Пайплайн собирает **конфигурацию**, но на объекте свет заработает только после
двух вещей вне пайплайна (см. ROADMAP → «Известный долг»):

- `input_number.vacant_delay` — иначе не гаснет;
- JSON Zone Manager — иначе не включается.

Оба заводятся вручную на объекте.
