# -*- coding: utf-8 -*-
"""
deploy.py
Доставка сгенерированной конфигурации на Home Assistant.

Файлы едут по SFTP (add-on «Advanced SSH & Web Terminal») — транспорт проверен
на живом HA. Пространства пока не едут: WebSocket-клиент ещё заготовка, и он
честно откажется работать, а не сделает вид, что создал.

Dry-run по умолчанию: показывает, что и куда поедет. `--live` отправляет.

Что и куда
----------
    Группы света   -> /config/includes/packages/zm_*.yaml       (SCP)
    Скрипты        -> /config/includes/scripts/zm_scripts.yaml  (SCP)
    Автоматизации  -> /config/includes/automations/zm_*.yaml    (SCP)
    Blueprint'ы    -> /config/blueprints/automation/zone_manager/ (SCP)
    Пространства   -> реестры HA                                (WebSocket)

Файлы перезаписываются целиком: «сгенерировал → залил». Мусор не копится —
имена фиксированы, и удалённое из таблицы просто исчезает из файла.
Файлы наладчика (без префикса zm_) не трогаются никогда.

⚠ РЕСТАРТ HOME ASSISTANT — ВРУЧНУЮ.
Деплой его не делает и делать не будет (решение владельца). Без рестарта
изменения не применятся: группы света объявлены через YAML-платформу
`light: - platform: group`, у которой нет сервиса reload.
"""

from __future__ import annotations

from _lib.bootstrap import setup_project_path
setup_project_path()

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

import yaml

from scripts._lib.ha_views import diff_summary, merge_views, order_views

from scripts._lib.ha_ssh import (
    HASSHClient,
    SSHConfig,
    SSHNotConfigured,
    SSHTransportError,
)
from scripts._lib.ha_targets import (
    HA_CONFIG_ROOT,
    TARGET_TITLES,
    TARGETS,
    Plan,
    build_plan,
    missing_pipeline_steps,
)
from scripts._lib.ha_ws import (
    HAWebSocketClient,
    WSConfig,
    WSNotConfigured,
    WSTransportError,
    build_areas_plan,
    load_areas_file,
)

__version__ = "0.1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


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


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} Б"
    return f"{size / 1024:.1f} КБ"


# ============================================================
# ОТЧЁТ
# ============================================================

def print_plan(plan: Plan, targets: List[str], data_dir: Path) -> None:
    """Показать, что поедет. Это и есть основная ценность dry-run."""
    print("📋 План деплоя\n")

    by_target = {t: [f for f in plan.files if f.target == t] for t in TARGETS}

    for target in TARGETS:
        if target not in targets:
            continue

        title = TARGET_TITLES[target]

        if target == "areas":
            _print_areas_plan(plan, title)
            continue

        if target == "lovelace":
            _print_lovelace_plan(plan, title)
            continue

        files = by_target[target]
        if not files:
            continue

        print(f"  {title}")
        for f in files:
            if f.exists:
                print(f"    ✓ {f.local.name:32} → {f.remote}")
                print(f"      {_human_size(f.size):>10}")
            else:
                print(f"    ✗ {f.local.name:32} → НЕ СГЕНЕРИРОВАН")
        print()

    if plan.remote_dirs:
        print("  Папки на HA (будут созданы, если их нет):")
        for d in plan.remote_dirs:
            print(f"    {d}")
        print()

    ready = len(plan.ready)
    print(f"  Файлов к отправке: {ready}, суммарно {_human_size(plan.total_size)}")


def _print_lovelace_plan(plan: Plan, title: str) -> None:
    """Карточки не файлы для /config: они пишутся в конфиг дашборда."""
    if plan.lovelace_dir is None:
        return

    print(f"  {title}")
    views = plan.lovelace_files
    if not views:
        print("    ✗ views не сгенерированы")
        print()
        return

    floors = [v for v in views if v.name.startswith("zm-floor-")]
    spaces = [v for v in views if v.name.startswith("zm-space-")]
    print(f"    ✓ этажных views: {len(floors)}, subview пространств: {len(spaces)}")
    print(f"      канал: WebSocket → конфиг дашборда (не файлы в /config)")
    print(f"      свои views заменяются, ваши сохраняются; нужен АДМИН-токен")
    print()


def _print_areas_plan(plan: Plan, title: str) -> None:
    """Пространства не файлы: они создаются в реестрах по WebSocket."""
    if plan.areas_file is None:
        return

    print(f"  {title}")

    if not plan.areas_file.exists():
        print(f"    ✗ {plan.areas_file.name} → НЕ СГЕНЕРИРОВАН")
        print()
        return

    payload = load_areas_file(plan.areas_file)

    # Без подключения к HA мы не знаем, что там уже есть, — показываем всё
    # как «создать». При живом транспорте существующие будут пропущены.
    areas_plan = build_areas_plan(payload, existing_areas=[], existing_floors=[])

    print(f"    Этажей:      {len(areas_plan.floors_to_create)}")
    for floor in areas_plan.floors_to_create:
        print(f"      + {floor['name']}  ({floor['icon']})")

    print(f"    Пространств: {len(areas_plan.areas_to_create)}")
    for area in areas_plan.areas_to_create:
        aliases = ", ".join(area.get("aliases") or [])
        floor = f"этаж {area['floor']}" if "floor" in area else "без этажа"
        print(f"      + {area['name']:28} [{aliases}]  {floor}")

    print("\n    ⚠ Создаются по WebSocket, не файлами. Идемпотентно:")
    print("      существующие пропускаются по имени.")
    print()


def print_missing(plan: Plan) -> None:
    """Чего не хватает и что запустить, чтобы появилось."""
    steps = missing_pipeline_steps(plan)
    if not steps:
        return

    print("\n⚠ Часть артефактов не сгенерирована. Запустите:")
    for step in steps:
        print(f"    python scripts/{step}")
    print("  Или нажмите Build All в лаунчере.")


def print_restart_reminder() -> None:
    print("\n" + "═" * 70)
    print("⚠ ПЕРЕЗАПУСТИТЕ HOME ASSISTANT ВРУЧНУЮ")
    print("═" * 70)
    print("Без рестарта изменения не применятся: группы света объявлены через")
    print("YAML-платформу `light: - platform: group`, у которой нет reload.")
    print("\nHome Assistant → Настройки → Система → кнопка «Перезапустить».")


# ============================================================
# ЖИВОЙ ДЕПЛОЙ — пока не подключён
# ============================================================

def deploy_files(plan: Plan, ssh: SSHConfig) -> int:
    """
    Залить файлы по SFTP. Возвращает число неудач.

    При отказе на одном файле остальные доливаем: половина конфигурации на HA
    хуже, чем «почти вся, кроме одного, вот он» (решение владельца).

    Порядок из plan.ready: blueprint'ы -> скрипты -> автоматизации. Если
    оборвётся посередине, HA не увидит автоматизаций, ссылающихся на
    несуществующие скрипты.
    """
    if not plan.ready:
        print("  Файлов к отправке нет.\n")
        return 0

    errors = 0

    with HASSHClient(ssh) as client:
        print("  ✅ SSH подключён, SFTP работает\n")

        # На свежем объекте папок может не быть вовсе.
        for remote_dir in plan.remote_dirs:
            if client.ensure_dir(remote_dir):
                print(f"  + создана папка {remote_dir}")

        for f in plan.ready:
            try:
                written = client.put(f.local, f.remote)
                print(f"  ✓ {f.remote}  ({_human_size(written)})")
            except SSHTransportError as exc:
                print(f"  ❌ {f.remote}: {exc}")
                errors += 1

    print()
    return errors


def deploy_areas(areas_file: Path, ws: WSConfig) -> int:
    """Создать пространства и этажи по WebSocket. Возвращает число неудач."""
    payload = load_areas_file(areas_file)

    client = HAWebSocketClient(ws)

    existing = client.fetch_existing()
    print("  ✅ Home Assistant отвечает, токен принят")
    print(f"     уже есть: {len(existing['floors'])} этажей, "
          f"{len(existing['areas'])} пространств\n")

    areas_plan = build_areas_plan(
        payload,
        existing_areas=existing["areas"],
        existing_floors=existing["floors"],
    )

    if areas_plan.is_empty:
        print("  Всё уже создано — пропускаем (идемпотентность).\n")
        return 0

    for name in areas_plan.floors_existing + areas_plan.areas_existing:
        print(f"  = {name} — уже есть, пропущено")

    stats = client.apply(areas_plan)

    print(f"  + этажей создано:      {stats['floors_created']}")
    print(f"  + пространств создано: {stats['areas_created']}\n")

    return 0


def load_views(lovelace_dir: Path) -> List[dict]:
    """Прочитать views с диска (файл на view) и упорядочить детерминированно."""
    views = []
    for path in sorted(lovelace_dir.glob("zm-*.yaml")):
        view = yaml.safe_load(path.read_text(encoding="utf-8"))
        if view:
            views.append(view)
    return order_views(views)


def deploy_lovelace(lovelace_dir: Path, ws: WSConfig, dashboard: str) -> int:
    """
    Записать views в конфиг дашборда по WebSocket.

    Команда save перезаписывает дашборд ЦЕЛИКОМ, поэтому порядок такой:
    прочитать текущий конфиг → слить (свои views заменить, чужие сохранить)
    → записать. Любая другая последовательность снесла бы ручные views
    владельца (Главная, Энергомониторинг, Ошибки).
    """
    ours = load_views(lovelace_dir)
    client = HAWebSocketClient(ws)

    config = client.fetch_dashboard_config(dashboard)
    existing = list(config.get("views", []))
    print(f"  ✅ Дашборд «{dashboard}» прочитан: {len(existing)} views\n")

    summary = diff_summary(existing, ours)
    print(f"  = чужих views сохраняем: {summary['keep_foreign']}")
    print(f"  ~ наших обновится:       {summary['replace']}")
    print(f"  + наших добавится:       {summary['add']}")
    if summary["remove"]:
        print(f"  - наших удалится:        {summary['remove']} "
              f"(помещение исчезло из таблицы)")

    config["views"] = merge_views(existing, ours)
    client.save_dashboard_config(dashboard, config)

    print(f"\n  ✔ Записано: {len(ours)} наших views, "
          f"дашборд теперь {len(config['views'])} views")
    print("     Рестарт не нужен — конфиг дашборда применяется сразу.\n")
    return 0


def deploy_live(plan: Plan, ssh: SSHConfig, ws: Optional[WSConfig],
                dashboard: str = "") -> int:
    """
    Отправить конфигурацию на Home Assistant.

    Файлы — по SFTP, пространства — по WebSocket. Это два разных транспорта:
    WebSocket пишет реестры, но не кладёт файлы в /config.
    """
    print("🚀 Живой деплой\n")

    if plan.ready:
        problems = ssh.validate()
        if problems:
            print("❌ Проверьте параметры SSH:")
            for p in problems:
                print(f"   • {p}")
            return 2
        print(f"  SSH: {ssh.describe()}")

    if ws is not None:
        ws_problems = ws.validate()
        if ws_problems:
            print("❌ Проверьте параметры Home Assistant:")
            for p in ws_problems:
                print(f"   • {p}")
            return 2
        print(f"  HA : {ws.describe()}")

    print()

    errors = 0

    if plan.ready:
        try:
            errors += deploy_files(plan, ssh)
        except (SSHNotConfigured, SSHTransportError) as exc:
            print(f"❌ {exc}\n")
            print("   Файлы можно залить вручную — запустите deploy.py без --live.")
            return 3

    if ws is not None and plan.areas_file is not None and plan.areas_file.exists():
        print("🏢 Пространства и этажи\n")
        try:
            errors += deploy_areas(plan.areas_file, ws)
        except (WSNotConfigured, WSTransportError) as exc:
            print(f"❌ {exc}\n")
            errors += 1

    if ws is not None and plan.lovelace_files:
        print("🗂 Карточки (views дашборда)\n")
        try:
            errors += deploy_lovelace(plan.lovelace_dir, ws, dashboard)
        except (WSNotConfigured, WSTransportError) as exc:
            print(f"❌ {exc}\n")
            print("   Если отказ по правам: lovelace/config/save требует токен")
            print("   АДМИНИСТРАТОРА — токен обычного пользователя не подойдёт.\n")
            errors += 1

    if errors:
        print(f"⚠ Завершено с ошибками: {errors}")
        return 1

    return 0


