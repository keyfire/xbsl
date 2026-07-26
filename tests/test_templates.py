"""Code templates: name parsing, pattern-to-snippet compilation, envelope reading."""

from __future__ import annotations

import json

import pytest

from xbsl import templates as tpl


def t(name: str, pattern: str = "x", **kw) -> tpl.Template:
    return tpl.Template(name=name, pattern=pattern, **kw)


# ------------------------------------------------------------------ name: abbreviation and title

def test_name_splits_into_trigger_and_title():
    x = t("мет[од] - Метод")
    assert (x.prefix, x.trigger, x.title) == ("мет", "метод", "Метод")


def test_name_without_brackets_needs_the_whole_trigger():
    x = t("Возврат - Возврат значения")
    assert (x.prefix, x.trigger, x.title) == ("Возврат", "Возврат", "Возврат значения")


def test_name_without_title_is_both_trigger_and_title():
    x = t("Возврат")
    assert (x.prefix, x.trigger, x.title) == ("Возврат", "Возврат", "Возврат")


def test_name_without_title_keeps_the_optional_tail():
    x = t("попыт[ка]")
    assert (x.prefix, x.trigger, x.title) == ("попыт", "попытка", "попытка")


def test_dash_inside_the_title_does_not_split_it_again():
    x = t("зпр[с] - Запрос - с параметром")
    assert (x.trigger, x.title) == ("зпрс", "Запрос - с параметром")


def test_match_is_case_insensitive_and_prefix_based():
    x = t("мет[од] - Метод")
    assert x.matches("мет") and x.matches("МЕТ") and x.matches("метод")
    assert not x.matches("етод")
    assert not x.matches("")


def test_category_is_the_description_without_the_leaf():
    assert t("а", description="/Стандартные/Управляющие/Если").category == "/Стандартные/Управляющие"
    assert t("а", description="").category == ""


# ------------------------------------------------------------------------------- variables

def test_variables_are_found_in_order_with_their_arguments():
    found = tpl.parse_variables('если ${Редактировать("Условие")} / ${Выбрать("а", "б")}')
    assert [(v.name, v.args) for v in found] == [
        ("Редактировать", ("Условие",)),
        ("Выбрать", ("а", "б")),
    ]


def test_quoted_argument_keeps_its_spaces_and_the_separator_does_not_leak():
    (var,) = tpl.parse_variables('${Выбрать("Имя метода", "Другое")}')
    assert var.args == ("Имя метода", "Другое")


def test_empty_and_absent_arguments_differ():
    assert tpl.parse_variables('${Редактировать("")}')[0].args == ("",)
    assert tpl.parse_variables("${Редактировать()}")[0].args == ()


def test_bare_argument_is_taken_as_is():
    (var,) = tpl.parse_variables("${ИмяОбъектаМетаданного(Справочник)}")
    assert var.args == ("Справочник",)


def test_brackets_inside_an_argument_survive():
    (var,) = tpl.parse_variables('${Редактировать("Массив(0)")}')
    assert var.args == ("Массив(0)",)


def test_unbalanced_variable_is_literal_text():
    assert tpl.parse_variables("${Редактировать(") == []


# ------------------------------------------------------------------------------- compilation

def test_edit_point_becomes_a_numbered_placeholder():
    assert tpl.expand('если ${Редактировать("Условие")}') == "если ${1:Условие}"


def test_empty_edit_point_becomes_a_bare_tab_stop():
    assert tpl.expand('${Редактировать("")}') == "${1}"


def test_tab_stops_are_numbered_by_appearance():
    out = tpl.expand('${Редактировать("а")} ${Редактировать("б")}')
    assert out == "${1:а} ${2:б}"


def test_choice_becomes_a_snippet_choice():
    assert tpl.expand('${Выбрать("а", "б")}') == "${1|а,б|}"


def test_choice_without_variants_degrades_to_an_edit_point():
    assert tpl.expand("${Выбрать()}") == "${1}"


def test_interpolation_dollar_of_xbsl_is_escaped():
    # "Здравствуйте, $Имя" - otherwise the editor would swallow $Имя as its own variable.
    assert tpl.expand('знч С = "Привет, $Имя"') == 'знч С = "Привет, \\$Имя"'


def test_collection_literal_braces_are_escaped():
    # the } closing the literal would close the tab stop.
    assert tpl.expand("знч С = {:}") == "знч С = {:\\}"


