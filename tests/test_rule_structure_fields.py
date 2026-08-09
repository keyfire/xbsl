"""Checks of code/unknown-structure-field (fields of project structures, tier D, project scope).

The rule parses XBSL, and the parser needs the Element language data; without it the whole
module is skipped (conftest does not know this file, so it guards itself).
"""

import pytest

from xbsl import dataset, engine
from xbsl.cli import discover

pytestmark = pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – сгенерируйте: python tools/extract.py --dist ...",
)

RULE = "code/unknown-structure-field"

CATALOG = (
    "структура КарточкаДанные\n"
    "    пер Заголовок: Строка\n"
    "    пер Иконка: Строка\n"
    "    метод Заполнить()\n    ;\n"
    ";\n"
)


def _lint_dir(tmp_path, files):
    """The file names are DATA (a project writes Russian file names), hence a dict, not kwargs."""
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE]


# --- The signal ------------------------------------------------------------------------

def test_unknown_field_through_parameter(tmp_path):
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Потребитель.xbsl": (
            "метод Показать(Карточка: Каталог.КарточкаДанные)\n"
            "    Сообщить(Карточка.АдресИконки)\n"
            ";\n"
        ),
    })
    assert len(hits) == 1
    assert "Каталог.КарточкаДанные" in hits[0].message and "АдресИконки" in hits[0].message
    assert (hits[0].line, hits[0].col) == (2, 14)


def test_unknown_field_through_loop_variable(tmp_path):
    # the everyday shape: the element type comes from the collection of the parameter
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Потребитель.xbsl": (
            "метод Показать(Список: Массив<Каталог.КарточкаДанные>)\n"
            "    для Карточка из Список\n"
            "        Сообщить(Карточка.Титул)\n"
            "    ;\n"
            ";\n"
        ),
    })
    assert len(hits) == 1 and "Титул" in hits[0].message


def test_unknown_field_of_own_module_structure(tmp_path):
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG + (
            "метод Печать(Данные: КарточкаДанные)\n"
            "    Сообщить(Данные.Титул)\n"
            ";\n"
        ),
    })
    assert len(hits) == 1 and "Каталог.КарточкаДанные" in hits[0].message


def test_constructor_types_the_variable(tmp_path):
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Потребитель.xbsl": (
            "метод Создать()\n"
            "    знч Новая = новый Каталог.КарточкаДанные(Заголовок = \"А\", Иконка = \"Б\")\n"
            "    Сообщить(Новая.Титул)\n"
            ";\n"
        ),
    })
    assert len(hits) == 1 and "Титул" in hits[0].message


def test_close_name_is_hinted(tmp_path):
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Потребитель.xbsl": (
            "метод Показать(Карточка: Каталог.КарточкаДанные)\n"
            "    Сообщить(Карточка.Заголовки)\n"
            ";\n"
        ),
    })
    assert len(hits) == 1 and "Заголовок" in hits[0].message


def test_pair_of_module_files_declares_into_one_namespace(tmp_path):
    # `X.xbsl` and `X.Объект.xbsl` are halves of one module - a field of either counts
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Каталог.Объект.xbsl": "структура Строка Данных\n;\n",
        "Потребитель.xbsl": (
            "метод Показать(Карточка: Каталог.КарточкаДанные)\n"
            "    Сообщить(Карточка.Иконка)\n"
            ";\n"
        ),
    })
    assert not hits


# --- Guards ------------------------------------------------------------------------------

def test_existing_field_and_method_not_flagged(tmp_path):
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Потребитель.xbsl": (
            "метод Показать(Карточка: Каталог.КарточкаДанные)\n"
            "    Сообщить(Карточка.Заголовок)\n"
            "    Карточка.Заполнить()\n"
            ";\n"
        ),
    })
    assert not hits


def test_name_declared_twice_with_different_types_not_flagged(tmp_path):
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Потребитель.xbsl": (
            "метод Показать(Карточка: Каталог.КарточкаДанные)\n"
            "    пер Карточка = \"строка\"\n"
            "    Сообщить(Карточка.Титул)\n"
            ";\n"
        ),
    })
    assert not hits


def test_second_hop_not_judged(tmp_path):
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Потребитель.xbsl": (
            "метод Показать(Карточка: Каталог.КарточкаДанные)\n"
            "    Сообщить(Карточка.Заголовок.НетТакого)\n"
            ";\n"
        ),
    })
    assert not hits


def test_unknown_module_not_judged(tmp_path):
    # the qualified name points at a module this project does not declare (a library type)
    hits = _lint_dir(
        tmp_path, {
        "Потребитель.xbsl": (
            "метод Показать(Карточка: Чужой.Карточка)\n"
            "    Сообщить(Карточка.Титул)\n"
            ";\n"
        ),
    })
    assert not hits


def test_latin_member_not_judged(tmp_path):
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Потребитель.xbsl": (
            "метод Показать(Карточка: Каталог.КарточкаДанные)\n"
            "    Сообщить(Карточка.title)\n"
            ";\n"
        ),
    })
    assert not hits


def test_bare_name_shared_with_a_stdlib_type_not_judged(tmp_path):
    # a structure named like a stdlib type: which one the compiler picks is not for a guess
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": (
            "структура Массив\n"
            "    пер Заголовок: Строка\n"
            ";\n\n"
            "метод Печать(Данные: Массив)\n"
            "    Сообщить(Данные.Размер)\n"
            ";\n"
        ),
    })
    assert not hits


def test_collection_of_several_arguments_not_judged(tmp_path):
    hits = _lint_dir(
        tmp_path, {
        "Каталог.xbsl": CATALOG,
        "Потребитель.xbsl": (
            "метод Показать(Список: Соответствие<Строка, Каталог.КарточкаДанные>)\n"
            "    для Пара из Список\n"
            "        Сообщить(Пара.Титул)\n"
            "    ;\n"
            ";\n"
        ),
    })
    assert not hits
