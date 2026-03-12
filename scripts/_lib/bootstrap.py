# bootstrap.py
# ------------------------------------------------------------
# Вспомогательный модуль для CLI-скриптов проекта.
#
# Зачем нужен:
#   при запуске:
#       python scripts/<script>.py
#
#   Python не добавляет корень проекта в sys.path автоматически.
#   Поэтому импорты вида:
#
#       from scripts._lib.canon import ...
#
#   начинают работать только после ручного добавления PROJECT_ROOT.
# ------------------------------------------------------------

from __future__ import annotations

import sys
from pathlib import Path


def setup_project_path() -> Path:
    """
    Добавляет корень проекта в sys.path и возвращает его.

    Возврат пути удобен для отладки и при желании
    может использоваться в самих скриптах.
    """
    current_file = Path(__file__).resolve()

    # scripts/_lib/bootstrap.py -> PROJECT_ROOT
    project_root = current_file.parents[2]

    project_root_str = str(project_root)

    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

    return project_root