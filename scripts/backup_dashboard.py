# -*- coding: utf-8 -*-
"""
backup_dashboard.py
Снять бэкап конфига дашборда Lovelace и восстановить его обратно.

Зачем: деплой карточек (`deploy.py --targets lovelace`) пишет конфиг дашборда
ЦЕЛИКОМ (`lovelace/config/save`). Слияние сохраняет ручные views владельца, но
цена ошибки — весь дашборд. Поэтому перед первым LIVE снимаем снимок.

Бэкап без восстановления бэкапом не является, поэтому здесь оба режима:

    # снять (пишет data/backups/<дашборд>-<дата>.json)
    python scripts/backup_dashboard.py --url http://192.168.8.49:8123 \
        --token <АДМИНСКИЙ_ТОКЕН> --dashboard dashboard-tets

    # вернуть как было
    python scripts/backup_dashboard.py --url http://192.168.8.49:8123 \
        --token <АДМИНСКИЙ_ТОКЕН> --dashboard dashboard-tets \
        --restore data/backups/dashboard-tets-2026-07-16_1230.json

Запускать с машины наладчика: она ходит в HA по локальному http, где TLS не
участвует. Токен нужен АДМИНСКИЙ — чтение конфига дашборда и запись требуют прав
администратора.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from scripts._lib.ha_ws import (
    HAWebSocketClient,
    WSConfig,
    WSNotConfigured,
    WSTransportError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "backups"


def backup(client: HAWebSocketClient, dashboard: str, out_dir: Path) -> Path:
    config = client.fetch_dashboard_config(dashboard)
    views = config.get("views", [])

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = out_dir / f"{dashboard}-{stamp}.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                    encoding="utf-8")

    print(f"✔ Бэкап снят: {path}")
    print(f"  views в дашборде: {len(views)}")
    for v in views:
        title = v.get("title", "(без имени)")
        print(f"    • {title:28} path={v.get('path', '—')}")
    print(f"\n  Размер: {path.stat().st_size} байт")
    print("  Вернуть как было:")
    print(f"    python scripts/backup_dashboard.py --url ... --token ... \\")
    print(f"        --dashboard {dashboard} --restore {path}")
    return path


def restore(client: HAWebSocketClient, dashboard: str, path: Path) -> None:
    config = json.loads(path.read_text(encoding="utf-8"))
    views = config.get("views", [])

    print(f"Восстанавливаю «{dashboard}» из {path}")
    print(f"  views в бэкапе: {len(views)}")
    print("  ⚠ Текущий конфиг дашборда будет перезаписан этим снимком.\n")

    client.save_dashboard_config(dashboard, config)
    print("✔ Дашборд восстановлен. Рестарт не нужен — применяется сразу.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Бэкап и восстановление конфига дашборда Lovelace.")
    parser.add_argument("--url", default=os.environ.get("HA_BASE_URL", ""),
                        help="http://<ip>:8123 (локальный адрес объекта)")
    parser.add_argument("--token", default=os.environ.get("HA_TOKEN", ""),
                        help="Long-lived token АДМИНИСТРАТОРА")
    parser.add_argument("--dashboard", default=os.environ.get("HA_DASHBOARD", ""),
                        help="url_path дашборда, напр. dashboard-tets")
    parser.add_argument("--out", default=str(DEFAULT_BACKUP_DIR),
                        help="Куда класть снимки")
    parser.add_argument("--restore", metavar="ФАЙЛ",
                        help="Вернуть дашборд из этого снимка")
    parser.add_argument("--insecure", action="store_true",
                        help="Не проверять TLS-сертификат (самоподписанный https)")
    args = parser.parse_args()

    if not args.dashboard:
        print("❌ Укажите --dashboard (url_path дашборда)", file=sys.stderr)
        return 2

    ws = WSConfig(base_url=args.url, token=args.token, insecure=args.insecure)
    problems = ws.validate()
    if problems:
        print("❌ Проверьте параметры Home Assistant:", file=sys.stderr)
        for p in problems:
            print(f"   • {p}", file=sys.stderr)
        return 2

    print(f"\n=== Дашборд «{args.dashboard}» ===")
    print(f"HA: {ws.describe()}\n")

    client = HAWebSocketClient(ws)

    try:
        if args.restore:
            restore(client, args.dashboard, Path(args.restore))
        else:
            backup(client, args.dashboard, Path(args.out))
    except (WSNotConfigured, WSTransportError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        print("\n   Если отказ по правам — нужен токен АДМИНИСТРАТОРА.",
              file=sys.stderr)
        print("   Если дашборд не найден — проверьте url_path (он с дефисом).",
              file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
