# Справочник по нормализованному слою (parquet)

Что именно лежит в `data/normalized/` после `normalize_excel.py`.

Этот документ — для человека. **Машиночитаемый источник правды —
`scripts/_lib/schemas.py`**; при расхождении верен код.

- Правила модели: `docs/internal/data_model.md`
- Чтение из генераторов: `scripts/_lib/normalized.py`
- Посмотреть глазами: `python scripts/show_normalized.py`

Все примеры ниже — настоящие, из `data/object_example.xlsx`
(6 помещений, 12 групп, 91 устройство).

---

# Зачем четыре файла, а не один

```
Excel (лист «Проектная БД»)
      ↓  normalize_excel.py
devices.parquet   строка = одно устройство            (91)
groups.parquet    строка = группа света / зона        (12)
spaces.parquet    строка = помещение                  (6)
units.parquet     строка = единица обслуживания       (3)
```

Один и тот же факт нужен генераторам в разной нарезке:

| Генератор | Читает | Почему |
|---|---|---|
| `generate_lights_groups` | `groups` | нужен список ламп на зону |
| `generate_general_groups` | `spaces` | нужен список зон на помещение |
| `generate_floor_groups` | `spaces` | нужны помещения на этаж |
| `generate_areas` | `spaces` | пространства и этажи HA |
| `generate_scripts` | `units` | клоны скриптов по единицам |
| `generate_automations` | `units` | автоматизации по единицам |
| `generate_lovelace_cards` | `spaces` | нужны зоны и датчики на карточку |

`devices` — нижний слой, из которого собраны остальные. Он же нужен, когда
надо ответить на вопрос «из какой строки Excel это взялось».

---

# devices.parquet

**Строка = одно физическое устройство.** Одна строка Excel даёт до трёх строк
здесь: лампа, датчик и панель лежат в таблице рядом, но это разные устройства.

| Колонка | Тип | Что это |
|---|---|---|
| `row_id` | int64 | Номер строки в Excel. Чтобы наладчик мог вернуться к своей таблице |
| `kind` | string | `lamp` / `sensor` / `panel` — из какой колонки пришло |
| `addr` | string | Адрес как в таблице: `1.1.5` |
| `addr_floor` | int64 | `X` — этаж. **Истина**, в отличие от колонки «Этаж» |
| `addr_bus` | int64 | `Y` — шина |
| `addr_num` | int64 | `Z` — проектный номер |
| `entity_id` | string | Имя сущности в HA: `light.l_*` / `sensor.ms_*` / `event.kp_*` |
| `entity_id_2` | string | Вторая сущность. **Только у датчиков**: `sensor.il_*`. У ламп и панелей — `null` |
| `group_id` | string | Группа из **этой же строки** Excel |
| `space` | string | Русское имя помещения |
| `room_slug` | string | Транслит для entity_id |
| `floor` | int64 | Из колонки «Этаж». Именно она идёт в `floor_<n>_all` |
| `space_type` | string | `class` / `korridor` / `recreation` / `hall` / `zal` / `special`; `null` если не указан |
| `block` | string | Колонка «Блок»; `null`, если помещение обслуживается само по себе |
| `dali_bus` | string | Из колонки «Шина DALI». Справочно, в генерации не участвует |

## Живой пример

Строки 6 и 8 Excel (помещение `102_Тамбур`) дали четыре устройства:

```
 row_id   kind  addr       entity_id     entity_id_2 group_id
      6   lamp 1.1.5   light.l_1_1_5             —      102_1
      6 sensor 1.1.2 sensor.ms_1_1_2 sensor.il_1_1_2    102_1
      8   lamp 1.1.7   light.l_1_1_7             —      102_1
      8 sensor 1.1.3 sensor.ms_1_1_3 sensor.il_1_1_3    102_1
```

Обратите внимание: датчик `1.1.3` физически записан в строке лампы `1.1.7`,
но к ней отношения не имеет — он принадлежит **группе** `102_1`, как и всё
остальное в этой строке. Это и есть правило привязки v2.

## Чего здесь нет

**Строк для отсутствующих устройств.** Ячейка `None` (или `нет`, `-`) означает
«устройства по проекту нет» — и в `devices` она не порождает ничего. Отсутствие
устройства не является устройством.

Поэтому 91 строка, а не 100+: 75 ламп + 11 датчиков + 5 панелей. Ячейки с
`None` (2 датчика, 4 панели) не в счёте.

---

# groups.parquet

**Строка = группа света (зона).** Каждая строка станет одной `light.<group_id>`
в YAML.

| Колонка | Тип | Что это |
|---|---|---|
| `group_id` | string | `103_1` — как в колонке «Группа» |
| `space`, `room_slug`, `floor`, `space_type` | | Протянуто с помещения, чтобы генератору не делать join |
| `zone_light_entity` | string | `light.103_1` — то, что создаст генератор |
| `lamps` | list\<string\> | Список ламп зоны → станет `entities:` в YAML |
| `sensors_ms` | list\<string\> | Датчики движения. **0..N** |
| `sensors_il` | list\<string\> | Датчики освещённости. Параллелен `sensors_ms`: тот же адрес, другой домен |
| `panels` | list\<string\> | Панели `event.kp_*`. **0..N** |
| `lamp_count`, `sensor_count`, `panel_count` | int64 | Длины списков. Дублируют данные, но избавляют генераторы от подсчётов |

