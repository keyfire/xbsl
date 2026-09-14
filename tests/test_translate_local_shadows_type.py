"""A local translated into the word of a platform type the same method reads is a collision.

The method namespace already holds the locals, and two of them under one English word are
reported, since the compiler refuses the second. A platform type read as the root of a static
access belongs to that namespace too: a parameter named for a transfer encoding takes the word of
the encoding type from the compiler dictionary, and in English the parameter hides the type, so
`Encoding.Utf8` asks a string for a property. Nothing reported it; the tree went out and did not
build. The translator cannot pick another word for the parameter, but it can say where the two
meet, and a dictionary entry written for that method separates them.
"""

from __future__ import annotations

from pathlib import Path

from xbsl.translation import dictionary as dict_module
from xbsl.translation.project import translate_project


def _dictionary(tokens: dict | None = None) -> dict_module.Dictionary:
    return dict_module.Dictionary(tokens=dict(tokens or {}), phrases={}, literals={})


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_MODULE = (
    "метод РазобратьВложение(Текст: Строка, Кодирование: Строка): Байты\n"
    '    если Кодирование == "base64"\n'
    "        возврат Кодировки.Base64.Декодировать(Текст)\n"
    "    ;\n"
    "    возврат Текст.ВБайты(Кодировка.Utf8)\n"
    ";\n"
)


def test_a_parameter_in_the_word_of_a_type_the_method_reads_is_a_collision(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Вложения.xbsl", _MODULE)
    report = translate_project(root, _dictionary(), None)
    assert report.problems == [
        "method:РазобратьВложение - 'Encoding' <- Кодирование (Вложения.xbsl:1:40),"
        " Кодировка (Вложения.xbsl:5:26)",
    ], report.problems


def test_an_entry_written_for_the_method_separates_the_parameter_from_the_type(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Вложения.xbsl", _MODULE)
    report = translate_project(root, _dictionary({
        "РазобратьВложение.Кодирование": "TransferEncoding",
    }), None)
    # The collision is judged by the word the local really gets, the qualified entry first.
    assert report.problems == [], report.problems


def test_a_type_that_is_only_written_as_a_type_hides_nothing(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Вложения.xbsl", (
        "метод Прочитать(Кодирование: Кодировка): Строка\n"
        '    знч Результат = новый Кодировка("utf-8")\n'
        "    возврат Кодирование.Псевдоним\n"
        ";\n"
    ))
    report = translate_project(root, _dictionary(), None)
    # A type expression and a constructor name a type where no variable can stand.
    assert report.problems == [], report.problems


def test_a_type_read_by_another_method_is_not_this_method_s_concern(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Вложения.xbsl", (
        "метод Разобрать(Кодирование: Строка): Строка\n"
        "    возврат Кодирование\n"
        ";\n"
        "\n"
        "метод ВБайты(Текст: Строка): Байты\n"
        "    возврат Текст.ВБайты(Кодировка.Utf8)\n"
        ";\n"
    ))
    report = translate_project(root, _dictionary(), None)
    assert report.problems == [], report.problems


def test_a_table_of_a_query_is_not_a_type_the_method_reads(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Вложения.xbsl", (
        "метод Выбрать(Кодирование: Строка)\n"
        "    знч Выборка = Запрос{\n"
        "        ВЫБРАТЬ Кодировка.Имя ИЗ Склады КАК Кодировка\n"
        "    }\n"
        ";\n"
    ))
    report = translate_project(root, _dictionary(), None)
    assert report.problems == [], report.problems
