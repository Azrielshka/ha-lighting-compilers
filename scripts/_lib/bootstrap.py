# bootstrap.py
# ------------------------------------------------------------
# Вспомогательный модуль для CLI-скриптов проекта.
#
# Зачем нужен:
#   когда мы запускаем скрипт так:
#       python scripts/generate_*.py
#
#   Python не считает папку проекта корнем модулей.
#   Поэтому импорт вида:
#
#       from scripts._lib.canon import ...
#
#   не работает.
#
#   Этот модуль добавляет корень проекта в sys.path,
#   чтобы все скрипты могли импортировать модули проекта.
# ------------------------------------------------------------

from __future__ import annotations

import sys
from pathlib import Path


def setup_project_path() -> None:
    """
    Добавляет корень проекта в PYTHONPATH.

    Это позволяет импортировать модули проекта из scripts/,
    даже если скрипт запущен напрямую через:

        python scripts/<script>.py
    """

    # путь до текущего файла bootstrap.py
    current_file = Path(__file__).resolve()

    # scripts/_lib/bootstrap.py -> scripts/_lib -> scripts -> PROJECT_ROOT
    project_root = current_file.parents[2]

    # добавляем путь только если его ещё нет
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))