def test_backslash_is_escaped():
    assert tpl.expand('знч П = "C:\\\\Каталог"') == 'знч П = "C:\\\\\\\\Каталог"'


def test_comma_and_pipe_inside_a_variant_are_escaped():
    assert tpl.expand('${Выбрать("а,б", "в|г")}') == "${1|а\\,б,в\\|г|}"


def test_unknown_variable_becomes_an_edit_point_named_after_itself():
    assert tpl.expand("${НоваяПеременная()}") == "${1:НоваяПеременная}"


# ---------------------------------------------------------------- project objects in variables

def test_object_name_uses_the_resolver_variants():
    out = tpl.expand(
        "Справочник.${ИмяОбъектаМетаданного(Справочник)}",
        resolver=lambda name, kind: ["Абоненты", "Программы"],
    )
    assert out == "Справочник.${1|Абоненты,Программы|}"


def test_object_name_without_resolver_prompts_for_the_kind():
    assert tpl.expand("${ИмяОбъектаМетаданного(Справочник)}") == "${1:Справочник}"


def test_object_name_with_empty_project_prompts_instead_of_offering_nothing():
    # An empty choice can be neither picked nor filled by hand - an edit point is more useful.
    out = tpl.expand("${ИмяОбъектаМетаданного(Справочник)}", resolver=lambda name, kind: [])
    assert out == "${1:Справочник}"


def test_resolver_gets_the_variable_and_its_kind():
    seen: list[tuple[str, str]] = []
    tpl.expand(
        "${ПолноеИмяОбъектаМетаданного(\"ОбщаяФорма\")}",
        resolver=lambda name, kind: seen.append((name, kind)) or ["Ф"],
    )
    assert seen == [("ПолноеИмяОбъектаМетаданного", "ОбщаяФорма")]


# --------------------------------------------------------------------------------- preview

def test_preview_shows_the_code_without_snippet_syntax():
    out = tpl.preview('если ${Редактировать("Условие")}\n    ${Выбрать("а", "б")}\n;')
    assert out == "если Условие\n    а\n;"


# ------------------------------------------------------------------------------------- envelope

def _envelope(**over) -> str:
    item = {
        "type": tpl.TEMPLATE_TYPE,
        "name": "если - Если",
        "description": "/Стандартные/Управляющие/Если",
        "context": {
            "moduleEnvironments": [tpl.SERVER_ENVIRONMENT],
            "moduleContexts": [tpl.STATEMENT_CONTEXT],
        },
        "pattern": 'если ${Редактировать("")}\n;',
        "isAutoinsertable": False,
    }
    item.update(over)
    return json.dumps({"templates": [item]}, ensure_ascii=False)


def test_envelope_round_trips():
    (one,) = tpl.loads(_envelope())
    assert one.name == "если - Если"
    assert one.contexts == (tpl.STATEMENT_CONTEXT,)
    assert one.environments == (tpl.SERVER_ENVIRONMENT,)
    (again,) = tpl.loads(tpl.dumps([one]))
    assert again == one


def test_missing_context_means_everywhere():
    (one,) = tpl.loads(_envelope(context={}))
    assert one.contexts == tpl.CONTEXTS and one.environments == tpl.ENVIRONMENTS


def test_a_dump_of_edt_templates_is_rejected_by_its_contexts():
    """We share the format with 1С:EDT, but not the content: that is BSL code, which does not
    compile as XBSL.

    Silently accepting such an export would yield a set of templates inserting unusable code.
    """
    with pytest.raises(tpl.TemplateError, match="неизвестный контекст"):
        tpl.loads(_envelope(context={
            "moduleEnvironments": ["ON_SERVER_ENVIRONMENT"],
            "moduleContexts": ["CONDITIONAL_CONTEXT", "STATEMENT_CONTEXT"],
        }))


@pytest.mark.parametrize("over, part", [
    ({"name": ""}, "имя"),
    ({"pattern": ""}, "текст шаблона"),
    ({"context": {"moduleContexts": ["НЕТ_ТАКОГО"]}}, "неизвестный контекст"),
    ({"context": {"moduleEnvironments": ["НЕТ_ТАКОГО"]}}, "неизвестное окружение"),
])
def test_broken_template_names_the_record_and_the_reason(over, part):
    with pytest.raises(tpl.TemplateError) as e:
        tpl.loads(_envelope(**over))
    assert "№1" in str(e.value) and part in str(e.value)


def test_broken_json_is_reported_with_the_path():
    with pytest.raises(tpl.TemplateError, match="шаблонов.py"):
        tpl.loads("{не json", path="шаблонов.py")


