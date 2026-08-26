"""yaml/duplicate-subtree: one interface subtree copied into another file."""

import pytest

from xbsl import engine, i18n
from xbsl.engine import RULES

_SELECT = {"yaml/duplicate-subtree"}


@pytest.fixture(autouse=True)
def _ru_lang():
    i18n.set_lang("ru")
    yield
    i18n.set_lang(None)


def _rows(count: int, first: int = 0) -> str:
    """A mapping deep enough to pass the threshold, with distinct names."""
    out = []
    for index in range(count):
        out.append(
            "        - Тип: Поле\n"
            "          Имя: Поле" + str(first + index) + "\n"
            "          Заголовок: Подпись" + str(first + index) + "\n"
            "          Ширина: " + str(10 + index) + "\n"
        )
    return "".join(out)


def _form(name: str, first: int = 0, rows: int = 15) -> str:
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 11111111-2222-3333-4444-55555555555" + str(first % 10) + "\n"
        "Имя: " + name + "\n"
        "Наследует:\n"
        "    Тип: Группа\n"
        "    Содержимое:\n" + _rows(rows, first)
    )


def _lint(files: dict[str, str]):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return engine.run_sources(sources, select=_SELECT)


def test_registered_and_off_by_default():
    info = next(r for r in RULES if r.id == "yaml/duplicate-subtree")
    assert info.enabled_by_default is False
    assert info.scope == "project"


def test_a_form_copied_into_another_file_is_found():
    diags = _lint({"А.yaml": _form("А"), "Б.yaml": _form("Б", first=100)})
    assert {d.path for d in diags} == {"А.yaml", "Б.yaml"}
    assert "повторяет устройство" in diags[0].message


def test_two_shapes_that_differ_are_clean():
    assert _lint({"А.yaml": _form("А"), "Б.yaml": _form("Б", first=100, rows=14)}) == []


def test_one_file_alone_is_not_a_copy():
    # Two mirrored branches of one form are a layout idiom, not a copy to pull out.
    doubled = _form("А") + "    Ещё:\n        Тип: Группа\n        Содержимое:\n" + _rows(15, 200)
    assert _lint({"А.yaml": doubled}) == []


def test_a_subtree_below_the_threshold_is_clean():
    assert _lint({"А.yaml": _form("А", rows=4), "Б.yaml": _form("Б", first=100, rows=4)}) == []


def test_nested_repeat_is_reported_once():
    diags = _lint({"А.yaml": _form("А"), "Б.yaml": _form("Б", first=100)})
    # The whole file and its every branch share the shape; only the maximal group is named.
    assert len(diags) == 2


def test_a_localized_strings_dictionary_is_out_of_scope():
    # Its per-language twin repeats its shape by definition.
    body = (
        "ВидЭлемента: ЛокализованныеСтроки\n"
        "Ид: 11111111-2222-3333-4444-555555555556\n"
        "Имя: Словарь\n"
        "Строки:\n"
        + "".join("    Ключ" + str(i) + ": Значение" + str(i) + "\n" for i in range(60))
    )
    assert _lint({"Словарь.yaml": body, "СловарьEn.yaml": body.replace("Словарь", "СловарьEn")}) == []
