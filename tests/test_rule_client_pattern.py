"""Opt-in checks for a client whose Pattern engine rejects Unicode class p."""
import pytest
from xbsl import engine
from xbsl.cli import discover

pytestmark = pytest.mark.needs_data

RULE = "code/client-pattern-unicode-class"


def run(tmp_path, expression, annotation="", environment="Клиент", english=False):
    yaml = ("ElementKind: CommonModule\nName: Probe\nEnvironment: " + environment + "\n") if english else ("ВидЭлемента: ОбщийМодуль\nИмя: Проба\nОкружение: " + environment + "\n")
    module = (annotation + "\n" if annotation else "") + ("method Check()\n    val X = " if english else "метод Проверить()\n    знч Х = ") + expression + "\n;\n"
    (tmp_path / "Probe.yaml").write_text(yaml, encoding="utf-8")
    (tmp_path / "Probe.xbsl").write_text(module, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={RULE})


@pytest.mark.parametrize("english", [False, True])
def test_literal_unicode_class_in_client_warns(tmp_path, english):
    expr = ('new Pattern' if english else 'новый Образец') + r'("[^\\p{L}]")'
    found = run(tmp_path, expr, environment="Client" if english else "Клиент", english=english)
    assert len(found) == 1
    assert found[0].rule_id == RULE
    assert found[0].severity.value == "warning"


@pytest.mark.parametrize("expr", [
    r'новый Образец("[^0-9A-Za-z_-]")',
    r'новый Образец("\\\\p{L}")',
    r'новый Образец("\\P{L}")',
    r'новый Образец(Шаблон)',
    r'новый Образец("\\p{L}" + Суффикс)',
    r'новый Образец("%{Шаблон}\\p{L}")',
    r'"\\p{L}"',
    r'Другой("\\p{L}")',
])
def test_unproven_or_non_pattern_text_is_silent(tmp_path, expr):
    assert run(tmp_path, expr) == []


@pytest.mark.parametrize("environment,annotation", [
    ("Сервер", ""), ("Клиент", "@НаСервере"),
    ("КлиентИСервер", "@НаСервере"),
])
def test_server_only_pattern_is_silent(tmp_path, environment, annotation):
    assert run(tmp_path, r'новый Образец("\\p{L}")', annotation, environment) == []


def test_shared_module_client_execution_warns(tmp_path):
    assert len(run(tmp_path, r'новый Образец("\\p{L}")', environment="КлиентИСервер")) == 1


def test_rule_is_opt_in_and_explains_why():
    rule = next(r for r in engine.RULES if r.id == RULE)
    assert not rule.enabled_by_default
    assert rule.off_reason_text and rule.off_reason_text != rule.off_reason



def test_form_module_is_a_client(tmp_path):
    run(tmp_path, r'новый Образец("\\p{N}")')
    (tmp_path / "Probe.yaml").write_text("ВидЭлемента: КомпонентИнтерфейса\nИмя: Проба\n", encoding="utf-8")
    assert len(engine.run(discover([str(tmp_path)]), select={RULE})) == 1


def test_missing_environment_is_undecided(tmp_path):
    run(tmp_path, r'новый Образец("\\p{L}")')
    (tmp_path / "Probe.yaml").unlink()
    assert engine.run(discover([str(tmp_path)]), select={RULE}) == []


def test_project_type_named_pattern_is_not_the_platform_type(tmp_path):
    run(tmp_path, r'новый Образец("\\p{L}")')
    module = tmp_path / "Probe.xbsl"
    module.write_text("структура Образец\n;\n" + module.read_text(encoding="utf-8"), encoding="utf-8")
    assert engine.run(discover([str(tmp_path)]), select={RULE}) == []


def test_warning_has_no_unsafe_ascii_autofix(tmp_path):
    found = run(tmp_path, r'новый Образец("\\p{L}")')
    assert found[0].fix is None



def test_other_project_element_named_pattern_is_silent(tmp_path):
    run(tmp_path, r'новый Образец("\\p{L}")')
    (tmp_path / "Pattern.yaml").write_text("ВидЭлемента: Справочник\nИмя: Образец\n", encoding="utf-8")
    assert engine.run(discover([str(tmp_path)]), select={RULE}) == []


def test_english_server_annotation_is_silent(tmp_path):
    assert run(tmp_path, r'new Pattern("\\p{L}")', "@OnServer", "Client", True) == []


def test_diagnostic_points_to_literal_in_file(tmp_path):
    found = run(tmp_path, r'новый Образец("\\p{L}")')
    line = (tmp_path / "Probe.xbsl").read_text(encoding="utf-8").splitlines()[found[0].line - 1]
    assert line[found[0].col - 1] == '"'



@pytest.mark.parametrize("name", ["[Неверное]", "{Ключ: Значение}"])
def test_nonstring_yaml_name_does_not_crash_explicit_selection(tmp_path, name):
    run(tmp_path, '"plain text"')
    (tmp_path / "Probe.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: " + name + "\nОкружение: Клиент\n", encoding="utf-8"
    )
    assert engine.run(discover([str(tmp_path)]), select={RULE}) == []
