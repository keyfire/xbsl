"""code/sequential-server-calls: several server calls in a row from one client method.

Every fixture is written once and spelled twice: the templates carry the keywords and the
platform names as fields, and the Russian and the English spellings fill them in. The line
structure is the same in both, so a finding sits on the same line in either language - the
rule must judge them the same way, call by call.
"""

from __future__ import annotations

import pytest

from xbsl import dataset, engine, i18n, parser as P
from xbsl.rules import sequential_calls

RULE = "code/sequential-server-calls"

WORDS = {
    "ru": {
        "метод": "метод", "статический": "статический", "знч": "знч", "возврат": "возврат",
        "если": "если", "иначе": "иначе", "и": "и", "не": "не", "для": "для", "из": "из",
        "попытка": "попытка", "поймать": "поймать", "Исключение": "Исключение",
        "Обработчик": "Обработчик", "ПослеСоздания": "ПослеСоздания",
        "ПослеЧтения": "ПослеЧтения", "ПриОткрытииПоСсылке": "ПриОткрытииПоСсылке",
        "Истина": "Истина", "Ложь": "Ложь", "Таймер": "ПодключитьОбработчикТаймера",
        "Подписка": "ПодключитьОбработчик",
        "Компоненты": "Компоненты", "мс": "мс", "Строка": "Строка", "Число": "Число",
        "Булево": "Булево", "Массив": "Массив", "НаСервере": "НаСервере",
        "НаКлиенте": "НаКлиенте", "ДоступноСКлиента": "ДоступноСКлиента",
        "КешироватьРезультат": "КешироватьРезультат",
    },
    "en": {
        "метод": "method", "статический": "static", "знч": "val", "возврат": "return",
        "если": "if", "иначе": "else", "и": "and", "не": "not", "для": "for", "из": "in",
        "попытка": "try", "поймать": "catch", "Исключение": "Exception",
        "Обработчик": "Handler", "ПослеСоздания": "AfterCreate",
        "ПослеЧтения": "AfterRead", "ПриОткрытииПоСсылке": "OnOpenByLink",
        "Истина": "True", "Ложь": "False", "Таймер": "AttachTimerHandler",
        "Подписка": "AttachHandler",
        "Компоненты": "Components", "мс": "ms", "Строка": "String", "Число": "Number",
        "Булево": "Boolean", "Массив": "Array", "НаСервере": "OnServer",
        "НаКлиенте": "OnClient", "ДоступноСКлиента": "AvailableFromClient",
        "КешироватьРезультат": "CacheResult",
    },
}

YAML = {
    "ru": {
        "module": "ВидЭлемента: ОбщийМодуль\nИд: 11111111-1111-4111-8111-111111111111\n"
                  "Имя: Склады\nОбластьВидимости: ВПроекте\nОкружение: КлиентИСервер\n",
        "form": "ВидЭлемента: КомпонентИнтерфейса\nИд: 22222222-2222-4222-8222-222222222222\n"
                "Имя: ПанельЗадач\nОбластьВидимости: ВПроекте\nНаследует:\n"
                "    Тип: Форма<Булево?>\nСодержимое:\n    -   Тип: СписокЗадач\n"
                "        Имя: Список\n",
        "child": "ВидЭлемента: КомпонентИнтерфейса\nИд: 33333333-3333-4333-8333-333333333333\n"
                 "Имя: СписокЗадач\nОбластьВидимости: ВПроекте\n",
    },
    "en": {
        "module": "ElementKind: CommonModule\nId: 11111111-1111-4111-8111-111111111111\n"
                  "Name: Склады\nVisibilityScope: InProject\nEnvironment: ClientAndServer\n",
        "form": "ElementKind: InterfaceComponent\nId: 22222222-2222-4222-8222-222222222222\n"
                "Name: ПанельЗадач\nVisibilityScope: InProject\nInherits:\n"
                "    Type: Form<Boolean?>\nContent:\n    -   Type: СписокЗадач\n"
                "        Name: Список\n",
        "child": "ElementKind: InterfaceComponent\nId: 33333333-3333-4333-8333-333333333333\n"
                 "Name: СписокЗадач\nVisibilityScope: InProject\n",
    },
}

