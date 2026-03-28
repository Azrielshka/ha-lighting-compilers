"""
launcher/services/config_store.py
------------------------------------------------------------
Сервис сохранения и загрузки пользовательских настроек launcher.

Задача файла:
    - сохранять конфиг launcher в JSON
    - загружать конфиг launcher при старте
    - безопасно обрабатывать отсутствие или повреждение файла
"""

# ------------------------------------------------------------
# Импорт стандартных модулей
# ------------------------------------------------------------
from __future__ import annotations

import json
from pathlib import Path


# ------------------------------------------------------------
# Сервис работы с конфигом launcher
# ------------------------------------------------------------
class ConfigStore:
    """
    Сохраняет и загружает пользовательский config launcher.
    """

    def __init__(self, config_file_path: str | Path):
        """
        Инициализация сервиса.

        Параметры:
            config_file_path:
                путь до JSON-файла конфигурации launcher
        """

        self.config_file_path = Path(config_file_path)

    # ------------------------------------------------------------
    # Загрузка конфига из JSON
    # ------------------------------------------------------------
    def load(self) -> dict:
        """
        Загружает config из JSON-файла.

        Возвращает:
            dict с настройками, если файл найден и корректен
            пустой dict, если файла нет или JSON повреждён
        """

        if not self.config_file_path.exists():
            return {}

        try:
            with self.config_file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if isinstance(data, dict):
                return data

            return {}

        except (OSError, json.JSONDecodeError):
            return {}

    # ------------------------------------------------------------
    # Сохранение конфига в JSON
    # ------------------------------------------------------------
    def save(self, data: dict) -> None:
        """
        Сохраняет config в JSON-файл.

        Параметры:
            data:
                словарь с настройками launcher
        """

        self.config_file_path.parent.mkdir(parents=True, exist_ok=True)

        with self.config_file_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)