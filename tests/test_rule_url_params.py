"""code/url-params-partial-encoding: the partial encoding of Url query parameter values.

The defect is a live one: a value that is itself an address arrives cut at its first "&",
because "&" and "=" inside the value stay separators (the platform registry probe of
2026-08). The rule is info and OFF by default - the values are invisible statically - so
every test selects it explicitly.

The module is listed in conftest._DATA_DEPENDENT: the rule itself needs no catalog for the
Russian spelling, but lexing a module does (the lexer keywords come from the language data),
so a data-less checkout skips the module whole. The English-spelling test additionally
depends on the dictionary and carries its own mark.
"""

import pytest

from xbsl import engine

RULE = "code/url-params-partial-encoding"


def _lint(content, name="Проба.xbsl"):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def test_the_chain_is_reported_at_the_method_name():
    d = _lint(
        "метод Ссылка(): Строка\n"
        '    возврат новый Url("http://x").СПараметрамиЗапроса(Пар()).ВСтроку()\n'
        ";\n"
    )
    assert [(x.rule_id, x.line) for x in d] == [(RULE, 2)]
    assert "частично" in d[0].message


def test_a_static_builder_chain_is_reported_too():
    d = _lint(
        "метод Ссылка(): Строка\n"
        '    возврат Url.СБазовымUrl("http://x").СПараметрамиЗапроса("a=b").ВСтроку()\n'
        ";\n"
    )
    assert len(d) == 1, [x.message for x in d]


def test_a_method_of_that_name_declared_or_named_bare_is_silent():
    # A declaration of an own method and a bare reference are not member calls.
    d = _lint(
        "метод СПараметрамиЗапроса(): Строка\n"
        '    возврат "x"\n'
        ";\n"
        "метод Другой(): Строка\n"
        "    возврат СПараметрамиЗапроса()\n"
        ";\n"
    )
    assert d == [], [x.message for x in d]


def test_a_member_read_without_a_call_is_silent():
    d = _lint(
        "метод Другой(О: Структура): Неопределено\n"
        "    знч Х = О.СПараметрамиЗапроса\n"
        "    возврат Неопределено\n"
        ";\n"
    )
    assert d == [], [x.message for x in d]


# The default-off state is NOT asserted here: in a process with the plugin installed the
# project profile turns these rules on, and such a test would judge the machine rather than
# the engine. The default is guarded by tests/test_metadata_sync.py, which reads the
# registry in a subprocess with XBSL_NO_PLUGINS=1.


@pytest.mark.needs_data
def test_the_english_spelling_is_reported_as_well():
    d = _lint(
        "метод Link(): Строка\n"
        '    возврат новый Url("http://x").WithRequestParameters("a=b").ВСтроку()\n'
        ";\n"
    )
    assert [(x.rule_id, x.line) for x in d] == [(RULE, 2)]