#: The common module: endpoints, a cached one, a two-environment one, and two client wrappers.
MODULE = """@{НаСервере} @{ДоступноСКлиента}
{метод} Остатки(): {Число}
    {возврат} 1
;

@{НаСервере} @{ДоступноСКлиента}
{метод} Резервы(Код: {Строка}): {Число}
    {возврат} 2
;

@{НаСервере} @{ДоступноСКлиента}
{метод} Код(): {Строка}
    {возврат} "к"
;

@{НаСервере} @{ДоступноСКлиента}{cache}
{метод} Настройка(): {Строка}
    {возврат} "н"
;

@{НаСервере} @{НаКлиенте}
{метод} Оба(): {Строка}
    {возврат} "о"
;

{метод} Обертка(): {Число}
    {возврат} Остатки()
;

{метод} ОберткаУсловная(Флаг: {Булево}): {Число}
    {если} {не} Флаг
        {возврат} 0
    ;
    {возврат} Остатки()
;
"""

#: The child component: its only method calls the server on its main path.
CHILD = """{метод} Загрузить()
    Склады.Остатки()
;
"""


def spell(template: str, lang: str, **extra) -> str:
    return template.format(**WORDS[lang], **extra)


def files(lang: str, page: str, *, cache: str = "cached") -> dict[str, str]:
    """The project: the common module, the form with `page` as its module, the child."""
    words = WORDS[lang]
    annotation = {
        "cached": f"({words['КешироватьРезультат']} = {words['Истина']})",
        "false": f"({words['КешироватьРезультат']} = {words['Ложь']})",
        "unknown": f"({words['КешироватьРезультат']} = Флаг)",
        "missing": "",
    }[cache]
    return {
        "Склады.yaml": YAML[lang]["module"],
        "Склады.xbsl": spell(MODULE, lang, cache=annotation),
        "ПанельЗадач.yaml": YAML[lang]["form"],
        "ПанельЗадач.xbsl": spell(page, lang),
        "СписокЗадач.yaml": YAML[lang]["child"],
        "СписокЗадач.xbsl": spell(CHILD, lang),
    }


def line_of(text: str, needle: str, nth: int = 1) -> int:
    """The line of the nth occurrence of `needle`."""
    lines = [i for i, line in enumerate(text.splitlines(), 1) if needle in line]
    return lines[nth - 1]


@pytest.fixture()
def lint(monkeypatch):
    def run(project: dict[str, str], *, scope: str = "open", min_calls: int = 2):
        monkeypatch.setattr(sequential_calls, "SCOPE", scope)
        monkeypatch.setattr(sequential_calls, "MIN_CALLS", min_calls)
        sources = [engine.load_text(path, text) for path, text in project.items()]
        found = engine.run_sources(sources, select={RULE})
        return sorted(found, key=lambda d: (d.path, d.line, d.col))

    return run


LANGS = pytest.mark.parametrize("lang", ["ru", "en"])

OPEN_TWO = """@{Обработчик}
{метод} {ПослеСоздания}()
    {знч} Остаток = Склады.Остатки()
    {знч} Резерв = Склады.Резервы("а")
;
"""


# --- what is a run ------------------------------------------------------------------------


@pytest.mark.needs_data
@LANGS
def test_two_calls_on_open_make_one_finding_on_the_first_call(lang, lint):
    project = files(lang, OPEN_TWO)
    found = lint(project)
    assert len(found) == 1
    finding = found[0]
    page = project["ПанельЗадач.xbsl"]
    assert finding.path == "ПанельЗадач.xbsl"
    assert finding.line == line_of(page, "Склады.Остатки()")
    assert finding.col == page.splitlines()[finding.line - 1].index("Склады") + 1
    assert finding.severity.value == "info" and finding.fix is None
    assert "При открытии" in finding.message and "(2)" in finding.message
    assert "Склады.Остатки:3, Склады.Резервы:4" in finding.message
    assert "Аргументы" not in finding.message  # the two reads are independent


