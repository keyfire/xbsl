"""Dictionary entries the PLATFORM answers itself - the workarounds nobody can see.

The mirror of the shadow report: there an entry the platform OVERRULES, judged as the defect
it is; here one it merely REPEATS. Such an entry breaks nothing - the tree comes out word for
word the same without it - and that is what makes it dangerous: it answers in place of the
platform data, so a hole in the data or in this engine stays hidden behind it. A live project
spelled the languages of its own descriptor that way, with one pair `Русский: Russian`, and
the half-translated enumeration behind it was found by a test on an empty dictionary, never
by the project.

The verdict is evidence from the pass, and the direction of its error is the point: an entry
is listed only when EVERY place it answered would have come out the same without it, so a
pair that carries one position of its own is never called redundant - which is the mistake
`--prune` would act on.
"""

import json
from pathlib import Path

import pytest

from xbsl import engine, i18n
from xbsl.translation import cli, dictionary as dictionary_module, entries, project
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.reporting import FileReport

pytestmark = pytest.mark.needs_data


@pytest.fixture(autouse=True)
def _ru_lang():
    i18n.set_lang("ru")
    yield
    i18n.set_lang(None)


def _project(tmp_path: Path, tokens: str = "", module: str = "") -> tuple[Path, Path]:
    """A project whose descriptor lists the languages, plus a dictionary that covers it.

    The descriptor is the case the whole verdict came from: both language properties are the
    platform's own enumeration, and no project should have to spell them.
    """
    root = tmp_path / "Acme" / "Demo"
    root.mkdir(parents=True)
    (root / "Проект.yaml").write_text(
        "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\nИмя: Задачник\nПоставщик: Acme\n"
        "ЯзыкиЛокализации: [Русский, Английский]\nЯзыкПоУмолчанию: Русский\n",
        encoding="utf-8",
    )
    (root / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\nИмя: Задачи\n"
        "Реквизиты:\n    -\n        Имя: Шаг\n        Тип: Строка\n",
        encoding="utf-8",
    )
    if module:
        (root / "Модуль.xbsl").write_text(module, encoding="utf-8")
    dictionary = tmp_path / "dictionary.yaml"
    dictionary.write_text(
        "version: 1\nlanguage: en\ntokens:\n"
        "    Задачник: TaskBook\n"
        "    Задачи: Tasks\n"
        "    Шаг: Step\n"
        "    Модуль: Module\n"
        f"{tokens}",
        encoding="utf-8",
    )
    return root, dictionary


def _echoed(root: Path, dictionary: Path) -> dict[str, str]:
    loaded = dictionary_module.load(dictionary)
    return project.translate_project(root, loaded, None).echoed


def _run(capsys, args: list[str]) -> tuple[int, list[str]]:
    code = cli.cli_main(args + ["--lang", "ru"])
    return code, capsys.readouterr().out.rstrip("\n").splitlines()


def test_an_entry_that_repeats_the_platform_is_named(tmp_path: Path):
    """The language of the descriptor is a value of the platform's own enumeration, and the
    string type its own name: neither entry answers anything the platform would not."""
    root, dictionary = _project(tmp_path, "    Русский: Russian\n    Строка: String\n")

    assert _echoed(root, dictionary) == {"Русский": "Russian", "Строка": "String"}


def test_an_entry_needed_in_one_place_is_not_named(tmp_path: Path):
    """The same word standing where no platform table reaches: the entry carries that place,
    so it is not redundant anywhere - the direction of the error that matters."""
    root, dictionary = _project(
        tmp_path,
        "    Русский: Russian\n    Строка: String\n    Пуск: Start\n    Метка: Mark\n",
        module="метод Пуск()\n    пер Метка = Русский\n;\n",
    )

    assert _echoed(root, dictionary) == {"Строка": "String"}


def test_a_name_the_project_declares_is_never_named(tmp_path: Path):
    """A project may name its own thing after a platform word, and then the entry is what
    keeps the declaration and its uses together: the platform is gated off there."""
    root, dictionary = _project(tmp_path, "    Строка: String\n")
    (root / "Строка.yaml").write_text(
        "ВидЭлемента: Справочник\nИмя: Строка\n", encoding="utf-8",
    )

    assert _echoed(root, dictionary) == {}


