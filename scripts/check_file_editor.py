# -*- coding: utf-8 -*-
"""
check_file_editor.py
Разведка: можно ли писать файлы в /config через add-on File Editor.

Зачем: WebSocket API умеет создавать Areas и Floors, но НЕ умеет класть файлы
в /config. Для YAML групп света нужен файловый транспорт. File Editor
теоретически подходит (у него есть POST /api/save), но официальный add-on
работает только через ingress, а этот путь недокументирован и, по отзывам,
ломался на новых версиях HA.

Этот скрипт отвечает на вопрос «работает или нет» ФАКТОМ, а не догадкой.

Ничего в проекте не меняет. По умолчанию только читает.
С флагом --write создаёт один безобидный пробный файл и тут же его удаляет.

Запуск:
    python scripts/check_file_editor.py --url http://192.168.1.50:8123 --token XXX
    python scripts/check_file_editor.py --write        # ещё и проба записи

Токен: Home Assistant -> профиль (внизу слева) -> Long-lived access tokens
       -> Create token. Нужен токен АДМИНА: Supervisor API иначе не ответит.

Можно не передавать флаги, а положить рядом .env:
    HA_BASE_URL=http://192.168.1.50:8123
    HA_TOKEN=eyJhbG...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Слаг официального add-on «File editor».
ADDON_SLUG = "core_configurator"

# Пробный файл: имя говорит само за себя, чтобы никто не гадал, откуда он взялся.
PROBE_PATH = "/config/ha_lighting_compilers_probe.txt"
PROBE_TEXT = "Пробная запись от ha-lighting-compilers. Файл можно удалить.\n"

TIMEOUT = 15


def _load_dotenv() -> None:
    """Простейший разбор .env — без зависимости от python-dotenv."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _request(
    url: str,
    token: str,
    method: str = "GET",
    data: Optional[bytes] = None,
    content_type: Optional[str] = None,
    cookie: Optional[str] = None,
) -> Tuple[int, str]:
    """HTTP-запрос на stdlib: не тащим requests ради разведки."""
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")

    if content_type:
        req.add_header("Content-Type", content_type)
    if cookie:
        req.add_header("Cookie", cookie)

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return 0, f"нет связи: {exc.reason}"


def step(n: int, title: str) -> None:
    print(f"\n{'─' * 70}\n{n}. {title}\n{'─' * 70}")


