"""yaml/standard-field-length: the platform limits on the standard fields.

The limits are not a guess: the compiler answers on 50/51 and 400/401,
and the compiler rejected exactly the two over-the-limit ones ('The length of attribute
"Код" must fall between zero and 50', the same wording for Наименование and 400).

The rule needs no Element data, so the tests live outside test_rules (that module is
skipped whole in a data-less checkout) and run in the public CI.
"""

from xbsl import engine


def _lint(name, content, **kw):
    return engine.run_sources([engine.load_text(name, content)], **kw)


_STANDARD_FIELDS_HEAD = "ВидЭлемента: Справочник\nИд: 11111111-1111-1111-1111-111111111111\nИмя: О\n"


def _standard_field(body: str):
    return _lint("О.yaml", _STANDARD_FIELDS_HEAD + body, select={"yaml/standard-field-length"})


def test_standard_field_length_over_the_limit():
    # The compiler: 'The length of attribute "Код" must fall between zero and 50',
    # and the same for Наименование against 400 - the rejected field then drops out of the object.
    d = _standard_field(
        "Реквизиты:\n"
        "    -\n        Имя: Код\n        Тип: Строка\n        Длина: 51\n"
        "    -\n        Имя: Наименование\n        Длина: 401\n"
    )
    assert len(d) == 2, [x.message for x in d]
    assert (d[0].line, d[0].col) == (8, 9) and "50" in d[0].message
    assert (d[1].line, d[1].col) == (11, 9) and "400" in d[1].message


def test_standard_field_length_at_the_limit_is_silent():
    # The same check applied cleanly with 50 and 400 - the boundary is legal.
    d = _standard_field(
        "Реквизиты:\n"
        "    -\n        Имя: Код\n        Тип: Строка\n        Длина: 50\n"
        "    -\n        Имя: Наименование\n        Длина: 400\n"
    )
    assert d == [], [x.message for x in d]


def test_standard_field_length_ignores_developer_fields():
    # A developer's field carries МаксимальнаяДлина, and a numeric Код counts digits by another
    # a limit that is not measured - neither is judged.
    d = _standard_field(
        "Реквизиты:\n"
        "    -\n        Ид: 22222222-2222-2222-2222-222222222222\n"
        "        Имя: Наименование2\n        Тип: Строка\n        МаксимальнаяДлина: 900\n"
        "    -\n        Имя: Код\n        Тип: Число\n        Длина: 500\n"
    )
    assert d == [], [x.message for x in d]
