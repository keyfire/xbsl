"""The code wrap of the translator: lines of code that the longer names pushed over the limit.

The fixtures are written as the translation leaves them: the English text, and next to it the
source it came from - shorter names, the same lines. The source decides which lines were long on
purpose, so it is spelled out for every case.
"""

from __future__ import annotations

from xbsl.translation import codewrap
from xbsl.translation.codewrap import wrap_code


def _lines(text: str) -> list[str]:
    return text.split("\n")


def test_a_call_breaks_after_the_last_comma_that_fits():
    source = "method Probe()\n    val A = S.Read(B, T, C.Settings())\n;\n"
    text = ("method Probe()\n"
            "    val Answer = Serializer.Read(Response.Body, Type<Row>, Requests.Settings())\n"
            ";\n")

    out, lined = wrap_code(text, source, limit=60)

    assert _lines(out) == [
        "method Probe()",
        "    val Answer = Serializer.Read(Response.Body, Type<Row>,",
        "        Requests.Settings())",
        ";",
        "",
    ]
    assert _lines(lined)[1:3] == ["    val A = S.Read(B, T, C.Settings())"] * 2, (
        "the comment pass after it judges each new line by the source line it came from")


def test_a_sibling_in_a_list_opened_above_keeps_its_indent():
    source = "method Probe()\n    val A = S.Read(\n        B, T, C(), D)\n;\n"
    text = ("method Probe()\n"
            "    val Answer = Serializer.Read(\n"
            "        Response.Body, Type<Row>, Requests.Settings(), Fallback.Value)\n"
            ";\n")

    out, _ = wrap_code(text, source, limit=50)

    assert _lines(out)[2:4] == [
        "        Response.Body, Type<Row>,",
        "        Requests.Settings(), Fallback.Value)",
    ]


def test_a_logical_operator_opens_the_continuation():
    source = 'method Probe(): Boolean\n    return K.Of(S.K) == K.Main and S.P == ""\n;\n'
    text = ("method Probe(): Boolean\n"
            '    return Kind.FromCode(Subscription.Kind) == Kind.Primary and Subscription.Parent == ""\n'
            ";\n")

    out, _ = wrap_code(text, source, limit=70)

    assert _lines(out)[1:3] == [
        "    return Kind.FromCode(Subscription.Kind) == Kind.Primary",
        '        and Subscription.Parent == ""',
    ], "the loosest operator wins over the comparisons around it"


def test_a_conditional_breaks_before_its_question_mark():
    source = 'method Probe()\n    val A = ((M.H and M.S != "") ? L.P(M) : "")\n;\n'
    text = ("method Probe()\n"
            '    val Address = ((Material.HasImage and Material.Slug != "") ? Links.PictureAddress(Material) : "")\n'
            ";\n")

    out, _ = wrap_code(text, source, limit=70)

    assert _lines(out)[1:3] == [
        '    val Address = ((Material.HasImage and Material.Slug != "")',
        '        ? Links.PictureAddress(Material) : "")',
    ], "not `cond ? a` over `: b` - the colon waits for its question mark"


def test_a_line_that_opens_with_the_question_mark_breaks_before_the_colon():
    payload = "api/pic/program-feature/%Slug/%{Feature.LineNumber}?v=%{Data.Version}"
    source = 'method Probe()\n    val A = (F.H\n        ? "api/%Slug" : "")\n;\n'
    text = ("method Probe()\n"
            "    val Address = (Feature.HasImage\n"
            f'        ? "{payload}" : "")\n'
            ";\n")

    out, _ = wrap_code(text, source, limit=82)

    assert _lines(out)[2:4] == [f'        ? "{payload}"', '        : "")']


def test_a_comma_between_type_arguments_is_not_a_place():
    """Were it a place, the first piece would end with `Map<String,` - the last one that fits."""
    source = "method R(T: M<S, N>, O: A<S>): B\n;\n"
    text = "method Register(Table: Map<String, Number>, Options: Array<String>): Boolean\n;\n"

    out, _ = wrap_code(text, source, limit=40)

    assert _lines(out) == [
        "method Register(",
        "    Table: Map<String, Number>,",
        "    Options: Array<String>): Boolean",
        ";",
        "",
    ]


