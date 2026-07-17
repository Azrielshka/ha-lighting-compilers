# -*- coding: utf-8 -*-
"""
tools/make_icon.py
------------------------------------------------------------
Собрать .ico для EXE из того же SVG, которым лаунчер красит своё окно.

    python tools/make_icon.py build/launcher.ico

Зовётся из .github/workflows/release.yml перед PyInstaller. Руками не нужен.

Почему файл .ico не лежит в репозитории:
    Это производная от launcher/ui/decals.ICON_SVG. Закоммитить её — значит
    завести второй источник правды: поправят SVG, а в Проводнике останется
    старая иконка, и никто не поймёт почему. Генерируем на сборке.

Почему .ico вообще законен, хотя мы весь проект держим без файлов-ресурсов:
    Файл нужен на СБОРКЕ, а не в рантайме. PyInstaller вшивает его в ресурсы
    EXE ключом --icon, и рядом с готовым EXE он уже не нужен. Это не тот
    случай, что --add-data: забыть его нельзя — сборка упадёт, а не соберёт
    молча EXE без картинки.

⚠ setWindowIcon в коде и --icon у EXE — РАЗНЫЕ вещи. Первое красит окно и
панель задач у запущенной программы, второе — сам файл в Проводнике. Нужны оба.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Без дисплея: на раннере GitHub Actions его нет.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from launcher.ui.decals import ICON_SVG, render_svg  # noqa: E402

# Размеры, которые Windows спрашивает у .ico. 256 — для крупной плитки в
# Проводнике, 16 — для списка файлов.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def build(destination: Path) -> None:
    # QPixmap требует запущенного QGuiApplication, иначе падает на первом же
    # рендере — на раннере это выглядело бы как невнятный краш сборки.
    app = QGuiApplication.instance() or QGuiApplication([])

    destination.parent.mkdir(parents=True, exist_ok=True)

    images = [render_svg(ICON_SVG, size, size).toImage() for size in SIZES]

    # QPixmap.save в .ico кладёт ОДИН размер. Пишем контейнер сами: заголовок,
    # каталог, следом PNG-кадры. Формат допускает PNG внутри с Vista, а все
    # цели проекта — Windows 10+.
    import io
    from PySide6.QtCore import QBuffer, QByteArray

    frames = []
    for image in images:
        # ⚠ QByteArray обязан жить в своей переменной. QBuffer(QByteArray())
        # держит указатель на временный объект, который тут же собирает сборщик
        # мусора, — и процесс падает по segfault, без единого сообщения.
        storage = QByteArray()
        buffer = QBuffer(storage)
        buffer.open(QBuffer.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        frames.append(bytes(storage))

    out = io.BytesIO()
    out.write(b"\x00\x00\x01\x00")                    # reserved, type=icon
    out.write(len(frames).to_bytes(2, "little"))      # число кадров

    offset = 6 + 16 * len(frames)                     # заголовок + каталог
    for size, data in zip(SIZES, frames):
        # 256 в байт не влезает и записывается нулём — так велит формат.
        out.write(bytes([size if size < 256 else 0]))  # ширина
        out.write(bytes([size if size < 256 else 0]))  # высота
        out.write(b"\x00\x00")                         # палитра, reserved
        out.write((1).to_bytes(2, "little"))           # цветовых плоскостей
        out.write((32).to_bytes(2, "little"))          # бит на пиксель
        out.write(len(data).to_bytes(4, "little"))
        out.write(offset.to_bytes(4, "little"))
        offset += len(data)

    for data in frames:
        out.write(data)

    destination.write_bytes(out.getvalue())

    # app намеренно НЕ удаляем: QGuiApplication должен пережить картинки,
    # иначе выход из процесса даёт segfault.
    assert app is not None

    print(f"OK: {destination} ({destination.stat().st_size} байт, "
          f"размеры {', '.join(map(str, SIZES))})")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[4], file=sys.stderr)
        print("Использование: python tools/make_icon.py <путь.ico>", file=sys.stderr)
        return 2

    build(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
