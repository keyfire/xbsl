"""Рантайм-доступ к документации Элемента (docs.sqlite): поиск, страница, дерево, символ.

База собирается `tools/extract_docs.py` из дистрибутива и лежит в бандле данных
`<корень>/<версия>/docs.sqlite` рядом со `stdlib.json` (см. dataset.py). Документация
необязательна: если базы нет, `available()` возвращает Ложь, а прочие функции – пустой
результат, чтобы MCP-сервер и LSP работали и без неё.

Соединение открывается на каждый запрос и сразу закрывается: запросы редкие (по действию
пользователя), зато файл базы не держится открытым – его можно пересобрать при живом сервере
(на Windows открытое соединение блокирует перезапись).

Поверх этого API строятся: инструменты MCP (Клод ищет методы, их свойства и параметры),
эндпоинт LSP "дока для символа под курсором" и панель расширения (дерево + просмотр HTML).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from xbsllint import dataset

_DB_NAME = "docs.sqlite"
# Токен запроса: буквы (вкл. кириллицу), цифры, подчёркивание – всё прочее для FTS5 отбрасываем.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# Картинки лежат файлами рядом с базой (`<версия>/assets/...`), mime определяем по расширению.
_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
}


def available(version: str | None = None) -> bool:
    """Есть ли база документации для версии данных."""
    return dataset.has_data_file(_DB_NAME, version)


def _open(version: str | None = None) -> sqlite3.Connection | None:
    """Свежее соединение только для чтения (закрывать вызывающему) или None, если базы нет."""
    if not available(version):
        return None
    uri = Path(dataset.data_file(_DB_NAME, version)).as_uri() + "?mode=ro"  # file-URI на любой ОС
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _fts_query(query: str) -> str:
    """Свободный текст -> безопасное выражение FTS5: слова в кавычках через И, последнее с префиксом."""
    tokens = _TOKEN_RE.findall(query)
    if not tokens:
        return ""
    terms = [f'"{t}"' for t in tokens[:-1]]
    terms.append(f'"{tokens[-1]}"*')  # префикс на последнем слове – удобно для набора на лету
    return " ".join(terms)


def search(query: str, limit: int = 10, version: str | None = None) -> list[dict]:
    """Полнотекстовый поиск по документации, ранжирование bm25 (лучшее – первым)."""
    match = _fts_query(query)
    if not match:
        return []
    con = _open(version)
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT p.id, p.title, p.qualified, p.kind, p.availability, p.url,"
            "       snippet(pages_fts, 3, '', '', ' ... ', 12) AS snippet "
            "FROM pages_fts f JOIN pages p ON p.id = f.id "
            "WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts) LIMIT ?",
            (match, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def page(doc_id: str, version: str | None = None) -> dict | None:
    """Полная запись страницы (с очищенным HTML) по её id или None."""
    con = _open(version)
    if con is None:
        return None
    try:
        row = con.execute(
            "SELECT id, kind, title, qualified, availability, url, html FROM pages WHERE id = ?",
            (doc_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def tree(version: str | None = None) -> list[dict]:
    """Плоский список узлов курируемого оглавления – дерево строит потребитель.

    Узел: node (id узла), parent (id родителя или None у раздела-вкладки), label (подпись),
    page (id страницы для ссылки, иначе None), kind (section/category/link).
    """
    con = _open(version)
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT node, parent, ord, label, page, kind FROM tree ORDER BY parent IS NOT NULL, parent, ord"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []  # база старой схемы (без курируемого дерева) – пусто, а не падение
    finally:
        con.close()


def for_symbol(name: str, version: str | None = None) -> str | None:
    """id страницы для имени символа/типа при УВЕРЕННОМ совпадении, иначе None.

    Совпадение – точный заголовок либо последний сегмент квалификатора (`Стд::...::Массив`);
    у типа предпочитаем страницу справочника (stdlib) топику руководства с тем же заголовком.
    Нечёткого (полнотекстового) фолбэка тут НЕТ: для метода-секции (напр. `Настроить`) точной
    страницы нет, а угаданный по слову топик руководства сбивает с толку – кандидатов подбирает
    вызывающий через search().
    """
    if not name:
        return None
    name = name.strip()
    con = _open(version)
    if con is None:
        return None
    try:
        exact = con.execute(
            "SELECT id FROM pages WHERE title = ? "
            "ORDER BY id LIKE 'stdlib/%' DESC, length(qualified) LIMIT 1",
            (name,),
        ).fetchone()
        if exact:
            return exact["id"]
        byq = con.execute(
            "SELECT id FROM pages WHERE qualified LIKE ? "
            "ORDER BY id LIKE 'stdlib/%' DESC, length(qualified) LIMIT 1",
            (f"%::{name}",),
        ).fetchone()
        return byq["id"] if byq else None
    finally:
        con.close()


def asset(asset_id: str, version: str | None = None) -> dict | None:
    """Байты картинки по её id (`assets/...`) с mime – файл рядом с базой, или None.

    Картинки хранятся не в базе, а файлами в `<корень>/<версия>/assets/...` (git-lfs). Путь
    ограничен подкаталогом assets – без выхода за пределы бандла.
    """
    if not asset_id.startswith("assets/") or ".." in asset_id:
        return None
    try:
        ver = dataset.resolve_version(version)
    except dataset.DatasetError:
        return None
    path = dataset.data_root() / ver / asset_id
    if not path.is_file():
        return None
    return {
        "id": asset_id,
        "mime": _MIME.get(path.suffix.lower(), "application/octet-stream"),
        "bytes": path.read_bytes(),
    }