def test_a_new_line_never_starts_with_a_parenthesis():
    source = "method Probe()\n    E.F(O.D, T, (V) -> A(V))\n;\n"
    text = ("method Probe()\n"
            "    Editor.Field(Object.Description, Translated, (Value) -> Accept(Value))\n"
            ";\n")

    out, _ = wrap_code(text, source, limit=60)

    assert _lines(out)[1:3] == [
        "    Editor.Field(Object.Description,",
        "        Translated, (Value) -> Accept(Value))",
    ], "the later comma would leave the lambda opening a line"


def test_a_line_the_rule_reports_in_the_source_is_left_alone():
    text = ("method Probe()\n"
            "    val Answer = Serializer.Read(Response.Body, Type<Row>, Requests.Settings())\n"
            ";\n")
    assert wrap_code(text, text, limit=60) == (text, text)


def test_a_source_line_long_only_inside_a_string_is_not_long_on_purpose():
    """The rule does not report it, and the translation moved the overflow out of the string."""
    source = ("method Probe()\n"
              "    val A = (F.H\n"
              f'        ? "{"x" * 60}" : F.D)\n'
              ";\n")
    text = ("method Probe()\n"
            "    val Address = (Feature.HasImage\n"
            f'        ? "{"x" * 40}" : Fallback.DefaultValue)\n'
            ";\n")

    out, _ = wrap_code(text, source, limit=60)

    assert _lines(out)[2:4] == [f'        ? "{"x" * 40}"', "        : Fallback.DefaultValue)"]


def test_an_overflow_inside_a_string_literal_is_left_alone():
    source = 'method Probe()\n    Log.Write(A, "short")\n;\n'
    text = f'method Probe()\n    Journal.Write(Level, "{"x" * 70}")\n;\n'
    assert wrap_code(text, source, limit=60)[0] == text, "style/line-length does not report it"


def test_a_line_with_a_comment_after_the_code_keeps_its_shape():
    source = "method Probe()\n    val A = S.Read(B, T, C()) // note\n;\n"
    text = ("method Probe()\n"
            "    val Answer = Serializer.Read(Response.Body, Type<Row>, Requests.Settings()) // note\n"
            ";\n")
    assert wrap_code(text, source, limit=60)[0] == text


def test_a_line_inside_a_multiline_string_is_left_alone():
    source = 'method Probe()\n    val A = "<p>\n        a, b, c(d)</p>"\n;\n'
    text = ('method Probe()\n'
            '    val Markup = "<p>\n'
            '        first, second, third(fourth), fifth, sixth, seventh, eighth</p>"\n'
            ';\n')
    assert wrap_code(text, source, limit=40)[0] == text


def test_a_break_that_changes_the_parse_is_refused(monkeypatch):
    """`else if` on one line is a branch of the same statement, on two lines a nested one."""
    source = ("method Probe(Value: Number)\n"
              "    if Value == 1\n"
              "        Log.Write(1)\n"
              "    else if Value == S.M\n"
              "        Log.Write(2)\n"
              "    ;\n"
              ";\n")
    text = ("method Probe(Value: Number)\n"
            "    if Value == 1\n"
            "        Log.Write(1)\n"
            "    else if Value == SomeRatherLongConstantName.WithMember\n"
            "        Log.Write(2)\n"
            "    ;\n"
            ";\n")
    found = codewrap._places

    def with_a_wrong_place(toks, module):
        places = found(toks, module)
        keyword = next(tok for tok in toks if tok.line == 4 and tok.value == "if")
        places[keyword.start] = codewrap._Place(codewrap._LIST)
        return places

    monkeypatch.setattr(codewrap, "_places", with_a_wrong_place)
    assert wrap_code(text, source, limit=54)[0] == text


def test_a_short_line_and_a_query_file_are_not_touched():
    text = "method Probe()\n    val A = F(B, C)\n;\n"
    assert wrap_code(text, text, limit=60) == (text, text)
    long = "SELECT First, Second, Third, Fourth, Fifth FROM Catalog.Tasks AS Tasks\n"
    assert wrap_code(long, "SELECT A FROM B\n", limit=40, path=codewrap.Path("Tasks.xbql"))[0] == long
