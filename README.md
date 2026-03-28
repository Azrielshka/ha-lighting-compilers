# 🏫 HA College Lighting

Генератор конфигурации освещения для Home Assistant на основе Excel.

---

# 📑 Содержание

- [Описание проекта](#описание-проекта)
- [Архитектура](#архитектура)
- [Скрипты](#скрипты)
  - [normalize_excel.py](#1-normalize_excelpy)
  - [generate_lights_groups.py](#2-generate_lights_groupspy)
  - [generate_general_groups.py](#3-generate_general_groupspy)
  - [generate_floor_groups.py](#4-generate_floor_groupspy)
  - [generate_lovelace_cards_v2.py](#5-generate_lovelace_cards_v2py)
- [Launcher (GUI)](#launcher-gui)
- [Установка и запуск](#установка-и-запуск)

---

# 📌 Описание проекта

Проект **ha-college-lighting** предназначен для автоматической генерации:

- YAML-групп освещения
- Lovelace-карточек
- структуры управления освещением

на основе одной Excel-таблицы.

---

## Основная идея

Excel — это **единственный источник данных**.

Pipeline проекта:

```
Excel → normalize → parquet → generators → YAML → Lovelace
```

---

## Что решает проект

- исключает ручное написание YAML
- обеспечивает единый нейминг сущностей
- упрощает поддержку проекта освещения
- позволяет быстро пересобирать конфигурацию

---

# 🧠 Архитектура

Ключевой принцип:

👉 Excel читается **один раз** (в normalize)

Дальше всё работает через **parquet слой**

```
Excel
  ↓
normalize_excel.py
  ↓
data/normalized/
  ↓
генераторы
  ↓
YAML + Lovelace
```

---

# 🧩 Скрипты

## 1. normalize_excel.py

**Назначение:**
нормализация Excel → канонический слой данных

**Что делает:**

- читает Excel
- строит:
  - `device_rows.parquet`
  - `spaces.parquet`
- формирует `normalized_meta.json`

**Особенности:**

- поддерживает 2 режима:
  - CLI: `--excel`
  - standalone: DEFAULT_EXCEL_PATH

**Выход:**

```
data/normalized/
```

---

## 2. generate_lights_groups.py

**Назначение:**
создание подгрупп света

**Что делает:**

- читает `device_rows.parquet`
- группирует лампы по `group_id`

**Результат:**

```
light.<group_id>
```

пример:

```
light.403_0
light.403_1
```

---

## 3. generate_general_groups.py

**Назначение:**
создание общей группы помещения

**Что делает:**

- объединяет подгруппы
- строит:

```
light.<room_slug>_obshchii
```

---

## 4. generate_floor_groups.py

**Назначение:**
создание групп этажей

**Что делает:**

- объединяет помещения по этажу

**Результат:**

```
floor_<n>_all
```

опционально:

```
tex_floor_<n>
```

---

## 5. generate_lovelace_cards_v2.py

**Назначение:**
генерация Lovelace UI

**Источник:**

```
spaces.parquet
```

**Использует:**

```
templates/
manifest.yaml
```

---

## Как работает генерация карточек

1. определяется `card_type`
2. определяется `groups_count`
3. выбирается шаблон
4. выполняется подстановка:

- entity_id света
- датчиков
- названий

---

# 🖥 Launcher (GUI)

Launcher — это **графическая оболочка для pipeline**

---

## Назначение

Позволяет запускать генерацию без терминала.

---

## Возможности

- выбор Project Root
- выбор Excel файла
- запуск отдельных шагов
- запуск полного pipeline (Build All)
- просмотр логов
- сохранение конфигурации

---

## Pipeline в launcher

```
Normalize
→ Lights
→ General
→ Floor
→ Lovelace
```

---

## Особенности

- запускает скрипты через subprocess
- Python определяется автоматически:

```
<project_root>/.venv/Scripts/python.exe
```

- UI блокируется во время выполнения
- лог выводится после завершения шагов

---

## Запуск launcher (dev)

```
python launcher/main.py
```

---

# ⚙️ Установка и запуск

## 1. Клонирование репозитория

```
git clone <repo_url>
cd ha-college-lighting
```

---

## 2. Создание виртуального окружения

```
python -m venv .venv
```

---

## 3. Установка зависимостей

```
pip install -r requirements.txt
```

---

## 4. Запуск launcher (dev)

```
python launcher/main.py
```

---

## 5. Сборка EXE

```
pyinstaller launcher/main.py --onefile --noconsole
```

---

## 6. Запуск EXE

```
dist/main.exe
```

---

## ⚠️ Важно

- launcher **не является автономным**
- требуется структура проекта
- требуется `.venv`
- требуется Excel файл

---

# 📌 Статус проекта

Проект используется как внутренний инструмент генерации конфигурации освещения для Home Assistant.

---

# 📎 Дополнительно

Подробности архитектуры:

```
docs/internal/architecture_rules.md
docs/internal/project_context.md
```