## Живой пример

```
group_id               103_1
zone_light_entity      light.103_1
lamps                  ['light.l_1_1_10', 'light.l_1_1_11', 'light.l_1_1_12', 'light.l_1_1_13']
sensors_ms             ['sensor.ms_1_1_4']
sensors_il             ['sensor.il_1_1_4']
panels                 ['event.kp_1_1_1']
lamp_count             4
sensor_count           1
panel_count            1
space_type             korridor
```

## Что здесь важно

**`sensors_ms` — список, а не значение.** Группа `102_1` держит два датчика:

```
sensors_ms   ['sensor.ms_1_1_2', 'sensor.ms_1_1_3']
```

Схема v1 хранила один датчик на группу, скаляром, и второй **молча теряла**.
Это был главный дефект, ради которого переезжали.

**`sensors_il` всегда той же длины, что `sensors_ms`.** Один адрес датчика даёт
обе сущности — движение и освещённость. `il_` понадобится в автоматизациях.

**Порядок — как в Excel.** И групп, и ламп внутри группы. Специально: наладчик
сверяет сгенерированный YAML со своей таблицей, и пересортировка сделала бы это
невозможным.

---

# spaces.parquet

**Строка = помещение.** Отсюда живут общие группы, группы этажей и карточки.

| Колонка | Тип | Что это |
|---|---|---|
| `space` | string | `103_Вестибюль` |
| `room_slug` | string | `103_vestibiul` — транслит |
| `floor` | int64 | Из колонки «Этаж» |
| `space_type` | string | Нормализованный тип; `null` если не указан |
| `has_valid_type` | bool | **Ворота для карточек** |
| `groups` | list\<string\> | `['103_1', '103_2', '103_3', '103_4']` |
| `groups_count` | int64 | Длина `groups`. Второй ключ выбора шаблона карточки |
| `general_light_entity` | string | `light.103_vestibiul_obshchii` |
| `zone_light_entities` | list\<string\> | Те же группы, но уже как `light.*` — готово к `[[ZONE_LIGHT_i]]` |
| `sensors_by_group` | list\<list\<string\>\> | **`[i]` относится к `groups[i]`** |
| `panels_by_group` | list\<list\<string\>\> | То же для панелей |
| `sensors_unique` | list\<string\> | Плоский отсортированный набор датчиков помещения |
| `block` | string | Колонка «Блок»; `null`, если помещение само по себе |
| `unit_id` | string | Единица обслуживания: `block` либо `room_slug` |
| `family` | string | `default` / `hall` / `special` / `null` (class и zal не автоматизируются) |
| `warnings` | list\<string\> | `missing_space_type` / `unknown_space_type:<что было>` |

## `has_valid_type` — ворота для карточек

| Значение | Что происходит |
|---|---|
| `True` | помещение попадает и в группы света, и в карточку Lovelace |
| `False` | тип не указан или неизвестен → **карточка не рисуется**, но группы света создаются: лампы физически существуют |

`generic` как fallback упразднён — помещение без типа не подставляется в
случайный шаблон, а честно пропускается с предупреждением.

## `sensors_by_group` — самое важное поле

Списки **выровнены по индексу** с `groups`. Пустой вложенный список означает
«у этой группы нет датчиков», а не «данные потерялись».

`103_Вестибюль` — у каждой зоны свой датчик, панель только в первой:

```
groups             ['103_1', '103_2', '103_3', '103_4']
sensors_by_group   [['sensor.ms_1_1_4'], ['sensor.ms_1_1_5'], ['sensor.ms_1_1_6'], ['sensor.ms_1_1_7']]
panels_by_group    [['event.kp_1_1_1'], [], [], []]
```

`105_Актовый зал` — датчиков нет вовсе (по глоссарию: «большие пространства, без
датчиков»), зато у каждой зоны своя панель:

```
groups             ['105_1', '105_2']
sensors_by_group   [[], []]
panels_by_group    [['event.kp_1_2_1'], ['event.kp_1_2_2']]
sensors_unique     []
```

Старая схема выразить такое состояние не могла: она хранила один датчик на
группу и подставляла в карточку `sensor.unavailable`, когда его не было.

---

# units.parquet

**Строка = единица обслуживания** — то, на что клонируется набор скриптов.
Единица = помещение (если «Блок» пуст) либо все помещения одного блока.
Только автоматизируемые: `class` и `zal` сюда не попадают.

