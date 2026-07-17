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

@pytest.mark.parametrize("name", ["HEADER_SVG", "ICON_SVG"])
def test_svg_parses(name):
    _qt()
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer

    from launcher.ui import decals

    renderer = QSvgRenderer(QByteArray(getattr(decals, name).strip().encode()))
    assert renderer.isValid(), f"{name} не разобрался"


@pytest.mark.parametrize("name", ["HEADER_SVG", "ICON_SVG"])
def test_svg_actually_draws_something(name):
    """Не «разобрался», а НАРИСОВАЛ.

    isValid() проходит и у разметки, которая ничего не рисует: перепутанный
    viewBox, координаты за кадром, fill="none" на всём. Тогда тест выше зелёный,
    а в окне пусто. Считаем непрозрачные пиксели.
    """
    _qt()
    from launcher.ui import decals

    # Размеры берём из модуля здесь, а не в параметрах: параметры собираются на
    # импорте, а импорт decals тянет PySide6 — без него сбор тестов упал бы.
    w, h = (decals.DECAL_W, decals.DECAL_H) if name == "HEADER_SVG" else (64, 64)

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


# ============================================================
# Окно обязано влезать в ноутбучный экран
# ============================================================

def test_window_fits_a_small_laptop_screen():
    """Минимум окна не должен превышать высоту ноутбучного экрана.

    Тот самый баг: панель Operations с четырнадцатью кнопками требовала себе
    689px, окно — 1016px. На большом мониторе всё прекрасно; на ноутбуке
    оконный менеджер ужимает окно ниже его же минимума, layout сплющивает
    кнопки, и от подписи остаётся полоска по центру.

    1366x768 — типовой экран наладчика. За вычетом заголовка окна и панели
    задач остаётся около 700px, берём их с небольшим запасом.
    """
    app = _qt()
    from launcher.ui.main_window import LauncherWindow
    from launcher.ui.theme import apply_theme

    apply_theme(app)
    window = LauncherWindow()

    assert window.minimumSizeHint().height() <= 720, (
        f"окно требует {window.minimumSizeHint().height()}px по высоте — "
        f"на экране 768px оно не поместится, и кнопки сплющит"
    )


def test_buttons_never_squash_below_their_text():
    """Кнопки не сжимаются ниже своей высоты ни на каком размере окна.

    Прокрутка обязана показывать, что не влезло, а не layout — сплющивать.
    """
    app = _qt()
    from PySide6.QtWidgets import QCheckBox, QPushButton

    from launcher.ui.main_window import LauncherWindow
    from launcher.ui.theme import apply_theme

    apply_theme(app)
    window = LauncherWindow()
    window.show()

    for height in (1016, 768, 620):
        window.resize(1100, height)
        app.processEvents()

        squashed = [b.text() for b in window.findChildren(QPushButton)
                    if b.height() < b.sizeHint().height()]
        assert not squashed, f"при высоте {height}px сплющены: {squashed}"

        # Полоса прокрутки съедает ширину у виджета внутри — на этом
        # обрезалась подпись флажка «Strict».
        clipped = [c.text() for c in window.findChildren(QCheckBox)
                   if c.width() < c.sizeHint().width()]
        assert not clipped, f"при высоте {height}px обрезаны: {clipped}"

    window.close()


# ============================================================
# Лицензия чужой графики
# ============================================================

def _notice_from_source() -> str:
    """Текст ISC из исходника — БЕЗ импорта модуля.

    ⚠ Импорт decals тянет PySide6, а на dev-VM он не грузится (нет libEGL) —
    тест падал бы вместо проверки. Но проверка-то текстовая: Qt ей не нужен, и
    пропускать её на машине без GUI неправильно. Соблюдение лицензии не должно
    зависеть от того, установлен ли где-то libEGL.
    """
    src = DECALS_PY.read_text(encoding="utf-8")

    if "LUCIDE_ICONS" not in src:
        pytest.skip("иконки Lucide больше не используются")

    match = re.search(r'LUCIDE_NOTICE = """(.*?)"""', src, re.DOTALL)
    assert match, "иконки Lucide есть, а LUCIDE_NOTICE не объявлен"
    return match.group(1)


