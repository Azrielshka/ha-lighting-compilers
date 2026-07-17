# -*- coding: utf-8 -*-
"""
Оформление лаунчера.

Стили проверить глазами можно, а вот удержать — нет: QSS молчит. Правило с
опечаткой, свойство, которого Qt не знает, свойство, которое Qt знает, но до
субконтрола не доносит — всё это не падает и не логируется в приложении, просто
не работает. За один вечер работы над темой я наступил на это дважды.

Здесь ловим то, что можно поймать машинно.

⚠ Часть тестов требует PySide6 и падать без него не должна: на Linux-VM
разработчика библиотека может не импортироваться (нужен libEGL). Такие тесты
пропускаются через importorskip; на машине наладчика, где лаунчер и живёт, они
отработают.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

THEME_PY = Path(__file__).resolve().parent.parent / "launcher" / "ui" / "theme.py"


def _source() -> str:
    """Исходник темы текстом: без импорта, значит и без PySide6."""
    return THEME_PY.read_text(encoding="utf-8")


def _qss_block() -> str:
    """Только сам QSS, без питоновской обвязки и docstring'а."""
    src = _source()
    marker = 'QSS = f"""'
    start = src.index(marker) + len(marker)   # +len: иначе в блок попадёт само
    end = src.index('"""', start)             # объявление и «QSS» сойдёт за виджет
    return src[start:end]


def _strip_comments(qss: str) -> str:
    return re.sub(r"/\*.*?\*/", "", qss, flags=re.DOTALL)


def _rule_body(selector: str) -> str:
    """Тело правила: от селектора до закрывающей `}}`.

    ⚠ Именно до `}}`, а не до первой `}`. В исходнике f-строки скобки правила
    удвоены, а одиночные — это подстановки вроде `{BG}`. Обрежешь по первой `}`
    — попадёшь внутрь подстановки, и проверка молча осмотрит два свойства
    вместо десяти. Эта ошибка тут уже была.
    """
    qss = _strip_comments(_qss_block())
    start = qss.index(selector)
    end = qss.index("}}", start)
    return qss[start:end]


# ============================================================
# Правила, которые молча не работают
# ============================================================

def test_no_text_transform_in_groupbox_title():
    """text-transform до ::title не доходит — заголовки заглавные в строках.

    Qt применяет его к QLabel, но не к субконтролу. Написанное здесь правило
    выглядело бы рабочим и не делало бы ничего: именно так заголовки групп и
    остались строчными в первой версии темы.
    """
    title_rule = _rule_body("QGroupBox::title")

    assert "text-transform" not in title_rule, (
        "text-transform не применяется к QGroupBox::title — заголовок останется "
        "строчным. Делайте .upper() на самой строке при создании QGroupBox."
    )


def test_spinbox_arrows_are_not_styled():
    """::up-arrow / ::down-arrow не трогаем: рисовать их нечем.

    Qt перестаёт рисовать нативную стрелку, как только стилизуешь ::up-button,
    а своя требует image — то есть ресурса и --add-data в сборке EXE. CSS-трюк
    «треугольник из рамок» в Qt не работает и даёт два квадратика.
    Поэтому у единственного QSpinBox стрелки выключены в коде.
    """
    qss = _strip_comments(_qss_block())

    assert "::up-arrow" not in qss and "::down-arrow" not in qss
    assert "::up-button" not in qss and "::down-button" not in qss


def test_the_only_spinbox_has_its_buttons_off():
    """Раз стрелки не стилизуются — они обязаны быть выключены."""
    dialog = (THEME_PY.parent / "deploy_dialog.py").read_text(encoding="utf-8")

    assert "setButtonSymbols(QSpinBox.NoButtons)" in dialog


# ============================================================
# Семантика важнее акцента
# ============================================================

def test_accent_never_collides_with_state_colours():
    """Ошибка/успех/предупреждение обязаны отличаться от акцента.

    Инженер читает состояние периферийным зрением. Совпади акцент с красным —
    и «всё хорошо» станет неотличимо от «упало». Пурпур ACCENT и красный ERROR
    оба красноватые, поэтому ещё и разведены по местам применения: акцент живёт
    в хроме, красный — в тексте лога и статусах.
    """
    src = _source()
    colours = dict(re.findall(r"^([A-Z_]+) = \"(#[0-9a-f]{6})\"", src, re.MULTILINE))

    assert colours["ACCENT"] != colours["ERROR"]
    assert colours["ACCENT"] != colours["SUCCESS"]
    assert colours["ACCENT"] != colours["WARNING"]


