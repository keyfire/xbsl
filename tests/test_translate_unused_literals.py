"""Literal entries the translating pass still asks for are never orphans, and `--strict` sees
a visible text without one.

The orphan pass used to read a literal only between double quotes of the raw text. That missed
two places the translating pass reads a literal from. A yaml value the metamodel types as a text
a person reads - a presentation, a presentation template - is keyed by the scalar itself, quoted
or not. A string standing inside an interpolation of another string was cut in two by the first
inner quote. `--unused` offered such live entries for removal, and `--prune` took them out: the
English tree then showed Russian presentations, and a group name read back by `Group("...")`
took another spelling than the pattern that declared it.

`--strict` did not catch the loss: a literal is counted apart from the coverage, because the pass
cannot tell data from a message in code. A yaml text taken through the literals plane is known to
be read by a person, so a gap there now fails the gate.
"""

import dataclasses
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from xbsl.translation import cli
from xbsl.translation import dictionary as dictionary_module
from xbsl.translation import entries
from xbsl.translation import project as project_module

pytestmark = pytest.mark.needs_data


_PRIVILEGE = (
    "ВидЭлемента: ПравоНаДействие\n"
    "Ид: 0190c7a0-0000-7000-8000-000000000001\n"
    "Имя: ПравоНаВыгрузку\n"
    "Представление: {presentation}\n"
)

_EVENT = (
    "ВидЭлемента: СобытиеЖурналаСобытий\n"
    "Ид: 0190c7a0-0000-7000-8000-000000000002\n"
    "Имя: ВыгрузкаОтчета\n"
    "ШаблонПредставления: Отчёт %{Номер} выгружен в архив.\n"
    "Свойства:\n"
    "    -\n"
    "        Ид: 0190c7a0-0000-7000-8000-000000000003\n"
    "        Имя: Номер\n"
    "        Тип: Строка\n"
)

_MODULE_YAML = (
    "ВидЭлемента: ОбщийМодуль\n"
    "Ид: 0190c7a0-0000-7000-8000-000000000004\n"
    "Имя: Итоги\n"
)

_MODULE = (
    "метод ИтогПоГруппе(Текст: Строка): Строка\n"
    "    знч Вхождения = новый Образец(\"[0-9]+\").НайтиСовпадения(Текст)\n"
    "    возврат \"Итог: %{Вхождения[0].Группа(\"Разряд\") ?? \"\"}\"\n"
    ";\n"
)

_TOKENS = (
    "tokens:\n"
    "    ПравоНаВыгрузку: ExportPrivilege\n"
    "    ВыгрузкаОтчета: ReportExport\n"
    "    Номер: Number\n"
    "    Итоги: Totals\n"
    "    ИтогПоГруппе: TotalByGroup\n"
    "    Текст: Text\n"
    "    Вхождения: Occurrences\n"
)

