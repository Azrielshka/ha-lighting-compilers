# Лицензии стороннего материала

Здесь перечислено всё чужое, что входит **в состав продукта** и уезжает на
объект вместе с EXE. Библиотеки, которые ставятся из `requirements.txt`
(PySide6, pandas, paramiko и прочие), сюда не входят: они приезжают со своими
лицензиями сами.

Файл нужен не для порядка. ISC и MIT разрешают коммерческое использование даром
и без спроса, но **требуют, чтобы копирайт и текст лицензии присутствовали во
всех копиях**. Это единственное, что они просят взамен, и не выполнить это —
значит нарушить лицензию.

---

## Lucide — иконки декали в шапке лаунчера

- **Что:** контуры пяти иконок (`scan-line`, `cpu`, `circuit-board`, `network`,
  `radar`) в `launcher/ui/decals.py`.
- **Откуда:** <https://lucide.dev>
- **Лицензия:** ISC

⚠ Текст лицензии продублирован **строкой в коде** (`decals.LUCIDE_NOTICE`), и
это не дублирование ради дублирования: лаунчер поставляется одним EXE, а
условие ISC — «во всех копиях». Файл рядом с EXE потребовал бы `--add-data` в
сборке PyInstaller, и забытый флаг превратил бы нарушение лицензии в тихую
ошибку сборки. Строка в модуле попадает в EXE сама.

Уберёте иконки — уберите и `LUCIDE_NOTICE`, и этот раздел.

```
ISC License

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
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

Часть иконок Lucide производна от проекта Feather и несёт дополнительно MIT.
**Ни одна из наших пяти в этот список не входит** — поэтому здесь только ISC.
Добавите новую иконку — сверьтесь со списком в `LICENSE` Lucide, иначе сюда
придётся дописать и MIT-блок Cole Bemis.

---

## Чего здесь нет и почему

Иконка окна и отклонённые варианты декали (`docs/design/decals/`) нарисованы в
этом репозитории. Прав третьих лиц в них нет, обязательств они не создают.

Материал из Pinterest, Vecteezy, Freepik и VectorStock в проект не берём:

- **Pinterest** — не источник графики, а доска чужих картинок. У изображения там
  нет ни автора, ни лицензии, ни происхождения.
- **Vecteezy / Freepik / VectorStock** — «free for commercial use» в их условиях
  означает обязательную атрибуцию либо подписку.
- **itch.io** — фильтр «free» это **цена**, а не лицензия. У ассета за $0 условия
  бывают любые, а чаще не указаны вовсе — тогда действует полное авторское
  право. CC0-фильтр там есть, но за ним пиксель-арт для игр.

⚠ И общее: у нас **коммерческое использование**. Инструментом настраивают
освещение на объектах за деньги — не важно, продаётся ли сам инструмент.
Лицензии «для личного использования» такой сценарий исключают явным пунктом.
