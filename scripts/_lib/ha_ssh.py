# -*- coding: utf-8 -*-
"""
ha_ssh.py
Транспорт файлов на Home Assistant по SFTP.

Модуль намеренно тупой: он умеет «положи файл сюда» и ничего не знает ни про
группы света, ни про автоматизации. Раскладка путей живёт в ha_targets.py,
что именно деплоить — решает deploy.py. Если завтра транспорт сменится,
переписывается только этот файл.

Проверено на живом HA (2026-07-14): хендшейк, ключ, SFTP, запись со сверкой
размера, чтение обратно, удаление. Разведка — scripts/check_sftp.py.

Требования к add-on «Advanced SSH & Web Terminal» на объекте
------------------------------------------------------------
    sftp: true          ← по умолчанию ВЫКЛЮЧЕН, без него ничего не поедет
    username: root      ← аддон требует именно root при включённом SFTP
    Network: порт наружу (у наладчика локальный, снаружи может быть другой)
    authorized_keys: публичный ключ

⚠ File Editor как транспорт НЕ ГОДИТСЯ: прокси /api/hassio/ в Home Assistant
работает по белому списку, и ни ingress/session, ни addons/*/info в него не
входят — 401 при любом токене, даже админском (проверено check_file_editor.py).
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

try:
    import paramiko
except ImportError:  # без paramiko недоступен только деплой, остальное работает
    paramiko = None  # type: ignore


# ============================================================
# ЖЁСТКИЕ КОНСТАНТЫ — одинаковы на любом объекте
# ============================================================

# ⚠ Это не настройка, а требование образа HA OS: без прибитых алгоритмов
# соединение рвётся с `Corrupted MAC on input`.
REQUIRED_CIPHERS = ("aes256-ctr",)
REQUIRED_DIGESTS = ("hmac-sha2-256-etm@openssh.com",)

# ⚠ В paramiko список MAC-алгоритмов называется digests — при том что и в
# OpenSSH, и в ssh_config, и в документации это «MACs». На этом легко
# споткнуться: options.macs молча не существует.

CONNECT_TIMEOUT = 15


# ============================================================
# ПАРАМЕТРЫ — свои на каждом объекте
# ============================================================

DEFAULT_PORT = 22
DEFAULT_USER = "root"


class SSHNotConfigured(RuntimeError):
    """Не хватает параметров подключения."""


class SSHTransportError(RuntimeError):
    """Не удалось подключиться или передать файл."""


@dataclass(frozen=True)
class SSHConfig:
    """
    Параметры подключения. Приходят из полей лаунчера или флагов CLI —
    константами быть не могут: на разных объектах разные порты, и однажды
    кто-то напоролся на чужой sshd, слушавший соседний порт.

    Только ключ, без пароля: секрет не пришлось бы хранить в конфиге лаунчера,
    а лишняя ветка авторизации всё равно осталась бы непроверенной.
    """

    host: str
    port: int = DEFAULT_PORT
    user: str = DEFAULT_USER
    key_path: Optional[str] = None

    def validate(self) -> List[str]:
        """Что мешает подключиться. Пустой список — всё на месте."""
        problems: List[str] = []

        if not self.host.strip():
            problems.append("не задан хост Home Assistant")

        if not (1 <= self.port <= 65535):
            problems.append(f"некорректный порт: {self.port}")

        if not self.user.strip():
            problems.append("не задан пользователь SSH")

        if not self.key_path:
            problems.append("не задан путь к SSH-ключу")
        elif not Path(self.key_path).expanduser().exists():
            problems.append(f"SSH-ключ не найден: {self.key_path}")

        return problems

    def describe(self) -> str:
        return f"{self.user}@{self.host}:{self.port} (ключ {self.key_path})"


# ============================================================
# КЛИЕНТ
# ============================================================

class HASSHClient:
    """
    Копирование файлов на Home Assistant по SFTP.

        with HASSHClient(config) as client:
            client.ensure_dir("/config/includes/packages")
            client.put(local_path, "/config/includes/packages/zm_lights.yaml")
    """

    def __init__(self, config: SSHConfig):
        self.config = config
        self._transport = None
        self._sftp = None

    def __enter__(self) -> "HASSHClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------
    # Подключение
    # ------------------------------------------------------------

    def connect(self) -> None:
        """Поднять SSH-сессию и открыть SFTP."""
        if paramiko is None:
            raise SSHTransportError(
                "не установлен paramiko — переустановите зависимости:\n"
                "   pip install -r requirements.txt"
            )

        problems = self.config.validate()
        if problems:
            raise SSHNotConfigured("; ".join(problems))

        sock = self._open_socket()
        transport = paramiko.Transport(sock)

        # ⚠ Главная строка модуля. Образ HA OS не договаривается о шифрах сам.
        options = transport.get_security_options()
        options.ciphers = REQUIRED_CIPHERS
        options.digests = REQUIRED_DIGESTS

        try:
            transport.start_client(timeout=CONNECT_TIMEOUT)
        except paramiko.SSHException as exc:
            transport.close()
            hint = ""
            if "mac" in str(exc).lower():
                hint = "\n   Это Corrupted MAC — сервер не принял наши алгоритмы."
            raise SSHTransportError(f"SSH-хендшейк не прошёл: {exc}{hint}") from exc

        try:
            transport.auth_publickey(self.config.user, self._load_key())
        except paramiko.AuthenticationException as exc:
            transport.close()
            raise SSHTransportError(
                f"ключ отклонён для пользователя {self.config.user!r}.\n"
                f"   Проверьте, что публичная часть добавлена в authorized_keys\n"
                f"   аддона и аддон ПЕРЕЗАПУЩЕН после сохранения."
            ) from exc
        except paramiko.SSHException as exc:
            transport.close()
            raise SSHTransportError(f"ошибка аутентификации: {exc}") from exc

        self._sftp = self._open_sftp(transport)
        self._transport = transport

    def _open_socket(self):
        try:
            return socket.create_connection(
                (self.config.host, self.config.port), timeout=CONNECT_TIMEOUT
            )
        except OSError as exc:
            raise SSHTransportError(
                f"не могу подключиться к {self.config.host}:{self.config.port} — {exc}\n"
                f"   Проверьте, что аддон SSH запущен и порт выставлен наружу."
            ) from exc

    def _load_key(self):
        """Тип ключа заранее неизвестен — пробуем поддерживаемые."""
        path = str(Path(self.config.key_path).expanduser())
        errors: List[str] = []

        for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try:
                return key_class.from_private_key_file(path)
            except paramiko.SSHException as exc:
                errors.append(f"{key_class.__name__}: {exc}")

        raise SSHTransportError(
            f"не удалось прочитать ключ {path}:\n   " + "\n   ".join(errors)
        )

    @staticmethod
    def _open_sftp(transport):
        """
        Если в аддоне не включён sftp: true, SFTP-канал не откроется.
        Падаем с инструкцией, а не откатываемся молча на другой протокол:
        тихая подмена транспорта — то, чего никто не ждёт и что мучительно
        отлаживать.
        """
        try:
            sftp = paramiko.SFTPClient.from_transport(transport)
        except paramiko.SSHException as exc:
            transport.close()
            raise SSHTransportError(_SFTP_OFF_HINT.format(error=exc)) from exc

        if sftp is None:
            transport.close()
            raise SSHTransportError(_SFTP_OFF_HINT.format(error="канал не открылся"))

        return sftp

    # ------------------------------------------------------------
    # Файловые операции
    # ------------------------------------------------------------

    def ensure_dir(self, remote_dir: str) -> bool:
        """
        Создать папку, если её нет. Возвращает True, если создали.

        Идём по частям: в SFTP нет mkdir -p, а на свежем объекте может не быть
        ни includes/, ни automations/ внутри неё.
        """
        self._require_sftp()

        if self.exists(remote_dir):
            return False

        created = False
        current = ""

        for part in [p for p in remote_dir.strip("/").split("/") if p]:
            current = f"{current}/{part}"

            if self.exists(current):
                continue

            try:
                self._sftp.mkdir(current)
                created = True
            except OSError as exc:
                raise SSHTransportError(
                    f"не удалось создать папку {current}: {exc}"
                ) from exc

        return created

    def put(self, local: Path, remote: str) -> int:
        """
        Положить файл. Существующий перезаписывается целиком.

        Возвращает записанный размер. Сверяем его с локальным: без сверки
        оборванная передача отрапортовала бы об успехе, и на объекте оказался
        бы обрезанный YAML — Home Assistant не загрузил бы его молча.
        """
        self._require_sftp()

        if not local.exists():
            raise SSHTransportError(f"локальный файл не найден: {local}")

        expected = local.stat().st_size

        try:
            self._sftp.put(str(local), remote)
        except OSError as exc:
            raise SSHTransportError(f"не удалось записать {remote}: {exc}") from exc

        written = self._sftp.stat(remote).st_size

        if written != expected:
            raise SSHTransportError(
                f"{remote}: записано {written} байт вместо {expected} — "
                f"передача оборвалась"
            )

        return written

    def exists(self, remote: str) -> bool:
        self._require_sftp()

        try:
            self._sftp.stat(remote)
            return True
        except FileNotFoundError:
            return False

    def listdir(self, remote_dir: str) -> List[str]:
        """Для диагностики: что лежит в папке."""
        self._require_sftp()

        try:
            return sorted(self._sftp.listdir(remote_dir))
        except OSError as exc:
            raise SSHTransportError(f"не могу прочитать {remote_dir}: {exc}") from exc

    # ------------------------------------------------------------

    def _require_sftp(self) -> None:
        if self._sftp is None:
            raise SSHTransportError("нет соединения — сначала connect()")

    def close(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None

        if self._transport is not None:
            self._transport.close()
            self._transport = None


_SFTP_OFF_HINT = (
    "SFTP недоступен ({error}).\n"
    "   Включите в настройках аддона «Advanced SSH & Web Terminal»:\n"
    "       sftp: true\n"
    "       username: root\n"
    "   и ПЕРЕЗАПУСТИТЕ аддон."
)