_LITERALS = (
    "literals:\n"
    "    \"Выгрузка отчётов\": \"Report export\"\n"
    "    \"Отчёт %{Номер} выгружен в архив.\": \"Report %{Номер} is exported to the archive.\"\n"
    "    \"Разряд\": \"Rank\"\n"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _shapes(tmp_path: Path, extra_literals: str = "",
            presentation: str = "Выгрузка отчётов") -> tuple[Path, Path]:
    """A project with every shape the literals plane reads, and a dictionary that covers it."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "ПравоНаВыгрузку.yaml", _PRIVILEGE.format(presentation=presentation))
    _write(root / "ВыгрузкаОтчета.yaml", _EVENT)
    _write(root / "Итоги.yaml", _MODULE_YAML)
    _write(root / "Итоги.xbsl", _MODULE)
    dictionary = tmp_path / "dictionary.yaml"
    _write(dictionary, "version: 1\nlanguage: en\n" + _TOKENS + _LITERALS + extra_literals)
    return root, dictionary


def _orphans(root: Path, dictionary: Path) -> set[str]:
    loaded = dictionary_module.load(dictionary)
    return {row.key for row in entries.unused_entries(root, dictionary, loaded)
            if row.kind == "literal"}


def _run(capsys, args: list[str]) -> tuple[int, list[str]]:
    code = cli.cli_main(args + ["--lang", "ru"])
    return code, capsys.readouterr().out.rstrip("\n").splitlines()


# --- the orphan reading ----------------------------------------------------------------------


@pytest.mark.parametrize("written", [
    "Выгрузка отчётов",
    "'Выгрузка отчётов'",
    "\"Выгрузка отчётов\"",
])
def test_a_presentation_is_live_however_its_scalar_is_quoted(tmp_path: Path, written: str):
    root, dictionary = _shapes(tmp_path, presentation=written)

    assert "Выгрузка отчётов" not in _orphans(root, dictionary)


def test_a_presentation_template_is_live(tmp_path: Path):
    root, dictionary = _shapes(tmp_path)

    assert "Отчёт %{Номер} выгружен в архив." not in _orphans(root, dictionary)


def test_a_group_name_inside_an_interpolation_is_live(tmp_path: Path):
    """The pass reads the inner string whole; the first inner quote used to cut it apart."""
    root, dictionary = _shapes(tmp_path)

    assert "Разряд" not in _orphans(root, dictionary)


def test_a_string_nested_in_an_interpolation_is_live(tmp_path: Path):
    root, dictionary = _shapes(tmp_path, extra_literals="    \"Остаток\": \"Balance\"\n")
    _write(root / "Итоги.xbsl", _MODULE + (
        "\nметод Подпись(Данные: Соответствие<Строка, Строка>): Строка\n"
        "    возврат \"%{Данные[\"Остаток\"] ?? \"\"} шт.\"\n"
        ";\n"
    ))

    assert "Остаток" not in _orphans(root, dictionary)


def test_a_string_inside_an_expression_of_a_quoted_yaml_value_is_live(tmp_path: Path):
    """A value holding `: ` has to be quoted, and inside a double-quoted scalar the inner quotes
    are escaped: the raw text holds no literal of its own. The pass reads the expression from
    the decoded value."""
    root, dictionary = _shapes(tmp_path, extra_literals="    \"Итог: всего\": \"Total: all\"\n")
    _write(root / "ПанельИтогов.yaml",
           "ВидЭлемента: КомпонентИнтерфейса\n"
           "Ид: 0190c7a0-0000-7000-8000-000000000006\n"
           "Имя: ПанельИтогов\n"
           "Содержимое:\n"
           "    Тип: Надпись\n"
           "    Значение: \"=\\\"Итог: всего\\\"\"\n")

    assert "Итог: всего" not in _orphans(root, dictionary)


def test_a_group_name_declared_only_by_a_pattern_is_live(tmp_path: Path):
    root, dictionary = _shapes(tmp_path, extra_literals="    \"Код\": \"Code\"\n")
    _write(root / "Итоги.xbsl", _MODULE.replace(
        "новый Образец(\"[0-9]+\")", "новый Образец('(?<Код>[0-9]+)')"))

    assert "Код" not in _orphans(root, dictionary)


def test_a_group_name_declared_inside_a_translation_is_live(tmp_path: Path):
    """A literal named whole is replaced by its translation, and the pass then reads the
    interpolations of the TRANSLATION: a pattern standing there declares a group the literals
    plane is asked about, though no source spells it."""
    key = "Совпадений: %{Образец('(?<Число>[0-9]+)').НайтиСовпадения(Текст).Количество()}"
    value = "Matches: %{Образец('(?<Цифры>[0-9]+)').НайтиСовпадения(Текст).Количество()}"
    root, dictionary = _shapes(tmp_path, extra_literals=(
        f"    \"{key}\": \"{value}\"\n"
        "    \"Цифры\": \"Digits\"\n"
    ))
    _write(root / "Итоги.xbsl", _MODULE + (
        "\nметод Совпадений(Текст: Строка): Строка\n"
        f"    возврат \"{key}\"\n"
        ";\n"
    ))
    recording = _recording(dictionary_module.load(dictionary))
    project_module.translate_project(root, recording, None)

    assert "Цифры" in recording.asked
    assert "Цифры" not in _orphans(root, dictionary)


def test_a_literal_nothing_asks_for_is_still_an_orphan(tmp_path: Path):
    """The control: a text no source carries any more is listed, whatever shape it had."""
    root, dictionary = _shapes(
        tmp_path,
        extra_literals="    \"Выгрузка отчётов за месяц\": \"Monthly report export\"\n"
                       "    \"Отчёт выгружен.\": \"The report is exported.\"\n",
    )

    orphans = _orphans(root, dictionary)

    assert orphans == {"Выгрузка отчётов за месяц", "Отчёт выгружен."}


def test_a_literal_spelled_like_a_yaml_name_is_still_an_orphan(tmp_path: Path):
    """The second control: only the texts the walk takes through the literals plane count.

    A name of the yaml - an element, a property, a component - is never asked about as a
    literal, so a pair keyed by the same word is dead however often the word stands there.
    """
    root, dictionary = _shapes(tmp_path, extra_literals="    \"ВыгрузкаОтчета\": \"ReportExport\"\n"
                                                        "    \"Номер\": \"Number\"\n")

    orphans = _orphans(root, dictionary)

    assert {"ВыгрузкаОтчета", "Номер"} <= orphans


# --- consistency with the translating pass ---------------------------------------------------


class _Recording(dictionary_module.Dictionary):
    """A dictionary that remembers every literal the pass asked it for."""

    asked: set

    def literal(self, text):
        self.asked.add(text)
        return super().literal(text)


def _recording(loaded) -> _Recording:
    fields = {field.name: getattr(loaded, field.name) for field in dataclasses.fields(loaded)}
    out = _Recording(**fields)
    out.asked = set()
    return out


def _tree(root: Path, dictionary: Path, out: Path) -> dict[str, bytes]:
    project_module.translate_project(root, dictionary_module.load(dictionary), out)
    return {path.relative_to(out).as_posix(): path.read_bytes()
            for path in sorted(out.rglob("*")) if path.is_file()}


def test_every_literal_the_pass_asks_for_is_read_as_live(tmp_path: Path):
    """The drift guard: the orphan reading is a second reading, and it must cover the first."""
    root, dictionary = _shapes(tmp_path, extra_literals="    \"Прежний текст\": \"Former text\"\n")
    loaded = dictionary_module.load(dictionary)
    recording = _recording(loaded)

    project_module.translate_project(root, recording, None)
    used = recording.asked & set(loaded.literals)
    orphans = _orphans(root, dictionary)

    assert used >= {"Выгрузка отчётов", "Отчёт %{Номер} выгружен в архив.", "Разряд"}
    assert not used & orphans
    assert orphans == {"Прежний текст"}


def test_pruning_every_candidate_leaves_the_translated_tree_byte_identical(tmp_path: Path, capsys):
    root, dictionary = _shapes(tmp_path, extra_literals="    \"Прежний текст\": \"Former text\"\n")
    before = _tree(root, dictionary, tmp_path / "before")

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--prune"])

    assert any("снято пар: 1" in line for line in lines), lines
    assert "Прежний текст" not in dictionary.read_text(encoding="utf-8")
    assert _tree(root, dictionary, tmp_path / "after") == before


def test_prune_on_a_clean_dictionary_changes_nothing(tmp_path: Path, capsys):
    root, dictionary = _shapes(tmp_path)
    before = dictionary.read_bytes()

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--prune"])

    assert any("пар без места в проекте нет" in line for line in lines), lines
    assert dictionary.read_bytes() == before


# --- the orphans of one change ---------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=str(repo), capture_output=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return done.stdout.decode("utf-8", "replace")


def test_a_removed_presentation_is_an_orphan_of_the_change_that_removed_it(tmp_path: Path):
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    root, dictionary = _shapes(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    (root / "ПравоНаВыгрузку.yaml").unlink()
    loaded = dictionary_module.load(dictionary)

    removed = entries.removed_surfaces(root, base)
    keys = {row.key for row in entries.unused_entries(root, dictionary, loaded, removed)}

    assert "Выгрузка отчётов" in keys
    assert "Разряд" not in keys and "Отчёт %{Номер} выгружен в архив." not in keys


# --- the strict gate -------------------------------------------------------------------------


def _visible_only(tmp_path: Path, shape: str, literals: str = "") -> tuple[Path, Path]:
    """One yaml text a person reads, every name covered - the literal is the only question."""
    root = tmp_path / "Acme" / "Demo"
    if shape == "presentation":
        _write(root / "ПравоНаВыгрузку.yaml", _PRIVILEGE.format(presentation="Выгрузка отчётов"))
    else:
        _write(root / "ВыгрузкаОтчета.yaml", _EVENT)
    dictionary = tmp_path / "dictionary.yaml"
    _write(dictionary, "version: 1\nlanguage: en\n" + _TOKENS + literals)
    return root, dictionary


@pytest.mark.parametrize("shape", ["presentation", "template"])
def test_a_visible_text_without_an_entry_fails_strict(tmp_path: Path, capsys, shape: str):
    root, dictionary = _visible_only(tmp_path, shape)

    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--strict"])

    assert code == 1, lines
    assert lines[-1] == "НЕ ГОТОВО: токенов 0, фраз 0; видимых литералов без пары 1"


@pytest.mark.parametrize("shape", ["presentation", "template"])
def test_a_visible_text_with_its_entry_is_ready(tmp_path: Path, capsys, shape: str):
    root, dictionary = _visible_only(tmp_path, shape, _LITERALS)

    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--strict"])

    assert code == 0, lines
    assert lines[-1] == "ГОТОВО"


_PANEL = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 0190c7a0-0000-7000-8000-000000000007\n"
    "Имя: ПанельИтогов\n"
    "Содержимое:\n"
    "    Тип: Надпись\n"
    "    {key}: {value}\n"
)

_PANEL_TOKENS = "    ПанельИтогов: TotalsPanel\n    Сумма: Amount\n"


@pytest.mark.parametrize("key", ["Значение", "Заголовок"])
def test_an_expression_value_takes_its_string_from_the_literals_plane(
        tmp_path: Path, capsys, key: str):
    """An `=` value is code even when its string carries a substitution: the string is keyed
    by the text between its quotes, and the entry an author writes for it applies. Read as a
    template, the value was keyed with its `=` and its quotes - a key the dictionary refuses to
    load - so no entry could cover it, and the strict gate failed for good."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "ПанельИтогов.yaml", _PANEL.format(key=key, value="=\"Итого %{Сумма} руб\""))
    dictionary = tmp_path / "dictionary.yaml"
    _write(dictionary, "version: 1\nlanguage: en\ntokens:\n" + _PANEL_TOKENS
           + "literals:\n    \"Итого %{Сумма} руб\": \"Total %{Сумма} rub\"\n")

    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--strict"])
    tree = b"".join(_tree(root, dictionary, tmp_path / "out").values()).decode("utf-8")

    assert code == 0, lines
    assert lines[-1] == "ГОТОВО"
    assert any(line.endswith(": =\"Total %{Amount} rub\"") for line in tree.splitlines()), tree


