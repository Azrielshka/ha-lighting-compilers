# -*- coding: utf-8 -*-
"""
launcher/ui/decals.py
------------------------------------------------------------
Векторная графика лаунчера: декаль шапки, иконка окна.

Почему SVG ПИТОНОВСКОЙ СТРОКОЙ, а не файлом:
    Та же причина, что и у QSS в theme.py. EXE собирается PyInstaller'ом, и
    файл-ресурс потребовал бы --add-data: забыли флаг — окно без иконки и без
    декали, при том что у разработчика всё на месте. Модуль импортируется и
    попадает в сборку сам. `QSvgRenderer` умеет читать разметку прямо из
    QByteArray — проверено.

Почему рисуем сами, а не берём готовое:
    - Лицензии. Vecteezy / Freepik / VectorStock пишут «free for commercial
      use», а в условиях — обязательная атрибуция либо подписка. Инструмент
      уезжает на объекты, тащить в него чужую графику с хвостом не стоит.
      Настоящий CC0 существует, но это игровая графика: рисовалась под HUD
      космического шутера и в окне инженерного инструмента выглядит наклейкой.
    - Вектор. У наладчика на ноутбуке вполне может стоять масштаб 125% или
      150%, где растр поплывёт. SVG рисуется под текущий devicePixelRatio.

Почему вектор рисуется В КОД, а не остаётся картинкой: ширина линий и цвета
берутся из палитры темы. Поменяете акцент — графика поменяется с ним, а не
останется висеть прежним цветом.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from launcher.ui.theme import ACCENT, CYAN


# ------------------------------------------------------------
# Декаль шапки: схема этажа
# ------------------------------------------------------------
# Абстрактный план: корпус, коридор по центру, перегородки, точки светильников.
# Выбрана владельцем как «буквально то, что делает инструмент»: из плана этажа
# с группами света он и собирает конфигурацию.
#
# Намеренно НЕ похоже ни на один реальный объект: это знак, а не чертёж. План
# конкретного заказчика в шапке был бы враньём на всех остальных объектах.
# Проёмы в стенах коридора обязательны: сплошные линии читаются как таблица, а
# не как план — первая версия декали выглядела ровно так. План узнаётся по
# коридору с дверями и по НЕравным помещениям; идеальная сетка выдаёт таблицу.
FLOOR_PLAN_SVG = f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 46">
  <g fill="none" stroke="{CYAN}" stroke-linecap="square">

    <path d="M1 2 H259 V44 H1 Z" stroke-width="1.6" opacity="0.6"/>

    <g stroke-width="1.2" opacity="0.55">
      <path d="M1 19 H34 M48 19 H94 M108 19 H146 M160 19 H212 M226 19 H259"/>
      <path d="M1 29 H26 M40 29 H82 M96 29 H138 M152 29 H198 M212 29 H259"/>
    </g>

    <g stroke-width="1" opacity="0.45">
      <path d="M42 2 V19 M88 2 V19 M140 2 V19 M196 2 V19"/>
      <path d="M32 29 V44 M78 29 V44 M126 29 V44 M172 29 V44 M224 29 V44"/>
    </g>
  </g>

  <g fill="{ACCENT}" opacity="0.7">
    <circle cx="21" cy="10" r="1.8"/>
    <circle cx="65" cy="10" r="1.8"/>
    <circle cx="114" cy="10" r="1.8"/>
    <circle cx="168" cy="10" r="1.8"/>
    <circle cx="228" cy="10" r="1.8"/>
    <circle cx="16" cy="37" r="1.8"/>
    <circle cx="55" cy="37" r="1.8"/>
    <circle cx="102" cy="37" r="1.8"/>
    <circle cx="149" cy="37" r="1.8"/>
    <circle cx="198" cy="37" r="1.8"/>
    <circle cx="242" cy="37" r="1.8"/>
  </g>

  <g fill="{CYAN}" opacity="0.5">
    <circle cx="130" cy="24" r="1.2"/>
    <circle cx="60" cy="24" r="1.2"/>
    <circle cx="205" cy="24" r="1.2"/>
  </g>
</svg>
"""

# ------------------------------------------------------------
# Иконка окна: шина DALI с тремя узлами
# ------------------------------------------------------------
# Сейчас иконки нет вовсе — в панели задач Windows стоит заглушка Qt.
# Знак читаемый в 16px: рамка, линия шины, три узла.
ICON_SVG = f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="3" y="3" width="58" height="58" fill="#ffffff"
        stroke="{CYAN}" stroke-width="5"/>
  <path d="M13 32 H51" stroke="{CYAN}" stroke-width="5" stroke-linecap="square"/>
  <circle cx="17" cy="32" r="6" fill="{ACCENT}"/>
  <circle cx="32" cy="32" r="6" fill="{ACCENT}"/>
  <circle cx="47" cy="32" r="6" fill="{ACCENT}"/>
</svg>
"""


def render_svg(svg: str, width: int, height: int, ratio: float = 1.0) -> QPixmap:
    """Отрисовать SVG-строку в QPixmap заданного размера.

    ⚠ ratio — devicePixelRatio экрана. Рисуем в физических пикселях и помечаем
    результат, иначе на масштабе Windows 125/150% вектор отрисуется в
    логическом размере и растянется — то есть будет мылить ровно там, где SVG
    и затевался ради чёткости.
    """
    renderer = QSvgRenderer(QByteArray(svg.strip().encode("utf-8")))
    if not renderer.isValid():
        raise ValueError("SVG не разобрался — проверьте разметку")

    pixmap = QPixmap(int(width * ratio), int(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, width * ratio, height * ratio))
    painter.end()

    return pixmap


def window_icon() -> QIcon:
    """Иконка окна во всех размерах, которые спрашивает Windows.

    Кладём несколько растров, а не один: Qt масштабирует ближайший, и одного
    64px хватило бы для панели задач, но в заголовке окна (16px) он бы мылил.
    """
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        icon.addPixmap(render_svg(ICON_SVG, size, size))
    return icon
