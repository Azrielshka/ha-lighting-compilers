# -*- coding: utf-8 -*-
"""
Workflow релиза — код, который исполняется РЕДКО и только по тегу.

Его нельзя прогнать локально: он собирает EXE под Windows. Значит ошибку в нём
видно только в момент публикации, когда релиз уже ждут. Сборка v3.0.0 падала
дважды подряд — оба раза по мелочи, которую можно было поймать здесь.

Тесты проверяют не логику сборки, а синтаксические ловушки: чем исполняется шаг
и совместим ли с этим его текст.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github/workflows/release.yml"


def _steps() -> list:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data["jobs"]["build"]["steps"]


def _run_steps(shell: str = None) -> list:
    """Шаги с run-блоком. shell=None -> все; иначе только с этим шеллом.

    На windows-latest умолчание — pwsh, поэтому отсутствие ключа shell
    означает именно его.
    """
    out = []
    for step in _steps():
        if "run" not in step:
            continue
        actual = step.get("shell", "pwsh")
        if shell is None or actual == shell:
            out.append((step["name"], step["run"]))
    return out


def test_powershell_steps_use_hash_comments():
    """`REM` — синтаксис cmd. В PowerShell это НЕИЗВЕСТНАЯ КОМАНДА.

    GitHub Actions запускает pwsh с $ErrorActionPreference = 'stop', поэтому
    строка комментария роняет весь шаг. Ровно на этом упала вторая попытка
    собрать v3.0.0: комментарии я писал в стиле cmd, а шаг исполняется pwsh.
    В PowerShell комментарий — `#`.
    """
    offenders = []
    for name, run in _run_steps("pwsh"):
        for line in run.split("\n"):
            if re.match(r"^\s*REM(\s|$)", line, re.I):
                offenders.append(f"{name}: {line.strip()[:60]}")

    assert not offenders, (
        "cmd-комментарии REM в PowerShell-шаге — шаг упадёт:\n  "
        + "\n  ".join(offenders)
    )


def test_bash_steps_use_hash_comments_too():
    """В bash `REM` тоже не комментарий, а команда."""
    offenders = [
        f"{name}: {line.strip()[:60]}"
        for name, run in _run_steps("bash")
        for line in run.split("\n")
        if re.match(r"^\s*REM(\s|$)", line, re.I)
    ]
    assert not offenders, offenders


def test_files_the_workflow_copies_exist_in_repo():
    """`copy X release\\Y` упадёт, если X нет в репозитории.

    Проверяем источники: их отсутствие — отказ шага, а не тихий пропуск.
    """
    root = WORKFLOW.parent.parent.parent
    missing = []
    for name, run in _run_steps():
        for match in re.finditer(r"^\s*(?:copy|xcopy)\s+([^\s*]+)\s", run, re.M):
            src = match.group(1).replace("\\", "/")
            if src.startswith("dist/"):        # продукт сборки, его ещё нет
                continue
            if not (root / src).exists():
                missing.append(f"{name}: {src}")

    assert not missing, f"workflow копирует несуществующее: {missing}"


def test_release_archive_gets_runtime_requirements_only():
    """В архив едет рантайм-список, не dev и не gui."""
    prepare = dict(_run_steps())["Prepare release folder"]

    assert "copy requirements.txt release" in prepare
    assert "requirements-dev" not in prepare
    assert "requirements-gui" not in prepare


def test_version_check_runs_before_anything_is_built():
    """Сверка версии обязана стоять до сборки.

    Иначе на расхождении мы сначала потратим минуты на PyInstaller, а упадём
    всё равно.
    """
    names = [s["name"] for s in _steps()]

    assert names.index("Check version matches tag") < names.index("Build EXE")


def test_icon_is_built_before_exe_needs_it():
    """--icon ссылается на файл, который делает предыдущий шаг."""
    names = [s["name"] for s in _steps()]
    build_exe = dict(_run_steps())["Build EXE"]

    assert names.index("Build icon") < names.index("Build EXE")
    assert "--icon build/launcher.ico" in build_exe

    icon_step = dict(_run_steps())["Build icon"]
    assert "build/launcher.ico" in icon_step, "шаги расходятся в пути к .ico"
