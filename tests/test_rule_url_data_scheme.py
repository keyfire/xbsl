"""code/url-data-scheme: a data address handed to the Url constructor.

The constructor parses `data:` as a hierarchical address - a slash after the scheme, `;` and
`,` encoded as path characters - and the browser refuses the result with `ERR_INVALID_URL`,
so a picture fed such a Url draws nothing. The rule reports a string literal opening with the
scheme as the first argument of the constructor.

The rule tokenizes the module, so the tests that lint code carry `needs_data` (the lexer needs
language.json); the registration check runs in every checkout.
"""

import pytest

from xbsl import engine, i18n
from xbsl.diagnostics import Severity

RULE = "code/url-data-scheme"


def _lint(text, name="Картинки.xbsl"):
    return engine.run_sources([engine.load_text(name, text)], select={RULE})


def _method(body):
    return f"метод Значок(): Url\n    {body}\n;\n"


def test_rule_registered_as_a_file_warning_on_by_default():
    info = next(r for r in engine.RULES if r.id == RULE)
    assert info.tier == "D" and info.scope == "file" and info.enabled_by_default
    assert info.severity is Severity.WARNING


@pytest.mark.needs_data
def test_a_data_literal_in_the_constructor_is_reported():
    diags = _lint(_method('возврат новый Url("data:image/svg+xml;utf8,<svg/>")'))
    assert [(d.line, d.col) for d in diags] == [(2, 23)]
    assert "ERR_INVALID_URL" in diags[0].message and "'новый Url'" in diags[0].message
    assert diags[0].severity is Severity.WARNING


@pytest.mark.needs_data
@pytest.mark.parametrize("call", [
    'новый Url("data:image/png;base64," + Данные)',
    'новый Url("DATA:image/png;base64,AAAA")',
    'новый Url(Ссылка = "data:image/png;base64,AAAA", РаскодироватьЗначение = Ложь)',
    'новый Url("data:image/svg+xml;utf8,%{Разметка}", Ложь)',
    'новый Стд::Http::Url("data:text/plain,x")',
])
def test_every_shape_of_the_literal_is_reported(call):
    assert len(_lint(_method(f"возврат {call}"))) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("call", [
    'новый Url("https://example.com/data:x")',
    'новый Url(Адрес)',
    'новый Url("%{Схема}:image/png")',
    'новый Url("/api/pic/" + "data:")',
    'Строка("data:x")',
    'новый Массив<Строка>(["data:x"])',
])
def test_other_addresses_and_calls_stay_silent(call):
    assert _lint(_method(f"возврат {call}")) == []


@pytest.mark.needs_data
def test_a_data_address_in_a_variable_is_not_traced():
    """The literal is the shape of the live case; a traced variable would be a guess."""
    body = 'знч Адрес = "data:image/png;base64,AAAA"\n    возврат новый Url(Адрес)'
    assert _lint(_method(body)) == []


@pytest.mark.needs_data
def test_the_english_spelling_is_reported_in_english():
    i18n.set_lang("en")
    text = 'method Badge(): Url\n    return new Url("data:image/svg+xml;utf8,<svg/>")\n;\n'
    diags = _lint(text, name="Pictures.xbsl")
    assert [(d.line, d.col) for d in diags] == [(2, 20)]
    assert "'new Url'" in diags[0].message and "Image" in diags[0].message


@pytest.mark.needs_data
def test_a_yaml_file_is_not_read():
    assert _lint('Значение: =новый Url("data:x")\n', name="Форма.yaml") == []