@pytest.mark.needs_data
@LANGS
def test_a_single_call_is_not_a_run(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Склады.Остатки()
;
"""
    assert lint(files(lang, page)) == []


@pytest.mark.needs_data
@LANGS
def test_calls_on_different_branches_do_not_join(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Склады.Остатки()
    {если} Флаг()
        Склады.Резервы("а")
    {иначе}
        Склады.Резервы("б")
    ;
;

{метод} Флаг(): {Булево}
    {возврат} {Истина}
;
"""
    assert lint(files(lang, page)) == []


@pytest.mark.needs_data
@LANGS
def test_a_branch_with_calls_is_judged_as_its_own_block(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    {если} Флаг()
        Склады.Остатки()
        Склады.Резервы("а")
    ;
;

{метод} Флаг(): {Булево}
    {возврат} {Истина}
;
"""
    project = files(lang, page)
    found = lint(project)
    assert [d.line for d in found] == [line_of(project["ПанельЗадач.xbsl"], "Склады.Остатки()")]


@pytest.mark.needs_data
@LANGS
@pytest.mark.parametrize("statement", [
    "{если} Флаг() {и} Склады.Остатки() > 0",
    "{знч} Остаток = Флаг() ? Склады.Остатки() : 0",
    "{знч} Остаток = Пусто() ?? Склады.Остатки()",
])
def test_a_conditional_operand_is_a_barrier(lang, statement, lint):
    """The right operand of `and`, a branch of `?:` and the fallback of `??` run on some paths."""
    guard = "\n        {возврат}\n    ;" if statement.startswith("{если}") else ""
    page = ("@{Обработчик}\n{метод} {ПослеСоздания}()\n    " + statement + guard + "\n"
            "    Склады.Резервы(\"а\")\n;\n\n"
            "{метод} Флаг(): {Булево}\n    {возврат} {Истина}\n;\n\n"
            "{метод} Пусто(): {Число}?\n    {возврат} 1\n;\n")
    assert lint(files(lang, page)) == []


@pytest.mark.needs_data
@LANGS
def test_a_loop_body_is_not_judged_and_splits_the_path(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Склады.Остатки()
    {для} Код {из} Коды()
        Склады.Резервы(Код)
        {если} Код == "а"
            Склады.Остатки()
            Склады.Резервы(Код)
        ;
    ;
    Склады.Код()
;

{метод} Коды(): {Массив}<{Строка}>
    {возврат} ["а"]
;
"""
    assert lint(files(lang, page)) == []


@pytest.mark.needs_data
@LANGS
def test_a_lambda_and_a_method_reference_are_not_calls_of_this_tick(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    {Таймер}(() -> Склады.Остатки(), 1{мс}, {Ложь})
    {знч} Ссылка = &Склады.Код
    Склады.Резервы("а")
;
"""
    assert lint(files(lang, page)) == []


@pytest.mark.needs_data
@LANGS
@pytest.mark.parametrize("cache,expected", [
    ("cached", 0), ("unknown", 0), ("false", 1), ("missing", 1),
])
def test_the_result_cache_takes_a_method_out_unless_it_is_off(lang, cache, expected, lint):
    """`CacheResult = True` answers from the client cache; an unreadable argument is skipped."""
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Склады.Настройка()
    Склады.Остатки()
;
"""
    assert len(lint(files(lang, page, cache=cache))) == expected


@pytest.mark.needs_data
@LANGS
def test_a_method_of_both_environments_runs_on_the_client(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Склады.Оба()
    Склады.Остатки()
;
"""
    assert lint(files(lang, page)) == []


@pytest.mark.needs_data
@LANGS
def test_a_bare_call_of_an_own_server_method_counts(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Прочитать()
    Прочитать()
;

@{НаСервере} @{ДоступноСКлиента}
{статический} {метод} Прочитать(): {Число}
    {возврат} 1
;
"""
    found = lint(files(lang, page))
    assert len(found) == 1 and "Прочитать:3, Прочитать:4" in found[0].message


# --- dependencies and wrappers ------------------------------------------------------------


@pytest.mark.needs_data
@LANGS
def test_a_data_dependency_is_explained(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    {знч} Код = Склады.Код()
    Склады.Резервы(Код)
;
"""
    found = lint(files(lang, page))
    assert len(found) == 1
    assert "Аргументы 'Склады.Резервы:4' вычисляются из результата 'Склады.Код:3'" in found[0].message


@pytest.mark.needs_data
@LANGS
def test_a_client_wrapper_counts_when_its_main_path_calls_the_server(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Склады.Обертка()
    Склады.Резервы("а")
;
"""
    found = lint(files(lang, page))
    assert len(found) == 1 and "Склады.Обертка:3, Склады.Резервы:4" in found[0].message


@pytest.mark.needs_data
@LANGS
def test_a_wrapper_that_calls_the_server_behind_a_guard_does_not_count(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Склады.ОберткаУсловная({Ложь})
    Склады.Резервы("а")
;
"""
    assert lint(files(lang, page)) == []


@pytest.mark.needs_data
@LANGS
def test_a_child_component_method_is_one_opaque_call(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    {Компоненты}.Список.Загрузить()
    Склады.Остатки()
;
"""
    found = lint(files(lang, page))
    assert len(found) == 1
    assert f"{WORDS[lang]['Компоненты']}.Список.Загрузить:3, Склады.Остатки:4" in found[0].message


@pytest.mark.needs_data
@LANGS
def test_a_same_module_method_is_walked_in_place(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Загрузить()
    Склады.Код()
;

{метод} Загрузить()
    Склады.Остатки()
    Склады.Резервы("а")
;
"""
    project = files(lang, page)
    found = lint(project)
    assert len(found) == 1
    assert found[0].line == line_of(project["ПанельЗадач.xbsl"], "Склады.Остатки()")
    assert f"'{WORDS[lang]['ПослеСоздания']}'" in found[0].message and "(3)" in found[0].message


@pytest.mark.needs_data
@LANGS
def test_the_same_calls_seen_from_a_caller_are_reported_once_for_the_callee(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Загрузить()
;

{метод} Загрузить()
    Склады.Остатки()
    Склады.Резервы("а")
;
"""
    found = lint(files(lang, page))
    assert len(found) == 1 and "'Загрузить'" in found[0].message


# --- error handling -----------------------------------------------------------------------


@pytest.mark.needs_data
@LANGS
def test_calls_in_different_tries_are_not_a_run(lang, lint):
    """A call outside the try and one inside it may be split on purpose: the first must
    happen even when the second fails."""
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Склады.Остатки()
    {попытка}
        Склады.Резервы("а")
    {поймать} Ошибка: {Исключение}
        {возврат}
    ;
;
"""
    assert lint(files(lang, page)) == []


@pytest.mark.needs_data
@LANGS
def test_calls_inside_one_try_are_a_run_and_a_catch_body_is_not_judged(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    {попытка}
        Склады.Остатки()
        Склады.Резервы("а")
    {поймать} Ошибка: {Исключение}
        Склады.Код()
        Склады.Резервы("б")
    ;
;
"""
    project = files(lang, page)
    found = lint(project)
    assert [d.line for d in found] == [line_of(project["ПанельЗадач.xbsl"], "Склады.Остатки()")]


# --- the opening path and the parameters --------------------------------------------------


@pytest.mark.needs_data
@LANGS
@pytest.mark.parametrize("handler", ["ПослеЧтения", "ПриОткрытииПоСсылке"])
def test_the_other_opening_handlers_start_the_path(lang, handler, lint):
    page = OPEN_TWO.replace("{ПослеСоздания}", "{" + handler + "}")
    assert len(lint(files(lang, page))) == 1


@pytest.mark.needs_data
@LANGS
def test_the_opening_path_follows_a_timer_lambda(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    {Таймер}(() -> Отложено(), 1{мс}, {Ложь})
;

{метод} Отложено()
    Склады.Остатки()
    Склады.Резервы("а")
;
"""
    found = lint(files(lang, page))
    assert len(found) == 1 and "При открытии метод 'Отложено'" in found[0].message


@pytest.mark.needs_data
@LANGS
def test_a_subscription_lambda_does_not_open_the_page(lang, lint):
    """A handler subscribed on open runs when its event fires, not while the page opens."""
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Сигнал.{Подписка}(() -> Отложено())
;

{метод} Отложено()
    Склады.Остатки()
    Склады.Резервы("а")
;
"""
    project = files(lang, page)
    assert lint(project) == []
    found = lint(project, scope="all")
    assert len(found) == 1 and found[0].message.startswith("Метод 'Отложено'")


@pytest.mark.needs_data
@LANGS
def test_scope_all_adds_the_methods_off_the_opening_path(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Склады.Остатки()
;

{метод} Сохранить()
    Склады.Остатки()
    Склады.Резервы("а")
;
"""
    project = files(lang, page)
    assert lint(project) == []
    found = lint(project, scope="all")
    assert len(found) == 1
    assert found[0].message.startswith("Метод 'Сохранить' обращается к серверу")


@pytest.mark.needs_data
@LANGS
def test_min_calls_sets_the_shortest_run(lang, lint):
    project = files(lang, OPEN_TWO)
    assert len(lint(project, min_calls=2)) == 1
    assert lint(project, min_calls=3) == []


@pytest.mark.needs_data
@LANGS
def test_shadowed_and_unknown_receivers_are_not_calls(lang, lint):
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    Проверить(1)
    Неизвестный.Остатки()
    Склады.Нет()
;

{метод} Проверить(Склады: {Число})
    Склады.Остатки()
    Склады.Резервы("а")
;
"""
    assert lint(files(lang, page)) == []


@pytest.mark.needs_data
def test_both_spellings_give_the_same_findings_call_by_call(lint):
    """One project with every shape above, judged over all client methods in both spellings."""
    page = """@{Обработчик}
{метод} {ПослеСоздания}()
    {знч} Код = Склады.Код()
    Склады.Резервы(Код)
    {Таймер}(() -> Отложено(), 1{мс}, {Ложь})
;

{метод} Отложено()
    Склады.Обертка()
    {Компоненты}.Список.Загрузить()
    Склады.ОберткаУсловная({Ложь})
;

{метод} Сохранить()
    {попытка}
        Склады.Остатки()
        Склады.Резервы("а")
    {поймать} Ошибка: {Исключение}
        {возврат}
    ;
    {если} Склады.Код() == "к"
        Склады.Настройка()
        Склады.Остатки()
        Склады.Резервы("б")
    ;
;
"""
    seen = {}
    for lang in ("ru", "en"):
        found = lint(files(lang, page), scope="all")
        seen[lang] = [(d.path, d.line, d.col, d.message.count(":")) for d in found]
    assert seen["ru"] == seen["en"]
    # The data pair of the handler, the deferred method (the guarded wrapper left out), and the
    # branch. The try pair is not reported: the condition call after it joins its run, and a
    # run over two different `try` statements is skipped as a whole.
    assert [line for _path, line, _col, _colons in seen["ru"]] == [3, 9, 23]


def test_english_message_names_the_opening_handler_in_english(lint):
    if not _has_data():
        pytest.skip("platform data is not installed")
    i18n.set_lang("en")
    try:
        found = lint(files("en", OPEN_TWO))
    finally:
        i18n.set_lang("ru")
    assert len(found) == 1
    assert found[0].message.startswith("On open, method 'AfterCreate' calls the server")
    assert "round trip" in found[0].message


# --- registration and the data-free paths -------------------------------------------------


def _has_data() -> bool:
    try:
        dataset.load_json("language.json")
    except dataset.DatasetError:
        return False
    return True


def test_registration_is_info_opt_in_and_says_why():
    rule = next(r for r in engine.RULES if r.id == RULE)
    assert (rule.tier, rule.scope, rule.severity.value) == ("D", "project", "info")
    assert not rule.enabled_by_default and rule.mapper is not None
    for lang in ("ru", "en"):
        i18n.set_lang(lang)
        try:
            assert rule.off_reason_text and rule.off_reason_text != f"{RULE}.off"
        finally:
            i18n.set_lang("ru")


def test_parameters_are_declared_with_their_defaults():
    params = {p.name: p for p in engine.params_of(RULE)}
    assert set(params) == {"scope", "min-calls"}
    assert params["scope"].default == "open" and params["min-calls"].default == 2
    assert params["scope"].env == "XBSL_CODE_SEQUENTIAL_SERVER_CALLS_SCOPE"
    assert params["min-calls"].env == "XBSL_CODE_SEQUENTIAL_SERVER_CALLS_MIN_CALLS"


@pytest.mark.parametrize("raw,expected", [("all", "all"), ("everything", "open"), (" ", "open")])
def test_a_value_outside_the_choices_keeps_the_default_and_says_so(raw, expected, monkeypatch,
                                                                   capsys):
    saved = list(engine.PARAMS)
    monkeypatch.setenv("XBSL_WHITESPACE_TRAILING_PROBE_SCOPE", raw)
    try:
        value = engine.rule_param("whitespace/trailing", "probe-scope", "open", "проба",
                                  valid=lambda v: v in ("open", "all"))
    finally:
        engine.PARAMS[:] = saved
    assert value == expected
    err = capsys.readouterr().err
    assert ("XBSL_WHITESPACE_TRAILING_PROBE_SCOPE" in err) == (raw == "everything")


def test_a_number_below_the_minimum_keeps_the_default(monkeypatch, capsys):
    saved = list(engine.PARAMS)
    monkeypatch.setenv("XBSL_WHITESPACE_TRAILING_PROBE_CALLS", "1")
    try:
        value = engine.rule_param("whitespace/trailing", "probe-calls", 2, "проба",
                                  valid=lambda v: v >= 2)
    finally:
        engine.PARAMS[:] = saved
    assert value == 2 and "XBSL_WHITESPACE_TRAILING_PROBE_CALLS" in capsys.readouterr().err


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_without_platform_data_nothing_is_parsed_and_nothing_is_reported(lang, tmp_path,
                                                                          monkeypatch, lint):
    """The shared mapper stops before a module is parsed when the type catalog is missing,
    and this rule's facts ride on it: no flow is compiled and nothing is reported."""

    def unavailable(*_args, **_kwargs):
        raise dataset.DatasetError("no language data")

    monkeypatch.setattr(P, "parse", unavailable)
    dataset.set_data_root(tmp_path)
    try:
        assert lint(files(lang, OPEN_TWO), scope="all") == []
    finally:
        dataset.set_data_root(None)