def test_lucide_icons_carry_their_licence():
    """Есть иконки Lucide — обязан быть и текст ISC. Внутри EXE, не рядом с ним.

    ISC разрешает коммерческое использование даром и без спроса, но требует
    копирайт и текст лицензии «во всех копиях». Лаунчер уезжает на объект одним
    EXE, поэтому текст лежит строкой в модуле: файл рядом потребовал бы
    --add-data, и забытый флаг превратил бы нарушение лицензии в тихую ошибку
    сборки.

    Тест связывает обязательство с кодом: уберёте иконки — уберите и notice;
    оставите иконки без notice — упадёте здесь, а не в разговоре с юристом
    заказчика.
    """
    notice = _notice_from_source()

    assert "ISC License" in notice
    assert "Lucide Icons and Contributors" in notice
    assert "appear in all copies" in notice


def test_licence_file_matches_the_notice_in_code():
    """Файл для людей и строка для EXE не должны разъехаться."""
    notice = _notice_from_source()

    licences = Path(__file__).resolve().parent.parent / "THIRD-PARTY-LICENSES.md"
    assert licences.exists(), "чужая графика есть, а файла лицензий нет"

    text = licences.read_text(encoding="utf-8")
    assert "Lucide" in text
    # Ключевые строки ISC обязаны быть в обоих местах дословно.
    for line in ("ISC License", "Copyright (c) 2026 Lucide Icons and Contributors"):
        assert line in notice and line in text, line


def test_no_icons_from_sources_we_rejected():
    """Ни Pinterest, ни стоков с атрибуцией — ни в коде, ни в вариантах.

    Условия у них требуют атрибуцию либо подписку, а «для личного
    использования» не покрывает нашу работу: инструментом настраивают
    освещение за деньги.
    """
    banned = ("pinterest", "vecteezy", "freepik", "vectorstock")

    for path in (DECALS_PY, WIDGETS_PY):
        text = path.read_text(encoding="utf-8").lower()
        for name in banned:
            # Упоминание в объяснении «почему не берём» — нормально;
            # ссылка на скачивание — нет.
            assert f"{name}.com" not in text, f"{path.name}: ссылка на {name}"


@pytest.mark.parametrize("ratio", [1.0, 1.25, 1.5, 2.0])
def test_svg_is_not_scaled_twice(ratio):
    """Рисунок при любом масштабе экрана занимает ту же долю холста.

    Тот самый баг, который поймал владелец, а не я: setDevicePixelRatio уже
    переводит координаты painter'а в логические, а я вдобавок рисовал в
    прямоугольник width * ratio — масштаб применялся ДВАЖДЫ. Рисунок раздувался
    и обрезался по краю: при 150% из пяти иконок было видно три с хвостиком и
    только верхние две трети их высоты.

    У меня на 100% всё выглядело правильно — ratio 1.0 умножение прячет.
    Поэтому проверяем именно НЕединичные масштабы: 125% и 150% на ноутбуках
    Windows встречаются чаще, чем 100%.
    """
    _qt()
    from launcher.ui import decals

    def coverage(r: float) -> tuple:
        image = decals.render_svg(decals.HEADER_SVG,
                                  decals.DECAL_W, decals.DECAL_H, r).toImage()
        cols = [x for x in range(image.width())
                if any(image.pixelColor(x, y).alpha() > 0
                       for y in range(image.height()))]
        rows = [y for y in range(image.height())
                if any(image.pixelColor(x, y).alpha() > 0
                       for x in range(image.width()))]
        assert cols and rows, "рисунок пуст"
        return max(cols) / image.width(), max(rows) / image.height()

    base_w, base_h = coverage(1.0)
    got_w, got_h = coverage(ratio)

    assert abs(got_w - base_w) < 0.03, (
        f"при масштабе {ratio} рисунок занимает {got_w:.0%} ширины вместо "
        f"{base_w:.0%} — масштаб применён дважды, картинка обрежется"
    )
    assert abs(got_h - base_h) < 0.03, (
        f"при масштабе {ratio} рисунок занимает {got_h:.0%} высоты вместо "
        f"{base_h:.0%} — масштаб применён дважды, картинка обрежется"
    )
