# -*- coding: utf-8 -*-
"""
docs/design/decals/variants.py
------------------------------------------------------------
Варианты декали для шапки лаунчера. Черновик на посмотреть, не часть сборки.

Запуск (из корня проекта):
    python docs/design/decals/variants.py

Кладёт рядом с собой:
    <имя>.svg          — исходник
    <имя>.png          — сам знак, увеличен в 3 раза
    header-<имя>.png   — он же в настоящей шапке окна, 1:1

Смотреть надо header-*.png: знак судят в контексте, а не отдельно. Первая
декаль («схема этажа») отдельно выглядела сносно, а в шапке не читалась.

Лицензии — в README.md рядом. Коротко: варианты 1–3 нарисованы здесь, прав
третьих лиц в них нет; вариант 4 собран из иконок Lucide (ISC) и требует
приложить к продукту текст лицензии.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication          # noqa: E402

from launcher.ui.theme import ACCENT, CYAN, apply_theme   # noqa: E402
from launcher.ui.decals import render_svg                  # noqa: E402
from launcher.ui.widgets import HeaderBar                  # noqa: E402

OUT = Path(__file__).parent
W, H = 260, 44


# ============================================================
# 1. Спектр: столбцы разной высоты
# ============================================================
def _spectrum() -> str:
    heights = [7, 14, 22, 11, 30, 18, 9, 25, 34, 16, 12, 28, 20, 8, 15, 31,
               13, 6, 23, 17, 27, 10, 19, 33, 14, 21, 9, 26, 12, 30, 16, 7]
    hot = {4, 8, 15, 23, 29}          # редкие пурпурные — «пики»
    bars = []
    for i, h in enumerate(heights):
        x = 2 + i * 8
        colour = ACCENT if i in hot else CYAN
        opacity = 0.85 if i in hot else 0.45
        bars.append(f'<rect x="{x}" y="{40 - h}" width="4" height="{h}" '
                    f'fill="{colour}" opacity="{opacity}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">'
            + "".join(bars)
            + f'<path d="M0 41 H{W}" stroke="{CYAN}" stroke-width="1" opacity="0.5"/>'
            + "</svg>")


# ============================================================
# 2. Осциллограмма: сетка и кривая
# ============================================================
def _waveform() -> str:
    grid = []
    for x in range(0, W + 1, 20):
        grid.append(f'<path d="M{x} 2 V42"/>')
    for y in range(2, H, 10):
        grid.append(f'<path d="M0 {y} H{W}"/>')

    import math
    points = []
    for x in range(0, W + 1, 4):
        t = x / 26.0
        y = 22 - (math.sin(t) * 9 + math.sin(t * 2.7) * 5)
        points.append(f"{x},{y:.1f}")

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">
  <g stroke="{CYAN}" stroke-width="0.5" opacity="0.22" fill="none">{''.join(grid)}</g>
  <polyline points="{' '.join(points)}" fill="none" stroke="{CYAN}"
            stroke-width="1.4" opacity="0.85"/>
  <g fill="{ACCENT}">
    <circle cx="72" cy="9.4" r="2"/>
    <circle cx="184" cy="33.6" r="2"/>
  </g>
  <path d="M0 22 H{W}" stroke="{CYAN}" stroke-width="0.5"
        stroke-dasharray="3 4" opacity="0.4" fill="none"/>
</svg>"""


