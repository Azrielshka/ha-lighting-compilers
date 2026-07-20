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


def _force_utf8_output() -> None:
    """Заставить stdout/stderr работать в UTF-8, чем бы ни был терминал.

    ⚠ Без этого скрипт ПАДАЕТ на собственном выводе. Весь вывод у нас русский,
    с эмодзи; Python на Windows берёт кодировку из локали (cp1251/cp1252/cp866),
    и первый же print с «📊 Статистика» роняет процесс с UnicodeEncodeError.

    Когда это бьёт:
      - вывод перенаправлен в файл или конвейер (`> log.txt`, `| more`);
      - запуск в CI — там stdout всегда труба. На этом упала сборка v3.0.0:
        иконка собралась, а печать «OK: ... байт» уронила шаг.

    Через лаунчер проблемы нет: он ставит PYTHONUTF8=1 своим подпроцессам
    (`launcher/services/process_runner.py`). Но CLI-запуск, который описан в
    INSTALL.txt наладчику, шёл незащищённым.

    `errors="replace"` намеренно: в старой консоли лучше показать «?» вместо
    буквы, чем уронить генерацию на середине. Данные от этого не страдают —
    в файлы мы пишем с явным encoding="utf-8".
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # stdout подменён (тесты, IDE) или уже закрыт — не наша забота
            pass


def setup_project_path() -> Path:
    """
    Добавляет корень проекта в sys.path и возвращает его.

    Заодно чинит кодировку вывода: это единственная точка, через которую
    проходят все CLI-скрипты проекта, — см. _force_utf8_output().

    Возврат пути удобен для отладки и при желании
    может использоваться в самих скриптах.
    """
    _force_utf8_output()

    current_file = Path(__file__).resolve()

    # scripts/_lib/bootstrap.py -> PROJECT_ROOT
    project_root = current_file.parents[2]

    project_root_str = str(project_root)

    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

    return project_root