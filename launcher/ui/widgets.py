# -*- coding: utf-8 -*-
"""
launcher/ui/widgets.py
------------------------------------------------------------
Виджеты, которых QSS не выражает: шапка окна и панель с уголками-скобками.

Своя отрисовка — дорогое удовольствие: QSS к ней уже не применяется, и всё,
что стиль делал даром, приходится держать руками. Поэтому здесь ровно два
виджета, и оба рисуют только ДОБАВКУ поверх нативной отрисовки, не подменяя её.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QStyle,
    QStyleOption,
    QVBoxLayout,
    QWidget,
)

from launcher.ui.decals import DECAL_H, DECAL_W, HEADER_SVG, render_svg
from launcher.ui.theme import BORDER, CYAN, MONO, TEXT, TEXT_MUTED

# Длина уголка-скобки и толщина линии.
BRACKET_LEN = 9
BRACKET_WIDTH = 2


class BracketGroupBox(QGroupBox):
    """Секция с L-образными метками в углах.

    Уголки-скобки — маркер жанра, которого QSS не умеет: рамку он рисует
    целиком, а нам нужны только её углы. Рисуем ПОВЕРХ нативной отрисовки
    (super().paintEvent сначала), поэтому весь QSS секции — фон, рамка,
    заголовок — продолжает работать как раньше.
    """

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        pen = QPen(QColor(CYAN))
        pen.setWidth(BRACKET_WIDTH)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)

        rect = self.rect().adjusted(1, 1, -1, -1)
        # Верхний край не трогаем: там уже проходит циановая рейка и сидит
        # заголовок — скобка сверху налезла бы на них и вышла бы каша.
        for x, dx in ((rect.left(), 1), (rect.right(), -1)):
            painter.drawLine(x, rect.bottom(), x + dx * BRACKET_LEN, rect.bottom())
            painter.drawLine(x, rect.bottom(), x, rect.bottom() - BRACKET_LEN)

        painter.end()


class HeaderBar(QWidget):
    """Шапка: имя инструмента, версия и декаль-схема этажа справа.

    Версия здесь не для красоты: наладчик звонит с объекта, и первый вопрос —
    «какая у вас сборка». Пусть будет на экране, а не в свойствах файла.
    """

    def __init__(self, title: str, version: str, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(2)

        name = QLabel(title.upper())
        name.setStyleSheet(
            f"color: {TEXT}; font-family: {MONO}; font-size: 13px;"
            f" font-weight: 700; letter-spacing: 2px;"
        )
        left.addWidget(name)

        meta = QLabel(version)
        meta.setStyleSheet(
            f"color: {TEXT_MUTED}; font-family: {MONO}; font-size: 10px;"
            f" letter-spacing: 1px;"
        )
        left.addWidget(meta)

        layout.addLayout(left)
        layout.addStretch(1)

        # Декаль рисуется под текущий devicePixelRatio: на масштабе Windows
        # 125/150% растр в логическом размере мылил бы.
        plan = QLabel()
        ratio = self.devicePixelRatioF() or 1.0
        plan.setPixmap(render_svg(HEADER_SVG, DECAL_W, DECAL_H, ratio))
        plan.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(plan, 0, Qt.AlignVCenter)

        self.setStyleSheet(
            f"HeaderBar {{ background: #ffffff; border: 1px solid {BORDER};"
            f" border-left: 3px solid {CYAN}; border-top: 2px solid {CYAN}; }}"
        )

    def paintEvent(self, event) -> None:
        """Без этого QSS шапки не рисуется вовсе — ни фона, ни рамки.

        ⚠ Требование Qt, а не наша причуда: прямой подкласс QWidget не
        применяет свой стиль сам. Готовые виджеты (QGroupBox, QPushButton) уже
        делают это внутри, а голый QWidget обязан прогнать PE_Widget через
        QStyle руками. Правило при этом выглядит совершенно рабочим — просто
        молча ничего не красит.
        """
        option = QStyleOption()
        option.initFrom(self)

        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)
        painter.end()