@pytest.mark.parametrize("shape", ["expression", "component text", "description"])
def test_a_text_the_metamodel_does_not_type_localizable_stays_apart_from_strict(
        tmp_path: Path, capsys, shape: str):
    """The other texts the literals plane reads are listed as gaps and do not fail the gate: an
    `=` expression is code, the text of an interface component is not typed `Localizable` by
    the metamodel, and a `Description` is documentation even when it carries a substitution."""
    root = tmp_path / "Acme" / "Demo"
    if shape == "description":
        _write(root / "ВыгрузкаОтчета.yaml",
               _EVENT + "Описание: Пишется при выгрузке отчёта %{Номер} в архив.\n")
        tokens, literals = _TOKENS, _LITERALS
    else:
        value = "=\"Итого %{Сумма} руб\"" if shape == "expression" else "Итого %{Сумма} руб"
        _write(root / "ПанельИтогов.yaml", _PANEL.format(key="Заголовок", value=value))
        tokens, literals = "tokens:\n" + _PANEL_TOKENS, ""
    dictionary = tmp_path / "dictionary.yaml"
    _write(dictionary, "version: 1\nlanguage: en\n" + tokens + literals)

    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--strict",
                                "--format", "json"])
    report = json.loads("\n".join(lines))

    assert code == 0, report["missing_visible_literals"]
    assert report["ready"] is True
    assert report["totals"]["missing_literals"] == 1
    assert report["totals"]["missing_visible_literals"] == 0


