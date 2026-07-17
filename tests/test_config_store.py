# -*- coding: utf-8 -*-
"""
Конфиг лаунчера: у него несколько независимых владельцев.

Поля главного окна и диалог Deploy живут в одном JSON, и каждый знает только
свою часть. Пока частичное сохранение шло через save(), которое перезаписывает
файл целиком, владельцы стирали друг друга — молча, и наладчик просто вводил
хост и токен заново каждый запуск.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from launcher.services.config_store import ConfigStore

LAUNCHER_UI = Path(__file__).resolve().parent.parent / "launcher" / "ui"


@pytest.fixture
def store(tmp_path) -> ConfigStore:
    return ConfigStore(tmp_path / "config.json")


def _deploy_settings() -> dict:
    return {
        "ssh_host": "10.0.0.5",
        "ssh_key": "C:/keys/object",
        "ha_url": "http://10.0.0.5:8123",
        "ha_token": "секрет",
        "ha_dashboard": "dashboard-tets",
        "ha_title": "Колледж Химки",
    }


def test_update_keeps_other_owners_settings(store):
    """Главное свойство: сохранил своё — чужое осталось.

    Тот самый баг: окно сохраняло три своих поля, и вместе с ними уезжали хост,
    токен и имя объекта. Проявлялось как «ввёл имя объекта, а в шапке старое»:
    имя стиралось при закрытии окна, и генерация его уже не видела.
    """
    store.save(_deploy_settings())

    store.update({"project_root": "C:/proj", "strict": True})

    data = store.load()
    assert data["ha_title"] == "Колледж Химки"
    assert data["ha_token"] == "секрет"
    assert data["project_root"] == "C:/proj"
    assert data["strict"] is True


def test_update_overwrites_only_its_own_keys(store):
    store.save(_deploy_settings())

    store.update({"ha_title": "Колледж Мытищи"})

    data = store.load()
    assert data["ha_title"] == "Колледж Мытищи"
    assert data["ssh_host"] == "10.0.0.5"


def test_update_on_empty_config_just_writes(store):
    store.update({"project_root": "C:/proj"})

    assert store.load() == {"project_root": "C:/proj"}


def test_update_survives_a_broken_file(store):
    """Битый JSON не должен ронять лаунчер: load() уже возвращает {}."""
    store.config_file_path.parent.mkdir(parents=True, exist_ok=True)
    store.config_file_path.write_text("{не json", encoding="utf-8")

    store.update({"project_root": "C:/proj"})

    assert store.load() == {"project_root": "C:/proj"}


def test_save_still_replaces_everything(store):
    """save() остаётся полной перезаписью — это его контракт.

    Именно поэтому у частичных владельцев есть update(). Ослабим save() до
    слияния — и удалить ключ станет нечем.
    """
    store.save({"a": 1, "b": 2})
    store.save({"a": 9})

    assert store.load() == {"a": 9}


# ============================================================
# Проводка окна: разбором кода, без PySide6
# ============================================================

def _method(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} не найден в {path.name}")


def _method_source(path: Path, name: str) -> str:
    return ast.unparse(_method(path, name))


def _config_keys(path: Path, name: str) -> set:
    """Ключи словарей-литералов внутри метода.

    Именно ключи, а не текст: ast.unparse нормализует кавычки, и поиск
    подстроки «"ha_title"» ловил бы форматирование, а не смысл.
    """
    return {
        key.value
        for node in ast.walk(_method(path, name))
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def test_window_saves_its_fields_with_update_not_save():
    """Окно обязано звать update(): save() снёс бы настройки диалога Deploy."""
    source = _method_source(LAUNCHER_UI / "main_window.py", "_save_current_config")

    assert "config_store.update(" in source
    assert "config_store.save(" not in source, (
        "главное окно знает только свои поля; save() перезапишет файл целиком "
        "и сотрёт хост, токен и ключ из диалога Deploy"
    )


def test_window_owns_the_fields_that_generation_reads():
    """«Объект» и «Дашборд» сохраняет то окно, где их вводят."""
    keys = _config_keys(LAUNCHER_UI / "main_window.py", "_save_current_config")

    assert {"ha_title", "ha_dashboard"} <= keys


def test_deploy_dialog_does_not_own_object_fields():
    """Диалог Deploy не возвращает «Объект» и «Дашборд» — иначе затрёт их.

    Они принадлежат главному окну: читает их генерация карточек, а не деплой.
    Вернёт их диалог — и `saved.update(dialog.result_config())` положит поверх
    то, что наладчик только что ввёл в главном окне.
    """
    keys = _config_keys(LAUNCHER_UI / "deploy_dialog.py", "result_config")

    assert "ha_title" not in keys
    assert "ha_dashboard" not in keys
    # а сеть и токен — его и остаются
    assert {"ha_token", "ssh_host"} <= keys