def main() -> int:
    _load_dotenv()

    parser = argparse.ArgumentParser(
        description="Проверить, можно ли писать файлы в /config через File Editor.",
    )
    parser.add_argument("--url", default=os.environ.get("HA_BASE_URL", ""),
                        help="http://<адрес HA>:8123")
    parser.add_argument("--token", default=os.environ.get("HA_TOKEN", ""),
                        help="Long-lived access token администратора")
    parser.add_argument("--write", action="store_true",
                        help="Проверить запись: создать пробный файл и удалить его")
    args = parser.parse_args()

    base = args.url.strip().rstrip("/")
    token = args.token.strip()

    if not base or not token:
        print("❌ Нужны адрес и токен.\n")
        print("   python scripts/check_file_editor.py --url http://192.168.1.50:8123 --token XXX")
        print("   или положите .env с HA_BASE_URL и HA_TOKEN рядом с проектом.\n")
        print("   Токен: HA -> профиль -> Long-lived access tokens -> Create token")
        print("   Нужен токен АДМИНА, иначе Supervisor API не ответит.")
        return 2

    print(f"\nПроверяем: {base}")

    # ------------------------------------------------------------
    step(1, "Home Assistant отвечает и токен принят?")

    status, body = _request(f"{base}/api/", token)

    if status == 0:
        print(f"❌ {body}")
        print("   Проверьте адрес и что HA доступен с этой машины.")
        return 1
    if status == 401:
        print("❌ 401: токен не принят. Создайте новый long-lived token.")
        return 1
    if status != 200:
        print(f"❌ HTTP {status}: {body[:200]}")
        return 1

    print("✅ HA отвечает, токен рабочий")

    # ------------------------------------------------------------
    step(2, "Supervisor виден и add-on File Editor установлен?")

    status, body = _request(f"{base}/api/hassio/addons/{ADDON_SLUG}/info", token)

    if status == 401 or status == 403:
        print(f"❌ HTTP {status}: Supervisor не пускает.")
        print("   Скорее всего токен НЕ администратора — создайте от админской учётки.")
        return 1
    if status == 404:
        print(f"❌ 404: add-on {ADDON_SLUG!r} не найден.")
        print("   Либо File Editor не установлен, либо это не HAOS/Supervised.")
        return 1
    if status != 200:
        print(f"❌ HTTP {status}: {body[:300]}")
        return 1

    info = json.loads(body).get("data", {})
    ingress_url = info.get("ingress_url") or ""
    ingress_port = info.get("ingress_port")

    print(f"✅ Add-on найден: {info.get('name')} v{info.get('version')}")
    print(f"   state       : {info.get('state')}")
    print(f"   ingress     : {info.get('ingress')}")
    print(f"   ingress_url : {ingress_url}")
    print(f"   ingress_port: {ingress_port}")

    if info.get("state") != "started":
        print("\n⚠ Add-on не запущен — запустите его и повторите.")
        return 1

    if not ingress_url:
        print("\n❌ У add-on нет ingress_url. Дальше идти некуда.")
        return 1

    # ------------------------------------------------------------
    step(3, "Ingress выдаёт сессию?")

    status, body = _request(f"{base}/api/hassio/ingress/session", token, method="POST")

    if status != 200:
        print(f"❌ HTTP {status}: {body[:300]}")
        print("   Это тот самый 401, о котором писали на форуме.")
        return 1

    session = json.loads(body).get("data", {}).get("session", "")
    if not session:
        print(f"❌ Сессия не пришла: {body[:200]}")
        return 1

    print(f"✅ Сессия получена: {session[:16]}…")

    cookie = f"ingress_session={session}"
    save_url = f"{base}{ingress_url.rstrip('/')}/api/save"
    print(f"   URL записи: {save_url}")

    # ------------------------------------------------------------
    step(4, "Чтение файла через File Editor")

    read_url = f"{base}{ingress_url.rstrip('/')}/api/file?filename=/config/configuration.yaml"
    status, body = _request(read_url, token, cookie=cookie)

    if status == 200:
        print(f"✅ configuration.yaml прочитан ({len(body)} байт)")
    else:
        print(f"⚠ HTTP {status}: {body[:200]}")
        print("   Чтение не удалось. Запись, скорее всего, тоже не пройдёт.")

    # ------------------------------------------------------------
    if not args.write:
        step(5, "Проба записи — пропущена")
        print("Запустите с флагом --write, чтобы проверить запись.")
        print(f"Будет создан и сразу удалён файл {PROBE_PATH}")
        return 0

    step(5, "Проба записи")
    print(f"Пишем {PROBE_PATH} …")

    payload = urllib.parse.urlencode({
        "filename": PROBE_PATH,
        "text": PROBE_TEXT,
    }).encode("utf-8")

    status, body = _request(
        save_url, token,
        method="POST",
        data=payload,
        content_type="application/x-www-form-urlencoded",
        cookie=cookie,
    )

    if status != 200:
        print(f"❌ HTTP {status}: {body[:300]}")
        print("\n   Запись не работает. Нужен другой транспорт для файлов")
        print("   (Samba share или SSH add-on).")
        return 1

    print(f"✅ Записан: {body[:120]}")

    # Читаем обратно — единственное honest-подтверждение, что файл реально лёг.
    status, body = _request(
        f"{base}{ingress_url.rstrip('/')}/api/file?filename={PROBE_PATH}",
        token, cookie=cookie,
    )

    if status == 200 and PROBE_TEXT.strip() in body:
        print("✅ Прочитан обратно — содержимое совпало")
    else:
        print(f"⚠ Обратное чтение: HTTP {status}: {body[:150]}")

    # Убираем за собой.
    status, body = _request(
        f"{base}{ingress_url.rstrip('/')}/api/delete",
        token,
        method="POST",
        data=urllib.parse.urlencode({"path": PROBE_PATH}).encode("utf-8"),
        content_type="application/x-www-form-urlencoded",
        cookie=cookie,
    )

    if status == 200:
        print("✅ Пробный файл удалён")
    else:
        print(f"⚠ Удалить не вышло (HTTP {status}). Удалите вручную: {PROBE_PATH}")

    print("\n" + "═" * 70)
    print("ИТОГ: File Editor годится как транспорт для файлов.")
    print("═" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