def test_disabled_state_is_described():
    """:disabled — не косметика.

    Лаунчер гасит кнопки на время работы пайплайна (_set_running_state). QSS
    отключает нативную отрисовку виджета целиком, поэтому без явного правила
    выключенная кнопка выглядела бы нажимаемой.
    """
    qss = _strip_comments(_qss_block())

    assert "QPushButton:disabled" in qss
    assert "QPushButton:hover" in qss
    assert "QPushButton:pressed" in qss


def test_fonts_are_system_only():
    """Никаких шрифтов, которых может не быть на машине наладчика.

    Свой шрифт = лицензия + --add-data + EXE без шрифта при забытом флаге.
    Consolas есть на любой Windows, Courier New — запасной.
    """
    src = _source()
    mono = re.search(r"^MONO = (.+)$", src, re.MULTILINE).group(1)

    assert "Consolas" in mono
    assert "Courier New" in mono

    # Смотрим только на объявления шрифтов, а не на весь файл: в docstring
    # Orbitron упомянут как пример того, чего мы НЕ тащим, и поиск по всему
    # исходнику ловил бы объяснение вместо нарушения.
    declared = " ".join(re.findall(r"font-family:\s*([^;]+);", _qss_block()))
    declared += " " + mono

    for fancy in ("Orbitron", "Rajdhani", "Share Tech", "Blender"):
        assert fancy not in declared


def test_theme_is_a_module_not_a_data_file():
    """QSS живёт в .py, а не в .qss: иначе EXE соберётся без стилей.

    Файл-ресурс потребовал бы --add-data. Забытый флаг = EXE без оформления
    при том, что у разработчика всё работает.
    """
    assert not list(THEME_PY.parent.glob("*.qss"))
    assert 'QSS = f"""' in _source()


# ============================================================
# Живая проверка Qt: требует PySide6
# ============================================================

def _styled_widget_names() -> list:
    """Типы виджетов, которые упоминает наш QSS.

    Выводим из самого QSS, а не перечисляем руками: Qt разбирает стили ЛЕНИВО и
    отдельно для каждого типа виджета. Не создашь QTextEdit — правило QTextEdit
    не разберётся, и опечатка в нём пройдёт мимо теста. На этом тест уже был
    пустышкой один раз.
    """
    qss = _strip_comments(_qss_block())

    # Селектор — всё до открывающей скобки правила (в исходнике f-строки она
    # удвоена). Из каждого достаём ВСЕ имена: `QLineEdit, QSpinBox {` — это два
    # типа, и поиск только по началу строки терял второй.
    names = set()
    for selector in re.findall(r"^([^\n{]+?)\s*\{\{", qss, re.MULTILINE):
        names.update(re.findall(r"\bQ[A-Za-z]+", selector))

    # QToolTip — не виджет, а статический класс-помощник: создавать нечего.
    return sorted(names - {"QToolTip"})


def test_qt_parses_our_qss_without_a_single_complaint():
    """Ни одного «Unknown property» и ни одного «Could not parse».

    Это единственный способ поймать опечатку в QSS: приложение с битым правилом
    не падает и ничего не пишет в лог — просто выглядит не так, как задумано, и
    поди пойми, какая из сотни строк виновата. Qt ругается в свой message
    handler, вот его и слушаем.
    """
    # Ловим ImportError руками, а не через importorskip: модуль на месте, падает
    # загрузка его бинарника (на dev-VM нет libEGL). importorskip рассчитан на
    # «модуля нет» и такую ошибку пробрасывает — тест падал бы вместо пропуска.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6 import QtWidgets
        from PySide6.QtCore import qInstallMessageHandler
        from PySide6.QtWidgets import QApplication
    except ImportError as e:
        pytest.skip(f"GUI-зависимость недоступна: {e}")

    from launcher.ui.theme import apply_theme

    complaints: list[str] = []

    def handler(mode, context, message):
        if "Unknown property" in message or "Could not parse" in message:
            complaints.append(message)

    app = QApplication.instance() or QApplication([])
    qInstallMessageHandler(handler)
    try:
        apply_theme(app)
        # Каждый тип, который упоминает QSS, обязан быть создан и отрисован:
        # разбор ленивый и по типам.
        for name in _styled_widget_names():
            widget = getattr(QtWidgets, name)()
            widget.ensurePolished()
            widget.grab()
    finally:
        qInstallMessageHandler(None)

    assert not complaints, "Qt не понял наш QSS:\n" + "\n".join(sorted(set(complaints)))
