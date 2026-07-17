# -*- coding: utf-8 -*-
"""
Векторная графика лаунчера: декаль шапки и иконка окна.

Та же беда, что и с QSS: битый SVG не роняет приложение. Он просто не
рисуется, и окно выглядит так, будто графики и не задумывали.

⚠ Тесты требуют PySide6 и пропускаются, если он не импортируется (на Linux-VM
нет libEGL). На машине наладчика, где лаунчер и живёт, отрабатывают.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parent.parent / "launcher" / "ui"
DECALS_PY = UI_DIR / "decals.py"
WIDGETS_PY = UI_DIR / "widgets.py"


def _qt():
    """PySide6 + QApplication, либо пропуск теста."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as e:
        pytest.skip(f"GUI-зависимость недоступна: {e}")
    return QApplication.instance() or QApplication([])


# ============================================================
# Никаких файлов-ресурсов
# ============================================================

def test_vector_lives_in_code_not_in_files():
    """SVG питоновской строкой, а не файлом: иначе EXE соберётся без графики.

    Тот же капкан, что у QSS и шрифтов: файл-ресурс требует --add-data, и
    забытый флаг даёт окно без иконки при том, что у разработчика всё на месте.
    """
    assert not list(UI_DIR.glob("*.svg"))
    assert not list(UI_DIR.glob("*.png"))

    src = DECALS_PY.read_text(encoding="utf-8")
    assert "QByteArray" in src, "SVG обязан читаться из памяти, а не с диска"
    assert "url(" not in src and "QFile" not in src


def test_decals_take_their_colours_from_the_theme():
    """Графика красится палитрой темы, а не своими хексами.

    Иначе смена акцента оставит декаль висеть прежним цветом — и это тот
    случай, когда рассинхрон видно, но не понятно, где чинить.
    """
    src = DECALS_PY.read_text(encoding="utf-8")

    assert "from launcher.ui.theme import" in src

    svg_only = "\n".join(re.findall(r'_SVG = f"""(.*?)"""', src, re.DOTALL))
    hardcoded = set(re.findall(r'"(#[0-9a-fA-F]{6})"', svg_only))

    # #ffffff — заливка подложки иконки, к акцентам отношения не имеет.
    assert hardcoded <= {"#ffffff"}, (
        f"цвета зашиты в SVG: {sorted(hardcoded)}. Берите из theme."
    )
    assert "{CYAN}" in svg_only and "{ACCENT}" in svg_only


# ============================================================
# Капкан Qt: свой QWidget не рисует свой же стиль
# ============================================================

def test_custom_widget_with_a_stylesheet_paints_itself():
    """Подкласс QWidget обязан реализовать paintEvent через QStyle.

    ⚠ Требование Qt, а не наша причуда. Готовые виджеты делают это внутри, а
    голый QWidget — нет: правило QSS применяется, выглядит рабочим и молча
    ничего не красит. Шапка вышла без фона и рамки ровно поэтому.
    """
    src = WIDGETS_PY.read_text(encoding="utf-8")
    header = src[src.index("class HeaderBar"):]

    assert "setStyleSheet" in header
    assert "def paintEvent" in header, (
        "HeaderBar задаёт себе стиль, но не рисует его: подкласс QWidget без "
        "paintEvent с QStyle.PE_Widget останется без фона и рамки"
    )
    assert "PE_Widget" in header


# ============================================================
# Живая отрисовка
# ============================================================

@pytest.mark.parametrize("name", ["FLOOR_PLAN_SVG", "ICON_SVG"])
def test_svg_parses(name):
    _qt()
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer

    from launcher.ui import decals

    renderer = QSvgRenderer(QByteArray(getattr(decals, name).strip().encode()))
    assert renderer.isValid(), f"{name} не разобрался"


@pytest.mark.parametrize("name,w,h", [("FLOOR_PLAN_SVG", 260, 44), ("ICON_SVG", 64, 64)])
def test_svg_actually_draws_something(name, w, h):
    """Не «разобрался», а НАРИСОВАЛ.

    isValid() проходит и у разметки, которая ничего не рисует: перепутанный
    viewBox, координаты за кадром, fill="none" на всём. Тогда тест выше зелёный,
    а в окне пусто. Считаем непрозрачные пиксели.
    """
    _qt()
    from launcher.ui import decals

    image = decals.render_svg(getattr(decals, name), w, h).toImage()
    painted = sum(1 for y in range(image.height()) for x in range(image.width())
                  if image.pixelColor(x, y).alpha() > 0)

    assert painted > 0, f"{name} не нарисовал ни пикселя"
    assert painted > image.width() * image.height() * 0.01, (
        f"{name} нарисовал {painted}px — подозрительно мало, проверьте viewBox"
    )


def test_broken_svg_fails_loudly():
    """Битую разметку рендерер обязан отвергнуть, а не отдать пустую картинку."""
    _qt()
    from launcher.ui import decals

    with pytest.raises(ValueError):
        decals.render_svg("<svg>это не разметка", 10, 10)


def test_window_icon_has_the_sizes_windows_asks_for():
    """Несколько растров, а не один.

    Qt берёт ближайший и масштабирует: с одним 64px иконка в заголовке окна
    (16px) мылила бы.
    """
    _qt()
    from launcher.ui.decals import window_icon

    sizes = {s.width() for s in window_icon().availableSizes()}
    assert {16, 32, 64} <= sizes


def test_version_is_shown_and_honest():
    """Версия на экране — чтобы наладчик читал её с экрана, а не из свойств файла.

    Суффикс -dev держится до тега v3.0.0: писать релизную версию на ветке
    значило бы врать тому, кто звонит с объекта.
    """
    from launcher import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+(-dev)?", __version__)

    main_window = (UI_DIR / "main_window.py").read_text(encoding="utf-8")
    assert "HeaderBar(" in main_window and "__version__" in main_window
