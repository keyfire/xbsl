"""A rule says out loud the values it judges by.

Before this the threshold was a constant in the sources and nothing else: `--list-rules` and
the MCP listing gave the id, the title, the tier, the severity and the "on by default" flag,
so the only way to learn the number was to rewrite the code around a guess and re-run the
linter over the whole project - a body cut to six lines was reported, the same body cut to
four was not, and two full runs bought one number that the tool already knew.

The parameter is declared where it is used (`rule_param` returns the value the constant takes),
so the listing and the rule cannot drift apart the way a hand-kept table of thresholds would.
"""

from __future__ import annotations

import pytest

from xbsl import cli, engine, environment, i18n


@pytest.fixture(autouse=True)
def _restore_registry():
    """The tests declare parameters of their own; the registry is put back afterwards."""
    saved = list(engine.PARAMS)
    yield
    engine.PARAMS[:] = saved


def _own():
    """Parameters of the engine's OWN rules - a plugin answers for its texts itself."""
    known = {
        r.id for r in engine.RULES if getattr(r.func, "__module__", "").startswith("xbsl.")
    }
    return [p for p in engine.PARAMS if p.rule_id in known]


def test_there_are_declared_parameters():
    """Without this the rest of the file would pass on an empty set."""
    assert _own(), "ни одно правило не объявило параметров - проверьте загрузку реестра"


def test_every_parameter_belongs_to_a_registered_rule():
    """A parameter of a rule that does not exist would be listed nowhere and read never."""
    known = {r.id for r in engine.RULES}
    orphans = [(p.rule_id, p.name) for p in engine.PARAMS if p.rule_id not in known]
    assert not orphans, "параметры без правила: %s" % orphans


def test_parameter_names_are_unique_within_a_rule():
    seen = [(p.rule_id, p.name) for p in engine.PARAMS]
    assert len(seen) == len(set(seen)), "параметр объявлен дважды: %s" % seen


@pytest.mark.parametrize("lang", ("ru", "en"))
def test_every_parameter_explains_itself_in_both_languages(lang):
    """A number without a sentence is another riddle - the catalog must answer in both."""
    i18n.set_lang(lang)
    try:
        silent = [(p.rule_id, p.name) for p in _own() if not p.doc.strip()]
        assert not silent, "параметры без описания: %s" % silent
        bare = [(p.rule_id, p.name) for p in _own() if p.doc == p.doc_key]
        assert not bare, "описание не переведено, в каталоге нет записи: %s" % bare
    finally:
        i18n.set_lang("ru")


def test_the_duplicate_body_threshold_is_the_one_the_rule_uses():
    """The very number that cost two full runs to find, taken from the rule's own constant."""
    from xbsl.rules import duplicate_bodies

    param = next(
        p for p in engine.PARAMS
        if (p.rule_id, p.name) == ("code/duplicate-method-body", "min-lines")
    )
    assert param.value == duplicate_bodies.MIN_LINES
    assert param.default == 5


def test_parameters_reach_the_machine_readable_listing():
    """MCP and the editor read as_dict() - the value has to travel there too."""
    rule = next(r for r in engine.RULES if r.id == "code/duplicate-method-body")
    param = rule.as_dict()["params"][0]
    assert param["name"] == "min-lines"
    assert param["value"] == 5 and param["default"] == 5
    assert param["env"] == "XBSL_CODE_DUPLICATE_METHOD_BODY_MIN_LINES"
    assert param["doc"].strip()


def test_a_rule_without_parameters_carries_no_empty_list():
    """Two hundred empty lists in one answer cost an agent's context and buy nothing."""
    rule = next(r for r in engine.RULES if not r.params)
    assert "params" not in rule.as_dict()


