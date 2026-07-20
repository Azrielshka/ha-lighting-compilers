# -*- coding: utf-8 -*-
"""
Зависимости разведены по тому, кому что нужно.

`requirements.txt` едет в релизный архив и ставится на каждом объекте. Каждая
лишняя строка в нём — мегабайты, которые качают заново на новой машине. До
2026-07-20 там лежал PySide6: пользователь тянул 0.62 ГБ Qt, чтобы положить
рядом с launcher.exe ровно то, что внутри EXE уже есть.

Тест держит границу: рантайм-список обязан покрывать импорты скриптов и не
содержать ничего сверх.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Что во что раскрывается: pandas читает .xlsx через openpyxl, не импортируя
# его в коде; paramiko тянет криптографию.
IMPLICIT = {"openpyxl"}

# import-имя -> имя пакета в requirements
DIST_NAME = {"yaml": "PyYAML"}


def _requirements(name: str) -> set:
    """Имена пакетов из файла, без версий, комментариев и -r."""
    text = (ROOT / name).read_text(encoding="utf-8")
    out = set()
    for line in text.split("\n"):
        line = line.split("#")[0].strip()
        if not line or line.startswith("-r"):
            continue
        out.add(re.split(r"[<>=!\[]", line)[0].strip())
    return out


def _third_party_imports(folder: str) -> set:
    """Внешние модули, которые импортирует папка."""
    std = set(sys.stdlib_module_names)
    local = {"scripts", "_lib", "launcher", "conftest", "tests"}
    found = set()
    for path in (ROOT / folder).rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    # локальные модули скриптов зовут друг друга по имени файла
    scripts_own = {p.stem for p in (ROOT / "scripts").rglob("*.py")}
    return found - std - local - scripts_own


def test_runtime_has_no_gui_dependency():
    """PySide6 не должен вернуться в рантайм-список.

    Проверяем не только имя файла, но и суть: ни один скрипт его не импортирует,
    значит пользователю архива он не нужен. Вернёте — вернёте 0.62 ГБ на объект.
    """
    runtime = _requirements("requirements.txt")

    assert "PySide6" not in runtime, (
        "PySide6 в requirements.txt: он едет в релизный архив, а скрипты его не "
        "импортируют — у пользователя оконная библиотека уже внутри launcher.exe"
    )
    assert "pyinstaller" not in {r.lower() for r in runtime}, (
        "pyinstaller собирает EXE и в рантайме бесполезен"
    )
    assert "pytest" not in runtime


def test_scripts_never_import_gui():
    """Разведение держится на этом: скрипты не знают про PySide6.

    Появится импорт — рантайм-список обязан будет его получить, и экономия
    исчезнет. Тогда это осознанное решение, а не случайность.
    """
    assert "PySide6" not in _third_party_imports("scripts")


def test_runtime_covers_what_scripts_import():
    """Всё, что скрипты импортируют, обязано быть в рантайм-списке.

    Обратная сторона урезания: убрать лишнее легко, вместе с нужным — тоже.
    Тогда пайплайн падает у наладчика на объекте, а не здесь.
    """
    runtime = _requirements("requirements.txt")
    needed = {DIST_NAME.get(m, m) for m in _third_party_imports("scripts")}

    missing = needed - runtime
    assert not missing, f"скрипты импортируют, а в requirements.txt нет: {sorted(missing)}"


def test_gui_list_exists_and_holds_pyside():
    gui = _requirements("requirements-gui.txt")
    assert gui == {"PySide6"}, gui


def test_dev_pulls_everything():
    """Разработчику нужно всё: рантайм, GUI, тесты, сборка."""
    text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "-r requirements.txt" in text
    assert "-r requirements-gui.txt" in text
    dev = _requirements("requirements-dev.txt")
    assert "pytest" in dev and "pyinstaller" in dev


def test_release_ships_runtime_only():
    """В архив кладём рантайм-список, а не dev.

    Положим dev — пользователь получит pytest и pyinstaller, которые ему не
    нужны, и снова PySide6 через -r requirements-gui.txt.
    """
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "copy requirements.txt release\\requirements.txt" in workflow
    for extra in ("requirements-dev.txt release", "requirements-gui.txt release"):
        assert extra not in workflow, f"в архив попадает {extra}"


def test_ci_installs_what_it_needs_to_build():
    """Раннеру нужны PySide6 (упаковать) и pyinstaller (собрать).

    requirements.txt их больше не содержит — если CI ставит его, сборка упадёт
    на «pyinstaller: command not found». Ловим здесь, а не в красном релизе.
    """
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    install = re.search(r"Install dependencies\s*\n\s*run: (.+)", workflow).group(1)

    assert "requirements-dev.txt" in install, install
