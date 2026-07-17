# -*- coding: utf-8 -*-
"""
check_sftp.py
Разведка: работает ли SFTP-канал на Home Assistant.

Отвечает фактом, а не догадкой — до того, как писать транспорт.
Тот же принцип, что с check_file_editor.py: там разведка сэкономила день
работы над тупиковым путём (прокси /api/hassio/ закрыт белым списком).

Ничего в проекте не меняет. По умолчанию только читает.
С флагом --write создаёт пробный файл и тут же удаляет.

Запуск:
    python scripts/check_sftp.py --host ha.local --port 22 --key ~/.ssh/key
    python scripts/check_sftp.py --write        # ещё и проба записи

Требования к add-on «Advanced SSH & Web Terminal» на объекте:
    sftp: true          ← по умолчанию ВЫКЛЮЧЕН
    username: root      ← аддон требует root при включённом SFTP
    Network: порт наружу
    authorized_keys: публичный ключ наладчика
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import List, Optional

try:
    import paramiko
except ImportError:
    paramiko = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ⚠ Без этих алгоритмов образ HA OS отвечает `Corrupted MAC on input`.
REQUIRED_CIPHERS = ("aes256-ctr",)
REQUIRED_MACS = ("hmac-sha2-256-etm@openssh.com",)

TIMEOUT = 15

PROBE_PATH = "/config/ha_lighting_compilers_probe.txt"
PROBE_TEXT = "Пробная запись от ha-lighting-compilers. Файл можно удалить.\n"

# Папки, которые деплою понадобятся.
NEEDED_DIRS = (
    "/config/includes/packages",
    "/config/includes/scripts",
    "/config/includes/automations",
    "/config/blueprints/automation/zone_manager",
)


def step(n: int, title: str) -> None:
    print(f"\n{'─' * 70}\n{n}. {title}\n{'─' * 70}")


def load_key(path: str):
    """Тип ключа заранее неизвестен — пробуем поддерживаемые."""
    errors: List[str] = []

    for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return key_class.from_private_key_file(path)
        except paramiko.SSHException as exc:
            errors.append(f"{key_class.__name__}: {exc}")

    print(f"❌ Не удалось прочитать ключ {path}:")
    for e in errors:
        print(f"   {e}")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проверить SFTP-канал на Home Assistant.",
    )
    parser.add_argument("--host", default=os.environ.get("HA_SSH_HOST", ""))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("HA_SSH_PORT", "22")))
    parser.add_argument("--user", default=os.environ.get("HA_SSH_USER", "root"))
    parser.add_argument("--key", default=os.environ.get("HA_SSH_KEY", ""))
    parser.add_argument("--write", action="store_true",
                        help="Проверить запись: создать пробный файл и удалить его")
    args = parser.parse_args()

    if paramiko is None:
        print("❌ Не установлен paramiko: pip install paramiko")
        return 2

    if not args.host or not args.key:
        print("❌ Нужны --host и --key\n")
        print("   python scripts/check_sftp.py --host ha.example --port 2223 \\")
        print("                                --key ~/.ssh/uncledrew/ha-lighting-deploy")
        return 2

    key_path = str(Path(args.key).expanduser())

    print(f"\nПроверяем: {args.user}@{args.host}:{args.port}")
    print(f"Ключ:      {key_path}")

    # ------------------------------------------------------------
    step(1, "TCP: порт вообще открыт?")

    try:
        sock = socket.create_connection((args.host, args.port), timeout=TIMEOUT)
    except OSError as exc:
        print(f"❌ {exc}")
        print("   Проверьте, что аддон SSH запущен и порт выставлен наружу.")
        return 1

    print(f"✅ {args.host}:{args.port} отвечает")

    # ------------------------------------------------------------
    step(2, "SSH-хендшейк с прибитыми шифрами")
    print(f"   Ciphers: {', '.join(REQUIRED_CIPHERS)}")
    print(f"   MACs:    {', '.join(REQUIRED_MACS)}")

    transport = paramiko.Transport(sock)

    # ⚠ Здесь главное: образ HA OS не договаривается о шифрах сам.
    # В paramiko список MAC называется digests, а не macs — на этом легко
    # споткнуться, потому что в ssh_config и в OpenSSH это «MACs».
    options = transport.get_security_options()
    options.ciphers = REQUIRED_CIPHERS
    options.digests = REQUIRED_MACS

    try:
        transport.start_client(timeout=TIMEOUT)
    except paramiko.SSHException as exc:
        print(f"❌ {exc}")
        if "MAC" in str(exc) or "mac" in str(exc):
            print("   Это тот самый Corrupted MAC — алгоритмы не совпали.")
        transport.close()
        return 1

    print(f"✅ Хендшейк прошёл, сервер: {transport.remote_version}")

    # ------------------------------------------------------------
    step(3, "Аутентификация по ключу")

    key = load_key(key_path)
    if key is None:
        transport.close()
        return 1

    try:
        transport.auth_publickey(args.user, key)
    except paramiko.AuthenticationException:
        print(f"❌ Ключ отклонён для пользователя {args.user!r}")
        print("   Проверьте, что публичная часть добавлена в authorized_keys аддона")
        print("   и аддон ПЕРЕЗАПУЩЕН после сохранения.")
        transport.close()
        return 1
    except paramiko.SSHException as exc:
        print(f"❌ {exc}")
        transport.close()
        return 1

    print(f"✅ Аутентификация прошла ({args.user})")

    # ------------------------------------------------------------
    step(4, "SFTP: открывается?")

    try:
        sftp = paramiko.SFTPClient.from_transport(transport)
    except paramiko.SSHException as exc:
        sftp = None
        print(f"❌ {exc}")

    if sftp is None:
        print("❌ SFTP недоступен.")
        print("\n   Включите в настройках аддона «Advanced SSH & Web Terminal»:")
        print("       sftp: true")
        print("       username: root")
        print("   и ПЕРЕЗАПУСТИТЕ аддон.")
        transport.close()
        return 1

    print("✅ SFTP работает")

    # ------------------------------------------------------------
    step(5, "Что лежит в /config")

    try:
        entries = sorted(sftp.listdir("/config"))
    except OSError as exc:
        print(f"❌ Не могу прочитать /config: {exc}")
        sftp.close()
        transport.close()
        return 1

    print(f"✅ {len(entries)} записей\n")
    for name in entries[:25]:
        print(f"   {name}")
    if len(entries) > 25:
        print(f"   … ещё {len(entries) - 25}")

    print("\n   Папки, которые нужны деплою:")
    for path in NEEDED_DIRS:
        try:
            sftp.stat(path)
            print(f"   ✓ {path}")
        except FileNotFoundError:
            print(f"   — {path}  (будет создана)")

    # ------------------------------------------------------------
    if not args.write:
        step(6, "Проба записи — пропущена")
        print(f"Запустите с --write, чтобы проверить запись.")
        print(f"Будет создан и сразу удалён {PROBE_PATH}")
        sftp.close()
        transport.close()
        return 0

    step(6, "Проба записи")

    try:
        with sftp.open(PROBE_PATH, "w") as f:
            f.write(PROBE_TEXT)
        print(f"✅ Записан {PROBE_PATH}")

        size = sftp.stat(PROBE_PATH).st_size
        expected = len(PROBE_TEXT.encode("utf-8"))
        print(f"   размер: {size} байт (ожидали {expected})")

        with sftp.open(PROBE_PATH, "r") as f:
            content = f.read().decode("utf-8")

        if content == PROBE_TEXT:
            print("✅ Прочитан обратно — содержимое совпало")
        else:
            print(f"⚠ Содержимое не совпало: {content!r}")

        sftp.remove(PROBE_PATH)
        print("✅ Пробный файл удалён")

    except OSError as exc:
        print(f"❌ {exc}")
        print(f"   Если файл остался — удалите вручную: {PROBE_PATH}")
        sftp.close()
        transport.close()
        return 1

    sftp.close()
    transport.close()

    print("\n" + "═" * 70)
    print("ИТОГ: SFTP-канал работает. Транспорт можно строить на нём.")
    print("═" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