# ============================================================
# 3. Радар: дуги, развёртка, отметки
# ============================================================
def _radar() -> str:
    cx, cy = 224, 22
    arcs = []
    for r in (8, 14, 20):
        arcs.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                    f'stroke="{CYAN}" stroke-width="0.8" opacity="0.45"/>')
    ticks = []
    for i in range(0, 26):
        x = 4 + i * 7
        long = i % 5 == 0
        ticks.append(f'<path d="M{x} 42 V{34 if long else 38}"/>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">
  <g stroke="{CYAN}" stroke-width="0.8" opacity="0.5" fill="none">{''.join(ticks)}</g>
  {''.join(arcs)}
  <path d="M{cx} {cy} L{cx + 19} {cy - 8}" stroke="{ACCENT}" stroke-width="1.4"
        opacity="0.9"/>
  <path d="M{cx} {cy} L{cx} {cy - 20} A20 20 0 0 1 {cx + 19} {cy - 8} Z"
        fill="{CYAN}" opacity="0.12"/>
  <g fill="{ACCENT}" opacity="0.85">
    <circle cx="{cx + 9}" cy="{cy - 11}" r="1.6"/>
    <circle cx="{cx - 12}" cy="{cy + 6}" r="1.6"/>
  </g>
  <g stroke="{CYAN}" stroke-width="0.8" opacity="0.35" fill="none">
    <path d="M4 12 H150 M4 18 H120 M4 24 H164 M4 30 H98"/>
  </g>
  <g fill="{CYAN}" opacity="0.5">
    <rect x="154" y="10" width="26" height="4"/>
    <rect x="124" y="16" width="14" height="4"/>
    <rect x="168" y="22" width="20" height="4"/>
  </g>
</svg>"""


# ============================================================
# 4. Иконная лента: Lucide (ISC)
# ============================================================
# Единственный вариант со сторонней графикой. Пути взяты из иконок Lucide
# как есть; stroke заменён на цвет темы (в оригинале currentColor).
#
# ⚠ ISC требует приложить к продукту текст лицензии и копирайт. Это не CC0:
# «бесплатно» тут не значит «без обязательств». Выберете этот вариант —
# в репозиторий и в сборку поедет NOTICE.
LUCIDE = {
    "circuit-board": ('<rect width="18" height="18" x="3" y="3" rx="2"/>'
                      '<path d="M11 9h4a2 2 0 0 0 2-2V3"/>'
                      '<circle cx="9" cy="9" r="2"/>'
                      '<path d="M7 21v-4a2 2 0 0 1 2-2h4"/>'
                      '<circle cx="15" cy="15" r="2"/>'),
    "cpu": ('<rect width="16" height="16" x="4" y="4" rx="2"/>'
            '<rect width="6" height="6" x="9" y="9" rx="1"/>'
            '<path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/>'
            '<path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/>'
            '<path d="M9 2v2"/><path d="M9 20v2"/>'),
    "network": ('<rect x="16" y="16" width="6" height="6" rx="1"/>'
                '<rect x="2" y="16" width="6" height="6" rx="1"/>'
                '<rect x="9" y="2" width="6" height="6" rx="1"/>'
                '<path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/>'
                '<path d="M12 12V8"/>'),
    "scan-line": ('<path d="M3 7V5a2 2 0 0 1 2-2h2"/>'
                  '<path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
                  '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
                  '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
                  '<path d="M7 12h10"/>'),
    "radar": ('<path d="M19.07 4.93A10 10 0 0 0 6.99 3.34"/>'
              '<path d="M4 6h.01"/>'
              '<path d="M2.29 9.62A10 10 0 1 0 21.31 8.35"/>'
              '<path d="M16.24 7.76A6 6 0 1 0 8.23 16.67"/>'
              '<path d="M12 18h.01"/>'
              '<path d="M17.99 11.66A6 6 0 0 1 15.77 16.67"/>'
              '<circle cx="12" cy="12" r="2"/>'
              '<path d="m13.41 10.59 5.66-5.66"/>'),
}


def _icon_strip() -> str:
    order = ["scan-line", "cpu", "circuit-board", "network", "radar"]
    parts = []
    for i, name in enumerate(order):
        x = 8 + i * 50
        colour = ACCENT if name == "radar" else CYAN
        parts.append(
            f'<g transform="translate({x} 10) scale(1)" fill="none" '
            f'stroke="{colour}" stroke-width="1.6" stroke-linecap="round" '
            f'stroke-linejoin="round" opacity="0.75">{LUCIDE[name]}</g>')
        if i < len(order) - 1:
            parts.append(f'<path d="M{x + 28} 22 H{x + 46}" stroke="{CYAN}" '
                         f'stroke-width="0.8" opacity="0.35"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">'
            + "".join(parts) + "</svg>")


VARIANTS = {
    "1-spectrum": _spectrum,
    "2-waveform": _waveform,
    "3-radar": _radar,
    "4-lucide-strip": _icon_strip,
}


def main() -> None:
    app = QApplication([])
    apply_theme(app)

    for name, build in VARIANTS.items():
        svg = build()
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")

        # Сам знак, крупно — разглядеть детали.
        render_svg(svg, W, H, 3.0).save(str(OUT / f"{name}.png"))

        # Он же в настоящей шапке, 1:1 — вот это и есть предмет выбора.
        header = HeaderBar("HA Lighting Compilers", "v3.0.0-dev")
        header.findChildren(type(header))  # noqa: B018
        label = header.layout().itemAt(2).widget()
        label.setPixmap(render_svg(svg, W, H, 1.0))
        header.resize(1100, 64)
        header.show()
        app.processEvents()
        header.grab().save(str(OUT / f"header-{name}.png"))
        header.close()

        print(f"OK  {name}")

    print("\nГотово:", OUT)


if __name__ == "__main__":
    main()
