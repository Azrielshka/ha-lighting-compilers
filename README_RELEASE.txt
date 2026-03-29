# HA College Lighting — инструкция запуска (Release)

## 📦 Что внутри архива

После скачивания `ha-college-lighting.zip` у тебя есть:

- `launcher.exe` — графический интерфейс для запуска пайплайна
- `scripts/` — Python-скрипты генерации (ОБЯЗАТЕЛЬНЫ)
- `templates/` — шаблоны карточек (можно редактировать)
- `data/` — папка для Excel и результатов
- `requirements.txt` — зависимости Python

---

## ⚠️ Важно перед началом

Требуется установленный Python (рекомендуется 3.10–3.12)

Проверка:
```bash
py --version
```

Если команда не работает — установи Python с официального сайта и включи:
✔ Add Python to PATH

---

## 🚀 Пошаговый запуск

### 1. Распаковать архив

Распакуй `ha-college-lighting.zip` в удобную папку, например:

```
C:\Projects\ha-college-lighting
```

---

### 2. Открыть папку в терминале

Самый простой способ:

- Открой папку в проводнике
- В адресной строке введи:
```
powershell
```
- Нажми Enter

---

### 3. Создать виртуальное окружение

```bash
py -m venv .venv
```

👉 Это создаёт изолированную среду Python внутри проекта

---

### 4. Установить зависимости

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

👉 Устанавливает все библиотеки, нужные для работы скриптов

⚠️ ВАЖНО:
НЕ используем `pip install` без указания `.venv\Scripts\python.exe` — иначе пакеты могут установиться не туда

---

### 5. Подготовить Excel

- Помести свой Excel файл в папку:
```
data/
```

- Или используй `example.xlsx`

---

### 6. Запустить лаунчер

Просто двойной клик:

```
launcher.exe
```

---

## 🖥️ Работа с лаунчером

### 1. Укажи пути:

- **Project Root** → путь к папке проекта
  (пример: `C:\Projects\ha-college-lighting`)

- **Excel File Path** → путь к Excel
  (пример: `...\data\example.xlsx`)

---

### 2. Нажми:

```
Build All
```

---

### 3. Что произойдёт

Лаунчер последовательно выполнит:

1. normalize_excel.py
2. generate_lights_groups.py
3. generate_general_groups.py
4. generate_floor_groups.py
5. generate_lovelace_cards_v2.py

---

### 4. Результаты

Файлы появятся в:

```
data/
├── normalized/
├── light_groups/
└── lovelace_cards_generated.txt
```

---

## ⚠️ Частые ошибки и решения

### ❌ Ошибка: "python.exe не найден"

Причина:
- не создан `.venv`

Решение:
```bash
py -m venv .venv
```

---

### ❌ Ошибка: "scripts/... не найден"

Причина:
- в архиве нет папки `scripts/`

Решение:
✔ Скачать правильный релиз
✔ Проверить структуру проекта

---

### ❌ Ошибка: PowerShell не даёт активировать venv

```
execution of scripts is disabled
```

Решение (НЕ обязательно):

Можно НЕ активировать окружение — просто использовать:

```bash
.venv\Scripts\python.exe ...
```

---

### ❌ Кнопка нажимается, но ничего не происходит

Причина:
- Python/venv не настроен

Проверь:
```
.venv\Scripts\python.exe
```

---

## 🛠️ Настройка шаблонов

Ты можешь изменять:

```
templates/
```

Например:
- cabinet/
- corridor/
- lestnitsa/
- su/

После изменений → снова нажать `Build All`

---

## 📌 Важно понимать

- `launcher.exe` НЕ содержит Python-скрипты внутри
- Он просто запускает их через `.venv`

👉 Поэтому структура проекта должна сохраняться

---

## 💡 Рекомендации

- Не переименовывай папки `scripts/`, `templates/`, `data/`
- Всегда запускай из одной и той же структуры
- Используй `Build All` вместо ручного запуска

---

## ✅ Минимальный чек-лист

```bash
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

→ открыть `launcher.exe`
→ выбрать Excel
→ нажать **Build All**

---

Готово 🚀

ha-college-lighting — инструкция запуска

1. Установить Python 3.10+
https://www.python.org/downloads/

ВАЖНО: при установке включить "Add Python to PATH"

2. Открыть папку проекта

3. Установить зависимости:
pip install -r requirements.txt

4. Подготовить Excel:
- можно использовать файл из папки data/
- или заменить своим (с той же структурой)

5. Запустить launcher:
launcher.exe

6. В GUI:
- выбрать Excel файл
- нажать Build All

Результат появится в папке data/