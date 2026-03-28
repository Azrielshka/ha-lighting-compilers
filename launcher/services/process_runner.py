"""
launcher/services/process_runner.py
------------------------------------------------------------
Сервис запуска CLI-скриптов проекта через subprocess.

Задача файла:
    - собрать команду запуска
    - выполнить Python-скрипт
    - вернуть stdout / stderr / exit code
"""

# ------------------------------------------------------------
# Импорт стандартных модулей
# ------------------------------------------------------------
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


# ------------------------------------------------------------
# Результат выполнения процесса
# ------------------------------------------------------------
@dataclass
class ProcessRunResult:
    """
    Результат выполнения одного CLI-скрипта.
    """

    command: List[str]
    returncode: int
    stdout: str
    stderr: str


# ------------------------------------------------------------
# Сервис запуска процессов
# ------------------------------------------------------------
class ProcessRunner:
    """
    Запускает Python-скрипты проекта через subprocess.run().
    """

    def run_python_script(
        self,
        python_executable: str,
        project_root: str,
        script_relative_path: str,
        script_args: Optional[List[str]] = None,
    ) -> ProcessRunResult:
        """
        Запускает Python-скрипт проекта.

        Параметры:
            python_executable:
                путь до python.exe / интерпретатора

            project_root:
                корень проекта ha-college-lighting

            script_relative_path:
                относительный путь до скрипта внутри проекта,
                например: scripts/normalize_excel.py

            script_args:
                дополнительные CLI-аргументы для скрипта,
                например: ["--excel", "C:/path/file.xlsx"]
        """

        # ------------------------------------------------------------
        # Подготавливаем пути
        # ------------------------------------------------------------
        project_root_path = Path(project_root).resolve()
        script_path = (project_root_path / script_relative_path).resolve()

        # ------------------------------------------------------------
        # Формируем команду запуска
        #
        # Базовый формат:
        #   <python_executable> <script_path>
        #
        # Если переданы script_args:
        #   <python_executable> <script_path> <arg1> <arg2> ...
        # ------------------------------------------------------------
        command = [
            str(Path(python_executable).resolve()),
            str(script_path),
        ]

        if script_args:
            command.extend(script_args)

        # ------------------------------------------------------------
        # Формируем окружение дочернего процесса.
        #
        # Зачем это нужно:
        #   при запуске из GUI на Windows Python может использовать
        #   cp1251 для stdout/stderr.
        #
        # Это ломает:
        #   - emoji в print(...)
        #   - кириллицу в выводе
        #
        # Поэтому принудительно включаем UTF-8 режим.
        # ------------------------------------------------------------
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        # ------------------------------------------------------------
        # Запускаем процесс
        #
        # cwd=project_root_path:
        #   важно, чтобы скрипт выполнялся из корня проекта
        #
        # capture_output=True:
        #   собираем stdout и stderr
        #
        # text=True:
        #   получаем строки, а не bytes
        #
        # encoding="utf-8", errors="replace":
        #   декодируем вывод как UTF-8
        # ------------------------------------------------------------
        completed = subprocess.run(
            command,
            cwd=str(project_root_path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )

        # ------------------------------------------------------------
        # Возвращаем структурированный результат
        # ------------------------------------------------------------
        return ProcessRunResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )