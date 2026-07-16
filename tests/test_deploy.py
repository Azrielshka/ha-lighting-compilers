# -*- coding: utf-8 -*-
"""
Деплой: раскладка артефактов по путям Home Assistant и dry-run.

Транспорт (SSH и WebSocket) — заготовки, их без живого HA не проверить.
Зато раскладка и дифф пространств — чистая логика, и она покрыта здесь
целиком. Разделение прошло ровно по этой границе.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import deploy as DEPLOY
from scripts._lib.ha_ssh import HASSHClient, SSHConfig, SSHTransportError
from scripts._lib.ha_targets import (
    TARGET_TITLES,
    TARGETS,
    build_plan,
    missing_pipeline_steps,
)
from scripts._lib.ha_ws import (
    HAWebSocketClient,
    WSConfig,
    WSTransportError,
    build_areas_plan,
    load_areas_file,
)


@pytest.fixture
def data_dir(tmp_path) -> Path:
    """Полный набор артефактов, как после Build All."""
    root = tmp_path / "data"

    (root / "light_groups").mkdir(parents=True)
    for name in ("lights_group.yaml", "lights_general_groups.yaml",
                 "lights_floor_groups.yaml"):
        (root / "light_groups" / name).write_text("x: 1\n", encoding="utf-8")

    (root / "scripts").mkdir()
    (root / "scripts" / "scripts.yaml").write_text("a_on:\n  alias: x\n", encoding="utf-8")

    (root / "automations").mkdir()
    (root / "automations" / "automations.yaml").write_text("- id: a\n", encoding="utf-8")

    (root / "blueprints").mkdir()
    for name in ("zm_default_on.yaml", "zm_default_off.yaml"):
        (root / "blueprints" / name).write_text("blueprint: {}\n", encoding="utf-8")

    (root / "areas").mkdir()
    (root / "areas" / "areas.yaml").write_text(
        "floors:\n"
        "  - level: 1\n"
        '    name: "1 этаж"\n'
        "    icon: mdi:home-floor-1\n"
        "\n"
        "areas:\n"
        '  - name: "101_Тамбур"\n'
        '    aliases: ["101_tambur"]\n'
        "    floor: 1\n"
        '  - name: "103_Вестибюль"\n'
        '    aliases: ["103_vestibiul"]\n'
        "    floor: 1\n",
        encoding="utf-8",
    )

    # Views дашборда: файл на view, как их кладёт generate_lovelace_cards.py.
    (root / "lovelace").mkdir()
    (root / "lovelace" / "zm-floor-1.yaml").write_text(
        "title: Этаж 1\npath: zm-floor-1\ntype: sections\n", encoding="utf-8")
    (root / "lovelace" / "zm-space-103_vestibiul.yaml").write_text(
        "title: 103 Вестибюль\npath: zm-space-103_vestibiul\nsubview: true\n",
        encoding="utf-8")

    return root


# ============================================================
# РАСКЛАДКА
# ============================================================

def test_light_groups_go_to_packages(data_dir):
    plan = build_plan(data_dir, ["lights"])
    remotes = {f.remote for f in plan.files}

    assert remotes == {
        "/config/includes/packages/zm_lights_group.yaml",
        "/config/includes/packages/zm_lights_general_groups.yaml",
        "/config/includes/packages/zm_lights_floor_groups.yaml",
    }


def test_scripts_go_to_includes_scripts(data_dir):
    """includes/scripts/ подключена через !include_dir_merge_named."""
    plan = build_plan(data_dir, ["scripts"])

    assert [f.remote for f in plan.files] == [
        "/config/includes/scripts/zm_scripts.yaml",
    ]


def test_automations_go_to_includes_automations(data_dir):
    """includes/automations/ подключена через !include_dir_merge_list."""
    plan = build_plan(data_dir, ["automations"])

    assert [f.remote for f in plan.files] == [
        "/config/includes/automations/zm_automations.yaml",
    ]


def test_blueprints_keep_their_names(data_dir):
    """
    Переименовывать blueprint'ы нельзя: на их имена ссылаются автоматизации
    через use_blueprint.path.
    """
    plan = build_plan(data_dir, ["blueprints"])
    names = {f.remote.rsplit("/", 1)[1] for f in plan.files}

    assert names == {"zm_default_on.yaml", "zm_default_off.yaml"}
    assert all("blueprints/automation/zone_manager" in f.remote for f in plan.files)


def test_all_remote_files_are_prefixed_or_blueprints(data_dir):
    """
    Префикс zm_ — гарантия, что деплой перезапишет только своё и не тронет
    файлы наладчика.
    """
    plan = build_plan(data_dir, list(TARGETS))

    for f in plan.files:
        name = f.remote.rsplit("/", 1)[1]
        assert name.startswith("zm_"), name


def test_areas_are_not_a_file_target(data_dir):
    """Пространства создаются в реестрах по WebSocket, файлом их не залить."""
    plan = build_plan(data_dir, ["areas"])

    assert plan.files == []
    assert plan.areas_file == data_dir / "areas" / "areas.yaml"


def test_custom_config_root(data_dir):
    plan = build_plan(data_dir, ["scripts"], config_root="/homeassistant")

    assert plan.files[0].remote == "/homeassistant/includes/scripts/zm_scripts.yaml"


def test_unknown_target(data_dir):
    with pytest.raises(ValueError, match="неизвестные цели"):
        build_plan(data_dir, ["ерунда"])


def test_target_titles_cover_all_targets():
    assert set(TARGET_TITLES) == set(TARGETS)


# ============================================================
# ОТСУТСТВУЮЩИЕ АРТЕФАКТЫ
# ============================================================

def test_missing_artifacts_are_visible(tmp_path):
    """
    Наладчик должен увидеть, что шаг пайплайна не запускался, а не гадать,
    почему на HA чего-то не хватает.
    """
    plan = build_plan(tmp_path / "пусто", list(TARGETS))

    assert plan.ready == []
    assert len(plan.missing) > 0


def test_missing_steps_are_deduplicated(tmp_path):
    """blueprints кладёт тот же generate_automations.py — не советуем дважды."""
    plan = build_plan(tmp_path / "пусто", ["automations", "blueprints"])
    steps = missing_pipeline_steps(plan)

    assert steps == ["generate_automations.py"]


def test_missing_steps_for_areas(tmp_path):
    plan = build_plan(tmp_path / "пусто", ["areas"])

    assert missing_pipeline_steps(plan) == ["generate_areas.py"]


def test_nothing_missing_when_all_generated(data_dir):
    plan = build_plan(data_dir, list(TARGETS))

    assert missing_pipeline_steps(plan) == []
    assert plan.missing == []


def test_remote_dirs_collected(data_dir):
    plan = build_plan(data_dir, list(TARGETS))

    assert set(plan.remote_dirs) == {
        "/config/includes/packages",
        "/config/includes/scripts",
        "/config/includes/automations",
        "/config/blueprints/automation/zone_manager",
    }


# ============================================================
# ПРОСТРАНСТВА: ДИФФ И ИДЕМПОТЕНТНОСТЬ
# ============================================================

def test_areas_plan_creates_everything_on_empty_ha(data_dir):
    payload = load_areas_file(data_dir / "areas" / "areas.yaml")
    plan = build_areas_plan(payload, existing_areas=[], existing_floors=[])

    assert len(plan.floors_to_create) == 1
    assert len(plan.areas_to_create) == 2
    assert not plan.is_empty


def test_areas_plan_is_idempotent(data_dir):
    """Повторный деплой ничего не дублирует: ключ сравнения — имя."""
    payload = load_areas_file(data_dir / "areas" / "areas.yaml")

    plan = build_areas_plan(
        payload,
        existing_areas=["101_Тамбур", "103_Вестибюль"],
        existing_floors=["1 этаж"],
    )

    assert plan.areas_to_create == []
    assert plan.floors_to_create == []
    assert plan.is_empty
    assert set(plan.areas_existing) == {"101_Тамбур", "103_Вестибюль"}


def test_areas_plan_partial(data_dir):
    payload = load_areas_file(data_dir / "areas" / "areas.yaml")
    plan = build_areas_plan(payload, existing_areas=["101_Тамбур"], existing_floors=[])

    assert [a["name"] for a in plan.areas_to_create] == ["103_Вестибюль"]
    assert plan.areas_existing == ["101_Тамбур"]


def test_areas_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="generate_areas.py"):
        load_areas_file(tmp_path / "нет.yaml")


def test_empty_areas_file(tmp_path):
    path = tmp_path / "areas.yaml"
    path.write_text("# нет данных\n", encoding="utf-8")

    payload = load_areas_file(path)
    assert payload == {"floors": [], "areas": []}


# ============================================================
# ПАРАМЕТРЫ ПОДКЛЮЧЕНИЯ
# ============================================================

def test_ssh_config_validation():
    assert SSHConfig(host="", key_path=None).validate()

    problems = SSHConfig(host="ha.local", port=99999, key_path="/нет").validate()
    assert any("порт" in p for p in problems)
    assert any("не найден" in p for p in problems)


def test_ssh_config_needs_key_or_password():
    problems = SSHConfig(host="ha.local").validate()
    assert any("ключ" in p or "пароль" in p for p in problems)


def test_ssh_config_ok(tmp_path):
    key = tmp_path / "id_ed25519"
    key.write_text("x", encoding="utf-8")

    assert SSHConfig(host="ha.local", port=2223, key_path=str(key)).validate() == []


def test_ws_url_derivation():
    assert WSConfig("http://ha:8123", "t").ws_url == "ws://ha:8123/api/websocket"
    assert WSConfig("https://ha.example", "t").ws_url == "wss://ha.example/api/websocket"


def test_ws_config_validation():
    assert WSConfig("", "").validate()
    assert WSConfig("http://ha:8123", "").validate()
    assert WSConfig("http://ha:8123", "token").validate() == []


def test_ws_token_is_not_printed_in_full():
    """Токен в логах светить незачем."""
    described = WSConfig("http://ha:8123", "supersecrettoken12345").describe()

    assert "supersecrettoken12345" not in described


# ============================================================
# ТРАНСПОРТ — ЗАГОТОВКА, ОТКАЗЫВАЕТСЯ ЧЕСТНО
# ============================================================

def test_ssh_transport_is_real(tmp_path):
    """
    SFTP-транспорт реализован и проверен на живом HA. Недоступный хост даёт
    внятную ошибку, а не молчаливый успех.
    """
    key = tmp_path / "k"
    key.write_text("x", encoding="utf-8")

    client = HASSHClient(SSHConfig(host="127.0.0.1", port=1, key_path=str(key)))

    with pytest.raises(SSHTransportError, match="не могу подключиться"):
        client.connect()


def test_ws_transport_is_real():
    """
    WebSocket-транспорт реализован (сеть проверяется на живом HA). До
    недоступного хоста он честно не достучится.
    """
    client = HAWebSocketClient(WSConfig("http://127.0.0.1:1", "t"))

    with pytest.raises(WSTransportError, match="не могу подключиться"):
        client.fetch_existing()


# ============================================================
# CLI
# ============================================================

def _main(monkeypatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["deploy.py", *args])
    return DEPLOY.main()


def test_dry_run_is_default(monkeypatch, data_dir, capsys):
    code = _main(monkeypatch, "--data", str(data_dir))

    assert code == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "ничего не отправлено" in out


def test_dry_run_shows_every_file(monkeypatch, data_dir, capsys):
    _main(monkeypatch, "--data", str(data_dir))
    out = capsys.readouterr().out

    assert "/config/includes/packages/zm_lights_group.yaml" in out
    assert "/config/includes/scripts/zm_scripts.yaml" in out
    assert "/config/includes/automations/zm_automations.yaml" in out
    assert "blueprints/automation/zone_manager" in out


def test_dry_run_shows_areas(monkeypatch, data_dir, capsys):
    _main(monkeypatch, "--data", str(data_dir), "--targets", "areas")
    out = capsys.readouterr().out

    assert "101_Тамбур" in out
    assert "1 этаж" in out


def test_target_selection(monkeypatch, data_dir, capsys):
    _main(monkeypatch, "--data", str(data_dir), "--targets", "scripts")
    out = capsys.readouterr().out

    assert "zm_scripts.yaml" in out
    assert "zm_lights_group.yaml" not in out


def test_unknown_target_cli(monkeypatch, data_dir):
    assert _main(monkeypatch, "--data", str(data_dir), "--targets", "ерунда") == 2


def test_live_without_params_fails(monkeypatch, data_dir, capsys):
    code = _main(monkeypatch, "--data", str(data_dir), "--live")

    assert code == 2
    assert "Проверьте параметры SSH" in capsys.readouterr().out


def test_live_reports_unreachable_host(monkeypatch, data_dir, tmp_path, capsys):
    """
    Транспорт настоящий: до недоступного хоста он честно не достучится и
    посоветует залить вручную.
    """
    key = tmp_path / "k"
    key.write_text("x", encoding="utf-8")

    code = _main(
        monkeypatch,
        "--data", str(data_dir), "--live",
        "--host", "127.0.0.1", "--port", "1", "--key", str(key),
        "--url", "http://ha:8123", "--token", "t",
    )

    assert code == 3
    out = capsys.readouterr().out
    assert "не могу подключиться" in out
    assert "вручную" in out


def test_missing_artifacts_suggest_pipeline_steps(monkeypatch, tmp_path, capsys):
    code = _main(monkeypatch, "--data", str(tmp_path / "пусто"))

    assert code == 0
    out = capsys.readouterr().out
    assert "не сгенерирована" in out
    assert "generate_scripts.py" in out