| Колонка | Тип | Что это |
|---|---|---|
| `unit_id` | string | «Блок» либо `room_slug`. Из него имена скриптов |
| `family` | string | `default` / `hall` / `special` |
| `spaces` | list\<string\> | Помещения единицы. Обычно одно; несколько — если задан «Блок» |
| `space_type` | string | Тип помещений единицы |
| `floors` | list\<int\> | Этажи (у лестничного стояка их несколько) |
| `sensors_ms` | list\<string\> | Датчики движения → станут `triggers` автоматизации |
| `sensor_count` | int64 | Длина. `> 12` → предупреждение W07 |
| `zone_lights` | list\<string\> | Группы света единицы |
| `scripts` | list\<string\> | Клоны: `script.<unit_id>_<role>` |
| `blueprint_on` | string | Файл blueprint'а ON |
| `blueprint_off` | string | Файл blueprint'а OFF |
| `warnings` | list\<string\> | `sensors_over_limit:<N>` |

Пример (два тамбура в блоке `hl_1`):

```
unit_id       hl_1
family        special
spaces        ['101_Тамбур', '102_Тамбур']
sensor_count  3
scripts       ['script.hl_1_on', 'script.hl_1_off']
blueprint_on  zm_special_on.yaml
```

Почему клонируем, а не один скрипт на всех: один экземпляр скрипта в HA — это
одна очередь. При тысяче датчиков вызовы копятся, и свет отстаёт от человека.
У каждой единицы свой набор — они друг друга не ждут.

---

# Схема прибита гвоздями

`normalize` пишет parquet **строго по объявленной схеме**, а не выводит её из
данных:

```python
pa.Table.from_pandas(frame, schema=SCHEMAS[name], preserve_index=False)
```

Так сделано не из аккуратности, а по итогам реального бага. `from_pandas()`
выводит типы из содержимого, и если колонка пуста во всей таблице, Arrow ставит
туда `null`:

| Колонка | Когда данные есть | Когда данных нет |
|---|---|---|
| `panels_by_group` | `list<list<string>>` | `list<list<null>>` |
| `warnings` | `list<string>` | `list<null>` |
| `space_type` | `string` | `null` |

То есть **схема файла зависела от объекта**. На объекте без единой панели
генератор автоматизаций получил бы список пустот вместо списка строк — и
сломался бы не у разработчика, а у наладчика, в месте, где отладить его некому.

Теперь несоответствие данных схеме роняет **запись**, сразу и внятно.

## Чтение из генераторов

Не читайте parquet напрямую. Используйте `scripts/_lib/normalized.py`:

Нужен один датасет — `load_dataset` (так делает большинство генераторов):

```python
from scripts._lib.normalized import load_dataset

spaces = load_dataset(Path("data/normalized"), "spaces")
```

Нужны несколько сразу — `load_normalized`:

```python
from scripts._lib.normalized import load_normalized

layer = load_normalized(Path("data/normalized"))
layer.groups   # DataFrame со сверенной схемой
layer.spaces
layer.devices
```

⚠ `load_normalized` отдаёт **три** датасета из четырёх: `units` в
`NormalizedLayer` не входит. Нужны единицы обслуживания — только
`load_dataset(path, "units")`, как это делают `generate_scripts` и
`generate_automations`.

Оба проверяют, что файл соответствует объявленной схеме, и внятно ругаются на
parquet, собранный старой версией `normalize_excel.py`
(`NormalizedLayerError`), — вместо того чтобы дать генератору странно себя
повести.

---

# Как посмотреть глазами

Parquet бинарный, в редакторе не открыть.

```bash
python scripts/show_normalized.py                 # обзор: паспорт + три датасета
python scripts/show_normalized.py --space 102     # помещение: все группы и их состав
python scripts/show_normalized.py --group 102_1   # группа + строки Excel, откуда собрана
python scripts/show_normalized.py --devices --full
```

⚠ **`units.parquet` просмотрщик не показывает.** Обзор выводит паспорт и три
датасета — `devices`, `groups`, `spaces`; флага для единиц обслуживания у
`show_normalized.py` нет вовсе. Пока смотреть только так:

```python
import pandas as pd
pd.read_parquet('data/normalized/units.parquet')
```

Или в Python Console — любой датасет:

```python
import pandas as pd
pd.read_parquet('data/normalized/groups.parquet')
```

---

# normalized_meta.json

Паспорт генерации рядом с parquet. Нужен, чтобы понять, из чего собран слой,
когда что-то не сходится:

```json
{
  "schema_version": 3,
  "generator_version": "3.0.0",
  "generated_at": "2026-07-13T08:01:12+00:00",
  "source_file": ".../object_example.xlsx",
  "sheet_name": "Проектная БД",
  "stats": {
    "excel_rows": 75,
    "devices": 91,
    "lamps": 75,
    "sensors": 11,
    "panels": 5,
    "groups": 12,
    "spaces": 6,
    "spaces_without_valid_type": 0,
    "units": 3,
    "scripts": 8,
    "automations": 6
  }
}
```

`spaces_without_valid_type` — сколько помещений не попадёт в карточки.
Если это число не ноль, а вы ждали карточку — смотрите `warnings` в `spaces`.
