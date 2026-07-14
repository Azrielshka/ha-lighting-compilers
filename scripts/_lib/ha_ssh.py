# -*- coding: utf-8 -*-
"""
ha_ssh.py
Транспорт файлов на Home Assistant по SSH.

⚠ ЗАГОТОВКА. Копирование файлов НЕ РЕАЛИЗОВАНО.
Всё, что здесь есть сегодня — параметры подключения и их проверка.
`--live` в deploy.py честно откажется работать, а не сделает вид, что залил.

Что известно про транспорт (проверено на живом HA, см.
uncledrew/ssh_connection_cooldrew.md):

1. Файлы кладём через add-on «Advanced SSH & Web Terminal».
   Официальный File Editor НЕ ГОДИТСЯ: прокси /api/hassio/ в Home Assistant
   работает по белому списку, и ни ingress/session, ни addons/*/info в него
   не входят — 401 при любом токене, даже админском.

2. SFTP в аддоне по умолчанию ВЫКЛЮЧЕН. Пока он выключен, работает только
   протокол SCP (`scp -O`, legacy-режим). Если включить в аддоне
   `sftp: true` (при `username: root`), SFTP заработает — и тогда код
   становится проще: paramiko умеет его нативно, включая mkdir и проверку
   существования файла.

3. ⚠ ШИФРЫ ОБЯЗАТЕЛЬНЫ. Без них соединение падает с `Corrupted MAC on input`:
       Ciphers = aes256-ctr
       MACs    = hmac-sha2-256-etm@openssh.com

4. Параметры СВОИ НА КАЖДОМ ОБЪЕКТЕ (порт, юзер, ключ). На одном из объектов
   порт 2223, а 2222 на том же хосте — чужой sshd, который отклоняет ключ.
   Поэтому это поля в лаунчере, а не константы.

Что осталось сделать:
    - выбрать протокол (SFTP предпочтительнее, требует sftp: true в аддоне)
    - paramiko: Transport с прибитыми ciphers/macs, авторизация по ключу
    - mkdir -p для отсутствующих папок
    - put() файлов из плана
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Без этих алгоритмов образ HA OS отвечает `Corrupted MAC on input`.
REQUIRED_CIPHERS = ("aes256-ctr",)
REQUIRED_MACS = ("hmac-sha2-256-etm@openssh.com",)

DEFAULT_PORT = 22
DEFAULT_USER = "root"


class SSHNotConfigured(RuntimeError):
    """Не хватает параметров подключения."""


class SSHTransportNotImplemented(NotImplementedError):
    """Транспорт ещё не подключён — честно отказываемся вместо тихой заглушки."""


@dataclass(frozen=True)
class SSHConfig:
    """Параметры подключения к SSH-аддону Home Assistant."""

    host: str
    port: int = DEFAULT_PORT
    user: str = DEFAULT_USER

    # Путь к приватному ключу. Публичный кладётся в authorized_keys аддона.
    key_path: Optional[str] = None

    # Пароль — запасной вариант; ключ надёжнее и не требует хранить секрет.
    password: Optional[str] = None

    def validate(self) -> List[str]:
        """Что мешает подключиться. Пустой список — всё на месте."""
        problems: List[str] = []

        if not self.host.strip():
            problems.append("не задан хост Home Assistant")

        if not (1 <= self.port <= 65535):
            problems.append(f"некорректный порт: {self.port}")

        if not self.user.strip():
            problems.append("не задан пользователь SSH")

        if not self.key_path and not self.password:
            problems.append("нужен либо путь к SSH-ключу, либо пароль")

        if self.key_path and not Path(self.key_path).exists():
            problems.append(f"SSH-ключ не найден: {self.key_path}")

        return problems

    def describe(self) -> str:
        auth = f"ключ {self.key_path}" if self.key_path else "пароль"
        return f"{self.user}@{self.host}:{self.port} ({auth})"


class HASSHClient:
    """
    Клиент копирования файлов на Home Assistant.

    ⚠ ЗАГОТОВКА: методы записи бросают SSHTransportNotImplemented.
    """

    def __init__(self, config: SSHConfig):
        self.config = config

    def connect(self) -> None:
        raise SSHTransportNotImplemented(
            "SSH-транспорт ещё не подключён.\n"
            "   Файлы придётся залить вручную — deploy.py --dry-run покажет,\n"
            "   что и куда."
        )

    def ensure_dir(self, remote_dir: str) -> None:
        raise SSHTransportNotImplemented("SSH-транспорт ещё не подключён")

    def put(self, local: Path, remote: str) -> None:
        raise SSHTransportNotImplemented("SSH-транспорт ещё не подключён")

    def close(self) -> None:
        pass