def test_envelope_without_the_list_is_rejected():
    with pytest.raises(tpl.TemplateError, match="templates"):
        tpl.loads('{"иное": []}')


# ------------------------------------------------------------------------------- set and selection

def test_custom_template_overrides_the_builtin_one_by_name():
    builtin = [t("если - Если", "старый"), t("для - Для", "для")]
    custom = [t("если - Если", "новый")]
    out = tpl.merge(builtin, custom)
    assert [x.pattern for x in out] == ["новый", "для"]


def test_offered_filters_by_prefix_and_context():
    items = [
        t("метод - Метод", contexts=(tpl.DECLARATION_CONTEXT,)),
        t("мера - Мера", contexts=(tpl.STATEMENT_CONTEXT,)),
    ]
    one = (tpl.DECLARATION_CONTEXT,)
    assert [x.title for x in tpl.offered(items, typed="ме", contexts=one)] == ["Метод"]
    assert [x.title for x in tpl.offered(items, typed="мер", contexts=(tpl.STATEMENT_CONTEXT,))] == ["Мера"]
    assert [x.title for x in tpl.offered(items, contexts=(tpl.STATEMENT_CONTEXT,))] == ["Мера"]


def test_offered_outside_a_query_shows_both_code_contexts():
    # In unfinished code "inside a method" and "module level" cannot be told apart - show both.
    items = [
        t("метод - Метод", contexts=(tpl.DECLARATION_CONTEXT,)),
        t("если - Если", contexts=(tpl.STATEMENT_CONTEXT,)),
        t("выбрать - ВЫБРАТЬ", contexts=(tpl.QUERY_CONTEXT,)),
    ]
    assert [x.title for x in tpl.offered(items)] == ["Метод", "Если"]
    assert [x.title for x in tpl.offered(items, contexts=(tpl.QUERY_CONTEXT,))] == ["ВЫБРАТЬ"]


# --------------------------------------------------------------------------- the built-in set

def test_builtin_set_loads_and_is_not_empty():
    assert len(tpl.load_builtin()) > 0


def test_builtin_names_are_unique():
    # The name is the merge key with the user file: a duplicate would make overriding unpredictable.
    # Abbreviations, however, repeat deliberately ("мет" leads to all the method flavors).
    seen: dict[str, str] = {}
    for x in tpl.load_builtin():
        assert x.name not in seen, f"имя '{x.name}' повторяется"
        seen[x.name] = x.name


def test_builtin_patterns_compile_into_snippets():
    for x in tpl.load_builtin():
        assert tpl.expand(x.pattern), x.name


def test_builtin_templates_are_described_by_a_category_path():
    for x in tpl.load_builtin():
        assert x.description.startswith("/"), x.name
        assert x.category, x.name


def _as_module(x: tpl.Template) -> str:
    """The template as module source: statements wrapped in a method, query ones in a literal."""
    code = tpl.preview(x.pattern)
    if tpl.DECLARATION_CONTEXT in x.contexts:
        return code
    if tpl.QUERY_CONTEXT in x.contexts:
        body = "\n".join("        " + line for line in code.split("\n"))
        return f"метод Проба()\n    знч Р = Запрос{{\n{body}\n    }}.Выполнить()\n;"
    body = "\n".join(("    " + line) if line.strip() else line for line in code.split("\n"))
    return f"метод Проба()\n{body}\n;"


def _parse_errors(text: str) -> list:
    from xbsl import engine

    return engine.run_sources(
        [engine.load_text("Проба.xbsl", text)], select={"code/parse-error"}, scopes=("file",),
    )


@pytest.mark.needs_data
def test_builtin_patterns_parse_as_xbsl():
    """An expanded template must be code the platform parser accepts.

    This is the only defense against idioms from 1С:Предприятие ("Тогда", "КонецЕсли",
    "умолчание" as a case branch): the template inserts such code silently, and the error
    would only surface at compile time.
    """
    broken = []
    for x in tpl.load_builtin():
        if _parse_errors(_as_module(x)):
            broken.append(x.name)
    assert not broken


@pytest.mark.needs_data
def test_the_parse_check_actually_catches_a_broken_template():
    # A false-zero control: the check above is green not because the parser is always silent.
    assert _parse_errors(_as_module(tpl.Template(
        name="плохой - Плохой", pattern='если ${Редактировать("Х")}', contexts=(tpl.STATEMENT_CONTEXT,),
    )))