def test_a_code_literal_without_an_entry_stays_apart_from_strict(tmp_path: Path, capsys):
    """The control: in code the pass cannot tell data from a message, so the gate does not ask."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Итоги.yaml", _MODULE_YAML)
    _write(root / "Итоги.xbsl", "метод ИтогПоГруппе(Текст: Строка): Строка\n"
                                "    возврат Текст + \"руб.\"\n;\n")
    dictionary = tmp_path / "dictionary.yaml"
    _write(dictionary, "version: 1\nlanguage: en\n" + _TOKENS)

    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--strict",
                                "--format", "json"])
    report = json.loads("\n".join(lines))

    assert code == 0
    assert report["ready"] is True
    assert report["totals"]["missing_literals"] == 1
    assert report["totals"]["missing_visible_literals"] == 0


def test_the_json_report_counts_the_visible_gap(tmp_path: Path, capsys):
    root, dictionary = _visible_only(tmp_path, "presentation")

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--format", "json"])
    report = json.loads("\n".join(lines))

    assert report["ready"] is False
    assert report["totals"]["missing_visible_literals"] == 1


def test_translate_status_counts_the_visible_gap(mcp_module, tmp_path: Path):
    root, dictionary = _visible_only(tmp_path, "presentation")
    (root / "Проект.yaml").write_text(
        "ВидЭлемента: Проект\nИд: 0190c7a0-0000-7000-8000-000000000005\n"
        "Имя: Demo\nПоставщик: Acme\n", encoding="utf-8")
    folder = root / dictionary_module.DICTIONARY_DIR
    folder.mkdir()
    shutil.copy(dictionary, folder / "010-names.yaml")

    status = mcp_module.translate_status(str(root))

    assert status["missing_visible_literals"] == 1
