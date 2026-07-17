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

Откуда графика:
    - Декаль шапки — иконки Lucide (ISC). Выбрана владельцем из четырёх
      вариантов, см. docs/design/decals/. ⚠ ISC требует, чтобы копирайт и текст
      лицензии присутствовали во всех копиях: отсюда LUCIDE_NOTICE ниже — он
      обязан ехать внутри EXE, а не лежать файлом рядом.
    - Иконка окна нарисована здесь: прав третьих лиц в ней нет.

Чего здесь нет и не будет: Pinterest, Vecteezy, Freepik, VectorStock. Pinterest —
доска чужих картинок без автора и лицензии. У остальных «free for commercial
use» означает атрибуцию либо подписку. На itch.io фильтр «free» — это ЦЕНА, а
не лицензия; настоящий CC0-фильтр там есть, но за ним лежит пиксель-арт для
игр — растр, чужая эстетика, в шапке инженерного окна наклейка.

Вектор, а не растр: у наладчика на ноутбуке вполне может стоять масштаб 125%
или 150%, где растр поплывёт. SVG рисуется под текущий devicePixelRatio.

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
# Декаль шапки: цепочка иконок Lucide
# ------------------------------------------------------------
# ⚠ ОБЯЗАТЕЛЬСТВО, а не справка.
#
# Контуры иконок ниже взяты из Lucide (https://lucide.dev), лицензия ISC. Она
# разрешает коммерческое использование даром и без спроса, но ТРЕБУЕТ, чтобы
# копирайт и текст лицензии присутствовали во всех копиях. Лаунчер уезжает на
# объекты в виде EXE — значит текст обязан быть внутри EXE.
#
# Поэтому он здесь строкой, а не в файле рядом: файл потребовал бы --add-data,
# и забытый флаг превратил бы нарушение лицензии в тихую ошибку сборки. Копия
# для людей — THIRD-PARTY-LICENSES.md в корне репозитория.
#
# Уберёте иконки — уберите и это. Оставите иконки без этого — нарушите ISC.
# Стережёт test_lucide_icons_carry_their_licence.
LUCIDE_NOTICE = """ISC License

Copyright (c) 2026 Lucide Icons and Contributors

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE."""

# Контуры иконок Lucide (24x24), дословно из исходников. Менять их не надо:
# это чужая работа, и правки здесь означают, что при обновлении Lucide вы уже
# не сможете просто перевзять файл.
#
# Ни одна из пяти не входит в список иконок, производных от Feather, — значит
# применяется только ISC, без второго слоя MIT. Добавите новую — сверьтесь со
# списком в LICENSE Lucide, иначе к NOTICE придётся добавлять и MIT.
LUCIDE_ICONS = {
    "scan-line": ('<path d="M3 7V5a2 2 0 0 1 2-2h2"/>'
                  '<path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
                  '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
                  '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
                  '<path d="M7 12h10"/>'),
    "cpu": ('<rect width="16" height="16" x="4" y="4" rx="2"/>'
            '<rect width="6" height="6" x="9" y="9" rx="1"/>'
            '<path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/>'
            '<path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/>'
            '<path d="M9 2v2"/><path d="M9 20v2"/>'),
    "circuit-board": ('<rect width="18" height="18" x="3" y="3" rx="2"/>'
                      '<path d="M11 9h4a2 2 0 0 0 2-2V3"/>'
                      '<circle cx="9" cy="9" r="2"/>'
                      '<path d="M7 21v-4a2 2 0 0 1 2-2h4"/>'
                      '<circle cx="15" cy="15" r="2"/>'),
    "network": ('<rect x="16" y="16" width="6" height="6" rx="1"/>'
                '<rect x="2" y="16" width="6" height="6" rx="1"/>'
                '<rect x="9" y="2" width="6" height="6" rx="1"/>'
                '<path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/>'
                '<path d="M12 12V8"/>'),
    "radar": ('<path d="M19.07 4.93A10 10 0 0 0 6.99 3.34"/>'
              '<path d="M4 6h.01"/>'
              '<path d="M2.29 9.62A10 10 0 1 0 21.31 8.35"/>'
              '<path d="M16.24 7.76A6 6 0 1 0 8.23 16.67"/>'
              '<path d="M12 18h.01"/>'
              '<path d="M17.99 11.66A6 6 0 0 1 15.77 16.67"/>'
              '<circle cx="12" cy="12" r="2"/>'
              '<path d="m13.41 10.59 5.66-5.66"/>'),
}

# Порядок — цепочкой слева направо; замыкает радар, он же единственный
# пурпурный. Пурпур здесь не нарушает правило «действие»: это знак, а не
# элемент управления, трогать его нельзя.
_STRIP_ORDER = ["scan-line", "cpu", "circuit-board", "network", "radar"]


def _build_strip() -> str:
    parts = []
    for i, name in enumerate(_STRIP_ORDER):
        x = 8 + i * 50
        colour = ACCENT if name == "radar" else CYAN
        parts.append(
            f'<g transform="translate({x} 10)" fill="none" stroke="{colour}" '
            f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
            f'opacity="0.75">{LUCIDE_ICONS[name]}</g>')
        if i < len(_STRIP_ORDER) - 1:
            parts.append(f'<path d="M{x + 28} 22 H{x + 46}" stroke="{CYAN}" '
                         f'stroke-width="0.8" opacity="0.35"/>')

    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 44">'
            + "".join(parts) + "</svg>")


# Декаль шапки. Выбрана владельцем из четырёх вариантов (docs/design/decals/):
# схема этажа не читалась планом, спектр/осциллограмма/радар отклонены.
HEADER_SVG = _build_strip()

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