# ============================================================
# CLI
# ============================================================

def main() -> int:
    _load_dotenv()

    parser = argparse.ArgumentParser(
        description="Доставить сгенерированную конфигурацию на Home Assistant.",
        epilog="Dry-run по умолчанию. Файлы едут по SFTP, пространства — по WebSocket.",
    )
    parser.add_argument("--data", default=str(DEFAULT_DATA_DIR),
                        help="Папка с артефактами генераторов")
    parser.add_argument("--targets", nargs="+", metavar="ЦЕЛЬ", default=list(TARGETS),
                        help=f"Что отправлять: {', '.join(TARGETS)} (по умолчанию всё)")
    parser.add_argument("--config-root", default=HA_CONFIG_ROOT,
                        help="Корень конфигурации на HA")
    parser.add_argument("--live", action="store_true",
                        help="Реально отправить на Home Assistant")

    ssh_group = parser.add_argument_group("SSH (файлы)")
    ssh_group.add_argument("--host", default=os.environ.get("HA_SSH_HOST", ""))
    ssh_group.add_argument("--port", type=int,
                           default=int(os.environ.get("HA_SSH_PORT", "22")))
    ssh_group.add_argument("--user", default=os.environ.get("HA_SSH_USER", "root"))
    ssh_group.add_argument("--key", default=os.environ.get("HA_SSH_KEY", ""))

    ha_group = parser.add_argument_group("Home Assistant (пространства, карточки)")
    ha_group.add_argument("--url", default=os.environ.get("HA_BASE_URL", ""))
    ha_group.add_argument("--token", default=os.environ.get("HA_TOKEN", ""),
                          help="Long-lived token. Для карточек нужен АДМИНСКИЙ")
    ha_group.add_argument("--insecure", action="store_true",
                          help="Не проверять TLS-сертификат (для самоподписанного https)")
    ha_group.add_argument("--dashboard",
                          default=os.environ.get("HA_DASHBOARD", "dashboard-tets"),
                          help="url_path дашборда, куда писать views карточек")

    args = parser.parse_args()

    data_dir = Path(args.data)

    print("\n=== Deploy ===")
    print("Артефакты:", data_dir)
    print("Цели     :", ", ".join(args.targets))
    print("Режим    :", "LIVE" if args.live else "dry-run (ничего не отправляем)")
    print()

    try:
        plan = build_plan(data_dir, list(args.targets), args.config_root)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 2

    print_plan(plan, list(args.targets), data_dir)
    print_missing(plan)

    if not args.live:
        print("\nЭто dry-run — ничего не отправлено.")
        print("Чтобы отправить файлы: тот же запуск с флагом --live.")
        return 0

    ssh = SSHConfig(
        host=args.host, port=args.port, user=args.user,
        key_path=args.key or None,
    )
    # WebSocket нужен и пространствам, и карточкам — канал один.
    ws = (
        WSConfig(base_url=args.url, token=args.token, insecure=args.insecure)
        if ("areas" in args.targets or "lovelace" in args.targets) else None
    )

    code = deploy_live(plan, ssh, ws, dashboard=args.dashboard)

    if code == 0:
        print_restart_reminder()

    return code


if __name__ == "__main__":
    sys.exit(main())