def test_an_entry_the_project_never_uses_is_not_named(tmp_path: Path):
    """That is the ORPHAN question, and --unused answers it: this verdict speaks only of
    entries the pass actually resolved, so the two lists never claim each other's rows."""
    root, dictionary = _project(tmp_path, "    Строка: String\n    Секунда: Second\n")

    assert set(_echoed(root, dictionary)) == {"Строка"}
    unused = entries.unused_entries(root, dictionary, dictionary_module.load(dictionary))
    orphans = {entry.key for entry in unused}
    assert "Секунда" in orphans and "Строка" not in orphans


#: The module of the dictionary-defects test, where a member is read off a receiver whose
#: type is INFERRED through a static call of a platform type - the fork this verdict shares
#: with the shadow report.
_EVENT_MODULE = (
    "метод Проба(Запрос: Строка)\n"
    "    исп Поиск = ЖурналСобытий.Найти(ДатаНачала = Запрос)\n"
    "    пока Поиск.Следующий()\n"
    "        знч Событие = Поиск.Событие\n"
    "        знч Важность = Событие.Важность\n"
    "    ;\n"
    ";\n"
)


def _module(tokens: dict):
    source = engine.load_text("Проба.xbsl", _EVENT_MODULE)
    report = FileReport(path="Проба.xbsl")
    resolver = Resolver(dictionary_module.Dictionary(tokens=dict(tokens)))
    return translate_code(source, resolver, report), report, resolver


def test_the_two_halves_of_one_fork():
    """Where the platform's own spelling of a member wins, the entry beside it is judged both
    ways by one `if`: a word the platform spells NOWHERE is the defect it always was, and one
    it spells exactly so is an echo of the platform and nothing else."""
    tokens = {"Проба": "Probe", "Запрос": "Query"}

    _out, shadowed, resolver = _module({**tokens, "Важность": "Severity"})
    assert set(shadowed.shadows) == {"Важность"} and not resolver.echoes()

    _out, report, resolver = _module({**tokens, "Важность": "Importance"})
    assert not report.shadows and resolver.echoes() == {"Важность": "Importance"}


def test_the_cli_lists_them_with_the_file_and_line(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    Русский: Russian\n    Строка: String\n")

    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--redundant"])

    assert code == 0
    assert lines[0] == "пар, на которые платформа отвечает сама: показано 2 из 2"
    assert any(line.strip().startswith("token   Русский  ->  Russian") and
               line.rstrip().endswith("dictionary.yaml:8") for line in lines), lines


def test_the_report_says_the_number_without_being_asked(tmp_path: Path, capsys):
    """Nobody looks for a workaround they cannot see - so the plain report carries the count
    and names the flag that lists them."""
    root, dictionary = _project(tmp_path, "    Русский: Russian\n")

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary)])

    assert "платформа сама отвечает на пар словаря: 1 (список – --redundant)" in lines


def test_the_json_report_carries_the_entries(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    Русский: Russian\n")

    _code, lines = _run(capsys, [
        str(root), "--dictionary", str(dictionary), "--format", "json",
    ])

    payload = json.loads("\n".join(lines))
    assert payload["redundant_entries"] == {"Русский": "Russian"}
    assert payload["totals"]["echoed_entries"] == 1


def test_prune_removes_exactly_the_listed_rows(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    Русский: Russian\n    Строка: String\n")

    _code, lines = _run(capsys, [
        str(root), "--dictionary", str(dictionary), "--redundant",
        "--filter", "Русский", "--prune",
    ])

    assert "снято пар: 1" in lines
    text = dictionary.read_text(encoding="utf-8")
    assert "Русский" not in text and "Строка: String" in text
    assert _echoed(root, dictionary) == {"Строка": "String"}


def test_nothing_to_report_says_so(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path)

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--redundant"])

    assert lines[0] == "таких пар нет: словарь нигде не повторяет ответ платформы"
