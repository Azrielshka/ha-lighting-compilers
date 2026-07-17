# -*- coding: utf-8 -*-
"""
SFTP-транспорт: параметры, шифры, обработка отказов.

Сам канал проверен на живом HA (2026-07-14): хендшейк, ключ, SFTP, запись
со сверкой размера, создание вложенных папок. Разведка — scripts/check_sftp.py.
Здесь — то, что можно проверить без сети.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts._lib.ha_ssh import (
    CONNECT_TIMEOUT,
    REQUIRED_CIPHERS,
    REQUIRED_DIGESTS,
    HASSHClient,
    SSHConfig,
    SSHNotConfigured,
    SSHTransportError,
)


@pytest.fixture
def key(tmp_path) -> Path:
    path = tmp_path / "id_ed25519"
    path.write_text("fake", encoding="utf-8")
    return path


# ============================================================
# ШИФРЫ — не настройка, а требование образа HA OS
# ============================================================

def test_ciphers_are_pinned():
    """
    Без прибитых алгоритмов образ HA OS рвёт соединение с
    `Corrupted MAC on input`. Это проверено на живом объекте, поэтому
    константы менять нельзя без повторной проверки.
    """
    assert REQUIRED_CIPHERS == ("aes256-ctr",)
    assert REQUIRED_DIGESTS == ("hmac-sha2-256-etm@openssh.com",)


def test_paramiko_calls_macs_digests():
    """
    В paramiko список MAC-алгоритмов называется digests — при том что в
    OpenSSH, ssh_config и документации это «MACs». options.macs молча не
    существует: на первом прогоне разведка на этом и споткнулась.
    """
    paramiko = pytest.importorskip("paramiko")

    assert "digests" in dir(paramiko.SecurityOptions)
    assert "macs" not in dir(paramiko.SecurityOptions)


def test_required_algorithms_are_supported_by_paramiko():
    """Прибитые алгоритмы должны быть среди тех, что paramiko вообще умеет."""
    paramiko = pytest.importorskip("paramiko")

    assert set(REQUIRED_CIPHERS) <= set(paramiko.Transport._preferred_ciphers)
    assert set(REQUIRED_DIGESTS) <= set(paramiko.Transport._preferred_macs)


# ============================================================
# ПАРАМЕТРЫ ПОДКЛЮЧЕНИЯ
# ============================================================

def test_valid_config(key):
    config = SSHConfig(host="ha.local", port=2223, user="root", key_path=str(key))

    assert config.validate() == []


def test_defaults():
    config = SSHConfig(host="ha.local")

    assert config.port == 22
    assert config.user == "root"


def test_missing_host(key):
    problems = SSHConfig(host="", key_path=str(key)).validate()

    assert any("хост" in p for p in problems)


def test_bad_port(key):
    problems = SSHConfig(host="ha", port=99999, key_path=str(key)).validate()

    assert any("порт" in p for p in problems)


def test_missing_key():
    problems = SSHConfig(host="ha").validate()

    assert any("ключ" in p for p in problems)


def test_key_file_not_found():
    problems = SSHConfig(host="ha", key_path="/нет/такого").validate()

    assert any("не найден" in p for p in problems)


def test_key_path_expands_tilde(tmp_path, monkeypatch):
    """Наладчик напишет ~/.ssh/key — путь должен разворачиваться."""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "k").write_text("x", encoding="utf-8")

    assert SSHConfig(host="ha", key_path="~/.ssh/k").validate() == []


def test_password_is_not_supported():
    """
    Только ключ. Пароль означал бы хранить секрет в конфиге лаунчера, а
    лишняя ветка авторизации всё равно осталась бы непроверенной.
    """
    assert "password" not in SSHConfig.__dataclass_fields__


def test_describe_shows_target(key):
    described = SSHConfig(host="ha", port=2223, key_path=str(key)).describe()

    assert "root@ha:2223" in described


# ============================================================
# ОТКАЗЫ
# ============================================================

def test_connect_refuses_bad_config():
    client = HASSHClient(SSHConfig(host="", key_path=None))

    with pytest.raises(SSHNotConfigured):
        client.connect()


def test_operations_without_connect(key, tmp_path):
    """Файловые методы до connect() должны падать внятно."""
    client = HASSHClient(SSHConfig(host="ha", key_path=str(key)))

    with pytest.raises(SSHTransportError, match="нет соединения"):
        client.exists("/config")

    with pytest.raises(SSHTransportError, match="нет соединения"):
        client.put(tmp_path / "x", "/config/x")


def test_unreachable_host_explains(key):
    """
    Закрытый порт на localhost отказывает сразу — тест не ждёт таймаут.
    (Недостижимый адрес вроде 192.0.2.1 висел бы CONNECT_TIMEOUT секунд.)
    """
    config = SSHConfig(host="127.0.0.1", port=1, key_path=str(key))
    client = HASSHClient(config)

    with pytest.raises(SSHTransportError, match="не могу подключиться"):
        client.connect()


def test_timeout_is_bounded():
    """Наладчик не должен ждать вечно, если HA недоступен."""
    assert 5 <= CONNECT_TIMEOUT <= 30


def test_context_manager_closes(key, monkeypatch):
    """Соединение закрывается даже при ошибке внутри блока."""
    closed = []

    client = HASSHClient(SSHConfig(host="ha", key_path=str(key)))
    monkeypatch.setattr(client, "connect", lambda: None)
    monkeypatch.setattr(client, "close", lambda: closed.append(True))

    with pytest.raises(ValueError):
        with client:
            raise ValueError("что-то пошло не так")

    assert closed == [True]