def test_env_name_is_derived_from_the_rule_and_the_parameter():
    """Derived, not spelled out: a hand-written name drifts from the rule it belongs to."""
    assert engine.param_env("code/duplicate-method-body", "min-lines") == (
        "XBSL_CODE_DUPLICATE_METHOD_BODY_MIN_LINES"
    )
    assert engine.param_env("yaml/hint-too-long", "limit") == "XBSL_YAML_HINT_TOO_LONG_LIMIT"


def test_environment_variable_overrides_the_value_and_the_default_still_shows(monkeypatch):
    monkeypatch.setenv("XBSL_WHITESPACE_TRAILING_PROBE", "9")
    value = engine.rule_param("whitespace/trailing", "probe", 4, "проба")
    assert value == 9
    param = engine.params_of("whitespace/trailing")[0]
    assert param.value == 9 and param.default == 4 and param.overridden


def test_a_broken_environment_value_keeps_the_default_and_says_so(monkeypatch, capsys):
    """A silently ignored override is a typo nobody notices - it is said out loud instead."""
    monkeypatch.setenv("XBSL_WHITESPACE_TRAILING_PROBE", "пять")
    value = engine.rule_param("whitespace/trailing", "probe", 4, "проба")
    err = capsys.readouterr().err
    assert value == 4
    assert "XBSL_WHITESPACE_TRAILING_PROBE" in err and "пять" in err


def test_redeclaration_replaces_the_record(monkeypatch):
    """A reloaded rule module (or a plugin taking a core rule over) must not double it."""
    engine.rule_param("whitespace/trailing", "probe", 4, "проба")
    monkeypatch.setenv("XBSL_WHITESPACE_TRAILING_PROBE", "7")
    engine.rule_param("whitespace/trailing", "probe", 4, "проба")
    assert [p.value for p in engine.params_of("whitespace/trailing")] == [7]


def test_a_run_names_the_parameters_it_moved_off_the_defaults(monkeypatch):
    """A threshold changed by the environment changes the findings - the report says so."""
    monkeypatch.setenv("XBSL_WHITESPACE_TRAILING_PROBE", "9")
    engine.rule_param("whitespace/trailing", "probe", 4, "проба")
    rule = next(r for r in engine.RULES if r.id == "whitespace/trailing")

    info = environment.provenance([rule])

    assert info["params"] == [{
        "rule": "whitespace/trailing", "name": "probe", "value": 9, "default": 4,
        "env": "XBSL_WHITESPACE_TRAILING_PROBE", "doc": "проба",
    }]
    assert "whitespace/trailing probe = 9 (4)" in environment.provenance_note(info)


def test_a_run_on_the_defaults_says_nothing_about_parameters():
    """A line of zeros in every report teaches nobody anything."""
    assert "params" not in environment.provenance(list(engine.RULES))


@pytest.mark.needs_data
def test_list_rules_narrows_to_the_rule_asked_about(capsys):
    """Asking about one threshold must not mean reading two hundred rules to find it."""
    code = cli.main(["--list-rules", "--select", "code/duplicate-method-body"])
    out = capsys.readouterr().out

    assert code == 0
    assert out.count("code/duplicate-method-body") == 1
    assert "min-lines = 5" in out and "XBSL_CODE_DUPLICATE_METHOD_BODY_MIN_LINES" in out
    assert "whitespace/trailing" not in out


@pytest.mark.needs_data
def test_list_rules_without_a_selection_still_lists_everything(capsys):
    cli.main(["--list-rules"])
    out = capsys.readouterr().out
    assert out.count("\n") >= len(engine.RULES)
    assert "code/duplicate-method-body" in out and "whitespace/trailing" in out


@pytest.mark.needs_data
def test_an_empty_selection_says_so_instead_of_claiming_an_empty_registry(capsys):
    """"No rules registered yet" sent the reader looking for a broken installation."""
    cli.main(["--list-rules", "--select", "нет-такого-правила"])
    out = capsys.readouterr().out
    assert "нет-такого-правила" in out
    assert "не зарегистрированы" not in out
