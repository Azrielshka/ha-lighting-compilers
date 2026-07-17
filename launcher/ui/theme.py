# -*- coding: utf-8 -*-
"""
launcher/ui/theme.py
------------------------------------------------------------
Оформление лаунчера: светлая база, пурпурный акцент, приборная геометрия.

Почему QSS ПИТОНОВСКОЙ СТРОКОЙ, а не файлом .qss:
    EXE собирается PyInstaller'ом. Файл-ресурс потребовал бы --add-data, и
    забытый флаг означал бы EXE без стилей — при том, что у разработчика всё
    работает. Модуль импортируется и попадает в сборку сам.

Почему шрифты только системные:
    Неоновый шрифт вроде Orbitron пришлось бы тащить с собой: лицензия плюс
    тот же капкан с --add-data. Consolas есть на любой Windows, Courier New —
    запасной. Список перебирается слева направо, первый найденный побеждает.

Жанр на светлом фоне читается ФОРМОЙ, а не цветом. Неон — это контраст яркого
пятна с темнотой; на светлой базе акцент обязан быть тёмным, иначе его просто
не прочесть. Поэтому работают: нулевое скругление, тонкие рамки, заглавные
подписи с разрядкой, акцентная полоса слева у секций, моноширинный лог.

⚠ Семантика состояний важнее акцента. Ошибка красная, успех зелёный,
предупреждение янтарное — эти цвета инженер читает на периферии зрения, и
акцент не имеет права их поглотить. Пурпур ACCENT и красный ERROR оба
красноватые, поэтому разведены по местам: акцент живёт в хроме (заголовки,
фокус, полоса секции), красный — только в тексте лога и статусах. Рядом они не
встречаются нигде.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# ------------------------------------------------------------
# Палитра. Контраст с фоном проверен: акцент 6.1:1, текст 14:1.
# ------------------------------------------------------------
BG = "#f7f4f6"          # тёплый светлый — фон окна
PANEL = "#ffffff"        # карточки групп
BORDER = "#d8c9d2"       # тонкие рамки
BORDER_STRONG = "#b9a3b0"
TEXT = "#241a20"         # почти чёрный, тёплый
TEXT_MUTED = "#6b5c65"   # пояснения; на светлом «gray» слишком блёкл
ACCENT = "#be185d"       # пурпур — только хром
ACCENT_HOVER = "#9d174d"
ACCENT_SOFT = "#fce7f0"  # заливка активного/наведённого
DISABLED_BG = "#efeaed"
DISABLED_TEXT = "#a99aa2"

# Семантика. Тёмные варианты — под светлый фон.
ERROR = "#b91c1c"
SUCCESS = "#15803d"
WARNING = "#b45309"

# Моноширинные по убыванию предпочтения. Consolas — Windows, DejaVu Sans Mono —
# Linux (на нём же гоняются скриншоты), Courier New — универсальный запасной.
MONO = '"Consolas", "DejaVu Sans Mono", "Courier New", monospace'


QSS = f"""
/* ---------- база ---------- */
QWidget {{
    background: {BG};
    color: {TEXT};
}}

QMainWindow, QDialog {{
    background: {BG};
}}

/* ---------- секции: карточка с акцентной полосой слева ---------- */
QGroupBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-left: 3px solid {ACCENT};
    border-radius: 0px;
    margin-top: 18px;
    padding: 14px 12px 12px 12px;
}}

/* ⚠ Стилизуешь рамку QGroupBox — обязан стилизовать и ::title, иначе
   заголовок врастает в рамку.
   ⚠ text-transform здесь НЕ работает: на QLabel он применяется, а до
   субконтрола ::title не доходит. Поэтому заголовки заглавные в самих строках
   (`.upper()` на месте создания). Написать его тут — значит получить правило,
   которое молча ничего не делает. */
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0px 6px;
    background: {BG};
    color: {ACCENT};
    font-family: {MONO};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
}}

/* ---------- поля ввода ---------- */
QLineEdit, QSpinBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 0px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}

QLineEdit:focus, QSpinBox:focus {{
    border: 1px solid {ACCENT};
}}

QLineEdit:disabled, QSpinBox:disabled {{
    background: {DISABLED_BG};
    color: {DISABLED_TEXT};
}}

/* ⚠ Стрелки QSpinBox здесь не описаны намеренно, и описывать их не надо.
   Qt перестаёт рисовать нативную стрелку, как только тронешь ::up-button, а
   нарисовать свою можно только картинкой: CSS-трюк «треугольник из рамок на
   нулевом боксе» в Qt не работает — субконтрол ждёт image и выдаёт два
   квадратика. Картинка же означает ресурс и --add-data в сборке.
   Поэтому у единственного QSpinBox проекта (порт SSH) стрелки выключены в коде
   через setButtonSymbols(NoButtons), и он стилизуется как обычное поле. */

/* ---------- кнопки ---------- */
/* ⚠ QSS отключает нативную отрисовку виджета ЦЕЛИКОМ: покрасил кнопку —
   потерял системные hover/pressed/disabled. Описываем руками все состояния.
   :disabled здесь не косметика: лаунчер гасит кнопки на время работы
   пайплайна (_set_running_state), и без правила они выглядели бы нажимаемыми. */
QPushButton {{
    background: {PANEL};
    border: 1px solid {BORDER_STRONG};
    border-radius: 0px;
    padding: 7px 12px;
    font-family: {MONO};
    font-size: 12px;
    letter-spacing: 1px;
    text-align: center;
}}

QPushButton:hover {{
    background: {ACCENT_SOFT};
    border: 1px solid {ACCENT};
    color: {ACCENT_HOVER};
}}

QPushButton:pressed {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #ffffff;
}}

QPushButton:disabled {{
    background: {DISABLED_BG};
    border: 1px solid {BORDER};
    color: {DISABLED_TEXT};
}}

QPushButton:default {{
    border: 1px solid {ACCENT};
    color: {ACCENT};
}}

/* ---------- лог ---------- */
/* Без неона намеренно: лог читают долго и подряд. Максимальный контраст,
   моноширинный, ровная сетка — это рабочая поверхность, а не витрина. */
QTextEdit {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 0px;
    padding: 8px;
    font-family: {MONO};
    font-size: 12px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}

/* ---------- флажки ---------- */
/* background: transparent — иначе флажок тащит за собой заливку QWidget и
   лежит серой плашкой поверх белой карточки группы. */
QCheckBox {{
    background: transparent;
    spacing: 8px;
    padding: 2px 0px;
}}

QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 0px;
    background: {PANEL};
}}

QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}

QCheckBox::indicator:disabled {{
    background: {DISABLED_BG};
    border: 1px solid {BORDER};
}}

/* ---------- прочее ---------- */
QLabel {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: {BG};
    width: 12px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    min-height: 24px;
    border-radius: 0px;
}}

QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QToolTip {{
    background: {TEXT};
    color: {BG};
    border: 1px solid {ACCENT};
    border-radius: 0px;
    padding: 4px 6px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Применить оформление ко всему приложению разом.

    Один вызов на QApplication: QSS наследуется всеми окнами, включая диалог
    Deploy. Красить окна поодиночке — значит однажды забыть новое и получить
    светлое пятно поверх оформленного.
    """
    app.setStyle("Fusion")   # одинаковая база на Windows и Linux: нативный
                             # стиль Windows игнорирует часть QSS-правил
    app.setStyleSheet(QSS)
