# -*- coding: utf-8 -*-
"""
Скрипты не должны падать на собственном выводе.

Весь вывод проекта русский, с эмодзи. Python берёт кодировку stdout из локали,
и когда вывод перенаправлен (файл, конвейер, CI), на Windows это cp1252 —
первый же print роняет процесс с UnicodeEncodeError.

Так умерла сборка v3.0.0: иконка собралась, а печать «OK: ... байт» уронила
шаг. Хуже другое — INSTALL.txt велит наладчику запускать скрипты из PowerShell,
и там та же мина: `python scripts\\validate_excel.py > log.txt` падал бы на
«📊 Статистика».

Через лаунчер проблемы не было (он ставит PYTHONUTF8 подпроцессам), поэтому и
не всплывало.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Кодировка, в которой Python оказывается на windows-latest при
# перенаправленном выводе. Ровно она и уронила сборку.
HOSTILE = "cp1252"


def _run(args: list, env_encoding: str) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = env_encoding
    env.pop("PYTHONUTF8", None)          # чтобы режим UTF-8 не спас нас случайно
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )


@pytest.mark.parametrize("script,args", [
    ("scripts/validate_excel.py", ["--excel", "data/object_example.xlsx"]),
    ("scripts/normalize_excel.py", ["--excel", "data/object_example.xlsx"]),
    ("scripts/generate_helpers.py", []),
    ("scripts/show_normalized.py", []),
])
def test_script_survives_hostile_console_encoding(script, args):
    """Скрипт отрабатывает, даже если консоль не понимает кириллицу.

    Проверяем код возврата, а не текст: в старой консоли вместо букв могут быть
    «?», и это нормально. Недопустимо — падение на середине генерации.
    """
    result = _run([script, *args], HOSTILE)

    assert result.returncode == 0, (
        f"{script} упал при PYTHONIOENCODING={HOSTILE}:\n{result.stderr[-800:]}"
    )
    assert "UnicodeEncodeError" not in result.stderr


def test_icon_builder_survives_too(tmp_path):
    """tools/make_icon.py — тот самый шаг, на котором умерла сборка v3.0.0.

    Он вне scripts/ и не проходит через bootstrap, поэтому чинится отдельно.
    """
    # ⚠ Ловим ImportError руками, а не importorskip: модуль на месте, падает
    # загрузка его бинарника (на dev-VM нет libEGL). importorskip рассчитан на
    # «модуля нет» и такую ошибку пробрасывает — тест падал бы вместо пропуска.
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError as e:
        pytest.skip(f"GUI-зависимость недоступна: {e}")

    result = _run(["tools/make_icon.py", str(tmp_path / "t.ico")], HOSTILE)

    assert result.returncode == 0, result.stderr[-800:]
    assert (tmp_path / "t.ico").exists()


def test_bootstrap_is_the_single_place_that_fixes_it():
    """Починка живёт в bootstrap: через него проходят все CLI-скрипты.

    Разложить её по скриптам — значит однажды забыть в новом.
    """
    src = (ROOT / "scripts/_lib/bootstrap.py").read_text(encoding="utf-8")

    assert "reconfigure" in src and "utf-8" in src
    # и она реально вызывается из точки входа, а не просто объявлена
    assert "_force_utf8_output()" in src.split("def setup_project_path")[1]


def test_every_cli_script_goes_through_bootstrap():
    """Новый скрипт без setup_project_path() останется незащищённым."""
    missing = []
    for path in sorted((ROOT / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        # check_file_editor.py — разведочный пробник, не часть пайплайна
        if path.name == "check_file_editor.py":
            continue
        if "setup_project_path" not in text:
            missing.append(path.name)

    assert not missing, f"скрипты без bootstrap (и без защиты вывода): {missing}"


def test_ci_sets_utf8_mode():
    """Пояс поверх подтяжек: раннер работает в режиме UTF-8.

    Скрипты чинят себя сами, но шагов в workflow больше, чем скриптов.
    """
    import yaml
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))

    env = workflow["jobs"]["build"].get("env", {})
    assert env.get("PYTHONUTF8") == "1", env
