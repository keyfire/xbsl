"""Checks of the yaml/toggle-command-pair rule (a handmade toggle out of two commands).

The Russian fixtures need no generated Element data; the English-spelling test writes its
own terms into a temporary data root, so the module runs in a public checkout as well.
"""

import json

import pytest

from xbsl import dataset, engine, terms, uischema
from xbsl.cli import discover
from xbsl.rules import component_props

_RULE = "yaml/toggle-command-pair"
_VER = "9.9.9+0"


def _clear_caches():
    component_props._toggle_names.cache_clear()
    terms._reset()
    uischema._reset()


def _run(tmp_path, text: str, name: str = "Форма.yaml"):
    _clear_caches()
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    diags = engine.run(discover([str(path)]), select={_RULE})
    return [d for d in diags if d.rule_id == _RULE]


@pytest.fixture
def english_root(tmp_path):
    """A data root whose terms spell the command kind and the visibility key in English."""
    root = tmp_path / "data"
    ver_dir = root / _VER
    ver_dir.mkdir(parents=True)
    (ver_dir / "terms.json").write_text(
        json.dumps({"kinds": {"ОбычнаяКоманда": "UsualCommand"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (ver_dir / "uiterms.json").write_text(
        json.dumps({"properties": {"Visible": "Видимость"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "index.json").write_text(
        json.dumps({"available": [_VER], "default": _VER}), encoding="utf-8"
    )
    dataset.set_data_root(root)
    yield
    dataset.set_data_root(None)
    _clear_caches()


_FORM = """ВидЭлемента: КомпонентИнтерфейса
Ид: 11111111-2222-4333-8444-555555555555
Имя: Форма
Наследует:
    Тип: ФормаСписка<Неопределено>
    ДополнительныеКоманды:
        Тип: ФрагментКомандногоИнтерфейса
        Элементы:
            - =Обновить
            -
                Тип: ОбычнаяКоманда
                Видимость: {first}
                Обработчик: {first_handler}
                Представление: $Локализация.Показать
            -{between}
                Тип: ОбычнаяКоманда
                Видимость: {second}
                Обработчик: {second_handler}
                Представление: $Локализация.Скрыть
"""

_BETWEEN = """
                Тип: ОбычнаяКоманда
                Обработчик: ДругойОбработчик
                Представление: $Локализация.Другая
            -"""


def _form(first, second, handlers=("ПоказатьОбработчик", "СкрытьОбработчик"), between=""):
    return _FORM.format(
        first=first, second=second,
        first_handler=handlers[0], second_handler=handlers[1],
        between=between,
    )


def test_mirrored_pair_is_reported_at_the_first_visibility(tmp_path):
    diags = _run(tmp_path, _form("=не ПоказыватьПомеченные", "=ПоказыватьПомеченные"))
    assert len(diags) == 1
    assert diags[0].line == 12
    assert "ПереключаемаяКоманда" in diags[0].message
    assert diags[0].severity.value == "warning"


def test_mirrored_pair_in_the_other_order_is_reported(tmp_path):
    diags = _run(tmp_path, _form("=ПоказыватьПомеченные", "=не ПоказыватьПомеченные"))
    assert len(diags) == 1


def test_shared_handler_is_not_required(tmp_path):
    handlers = ("ПереключитьОбработчик", "ПереключитьОбработчик")
    diags = _run(
        tmp_path, _form("=не ПоказыватьПомеченные", "=ПоказыватьПомеченные", handlers)
    )
    assert len(diags) == 1


def test_parenthesized_negation_still_mirrors(tmp_path):
    diags = _run(tmp_path, _form("=не (ПоказыватьПомеченные)", "=ПоказыватьПомеченные"))
    assert len(diags) == 1


def test_unrelated_visibilities_are_silent(tmp_path):
    assert _run(tmp_path, _form("=не ПоказыватьПомеченные", "=ЕстьПраво")) == []


def test_negation_glued_to_an_identifier_is_not_a_negation(tmp_path):
    # `неАктивен` is an identifier of its own, not `не Активен`
    assert _run(tmp_path, _form("=неАктивен", "=Активен")) == []


def test_plain_values_are_silent(tmp_path):
    # a pair of literal visibilities carries no shared state to toggle
    assert _run(tmp_path, _form("Истина", "Ложь")) == []


def test_commands_apart_are_not_a_pair(tmp_path):
    text = _form(
        "=не ПоказыватьПомеченные", "=ПоказыватьПомеченные", between=_BETWEEN
    )
    assert _run(tmp_path, text) == []


def test_english_spelling_is_taken_from_the_data(english_root, tmp_path):
    text = (
        _form("=not ShowMarked", "=ShowMarked")
        .replace("Тип: ОбычнаяКоманда", "Тип: UsualCommand")
        .replace("Видимость:", "Visible:")
    )
    diags = _run(tmp_path, text)
    assert len(diags) == 1
