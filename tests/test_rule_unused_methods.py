"""Checks of the code/unused-method rule (dead methods, tier D, scope=project).

The rule needs the lexer, and the lexer needs the Element language data; without the data
the whole module is skipped (conftest does not know this file, so we guard ourselves).
"""

import pytest

from xbsl import dataset, engine, i18n
from xbsl.cli import discover

pytestmark = pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – сгенерируйте: python tools/extract.py --dist ...",
)

RULE = "code/unused-method"


def _lint_dir(tmp_path, **files):
    for name, content in files.items():
        (tmp_path / name.replace("__", ".")).write_text(content, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={RULE})


def _hits(diags):
    return [d for d in diags if d.rule_id == RULE]


# --- The signal: declared and never seen anywhere else ---------------------------------

def test_dead_method_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl="метод Живой()\n;\n\nметод Мёртвый()\n;\n\nметод Главный()\n    Живой()\n;\n",
        Ф__yaml="Обработчик: Главный\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and "Мёртвый" in hits[0].message


def test_position_is_declaration_name(tmp_path):
    d = _lint_dir(tmp_path, М__xbsl="// шапка\nметод Мёртвый()\n;\n")
    hits = _hits(d)
    assert (hits[0].line, hits[0].col) == (2, 7)


def test_off_by_default(tmp_path):
    (tmp_path / "М.xbsl").write_text("метод Мёртвый()\n;\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]))
    assert not _hits(d)


# --- Guard: the name is mentioned somewhere else ----------------------------------------

def test_qualified_call_from_other_module_not_flagged(tmp_path):
    # a static manager method called with the Модуль.Метод qualification
    d = _lint_dir(
        tmp_path,
        Менеджер__xbsl="стат метод Посчитать(): Число\n    возврат 1\n;\n",
        Клиент__xbsl="@Обработчик\nметод ПослеСоздания()\n    Менеджер.Посчитать()\n;\n",
    )
    assert not _hits(d)


def test_mention_in_yaml_not_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        Ф__xbsl="метод Клик(Источник: Надпись)\n;\n",
        Ф__yaml="Содержимое:\n    -\n        Тип: Надпись\n        ПриНажатии: Клик\n",
    )
    assert not _hits(d)


def test_mention_in_string_literal_not_flagged(tmp_path):
    # the HTML insert bridge calls the method by name inside a string literal
    d = _lint_dir(
        tmp_path,
        Ф__xbsl=(
            "метод ОбновитьСчётчик()\n;\n\n"
            "метод Разметка(): Строка\n"
            "    возврат \"<script>bridge.call('ОбновитьСчётчик')</script>\"\n"
            ";\n"
        ),
        Ф__yaml="Обработчик: Разметка\n",
    )
    assert not _hits(d)


# --- What a comment is worth: nothing ------------------------------------------------------

def _comment_only(name: str) -> str:
    return i18n.t("code/unused-method.comment-only", name=name)


def test_comment_of_the_same_module_does_not_count(tmp_path):
    # the note claiming an invisible caller is prose; the annotation and the baseline are
    # what silences such a method
    d = _lint_dir(
        tmp_path,
        М__xbsl="// Колбэк: платформа вызывает ПоТаймеру\nметод ПоТаймеру()\n;\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and hits[0].message == _comment_only("ПоТаймеру")


def test_comment_of_another_module_does_not_count(tmp_path):
    # prose about a method is not a call, and a module keeps its notes about itself at home
    d = _lint_dir(
        tmp_path,
        А__xbsl="@ВПроекте\nметод СобратьРазметку()\n;\n",
        Б__xbsl="// разметку раньше собирал СобратьРазметку\nметод Главный()\n;\n",
        Б__yaml="Обработчик: Главный\n",
    )
    hits = _hits(d)
    assert len(hits) == 1
    assert hits[0].message == _comment_only("СобратьРазметку")


def test_comment_of_the_paired_yaml_does_not_count(tmp_path):
    # a `#` note of the paired yaml is prose as much as a `//` one of the module
    d = _lint_dir(
        tmp_path,
        Ф__xbsl="метод Клик()\n;\n",
        Ф__yaml="# Клик зовёт вставка по имени\nИмя: Ф\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and hits[0].message == _comment_only("Клик")


def test_comment_of_another_yaml_does_not_count(tmp_path):
    d = _lint_dir(
        tmp_path,
        А__xbsl="@ВПроекте\nметод Клик()\n;\n",
        Б__yaml="# Клик зовёт вставка по имени\nИмя: Б\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and hits[0].message == _comment_only("Клик")


def test_doc_comment_of_a_neighbour_method_does_not_count(tmp_path):
    # a doc comment describes the neighbour, it does not call the method it names
    d = _lint_dir(
        tmp_path,
        М__xbsl=(
            "метод Подпись()\n;\n\n"
            "/** Готовит данные.\n * Подпись берётся отдельно.\n */\n"
            "метод Данные()\n;\n\n"
            "метод Главный()\n    Данные()\n;\n"
        ),
        М__yaml="Обработчик: Главный\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and hits[0].message == _comment_only("Подпись")


def test_doc_comment_of_another_module_does_not_count(tmp_path):
    d = _lint_dir(
        tmp_path,
        А__xbsl="@ВПроекте\nметод Подпись()\n;\n",
        Б__xbsl=(
            "/** Готовит данные.\n * Подпись берётся отдельно.\n */\n"
            "метод Данные()\n;\n"
        ),
        Б__yaml="Обработчик: Данные\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and hits[0].message == _comment_only("Подпись")


def test_string_literal_of_another_module_still_counts(tmp_path):
    # a string is a call the reader cannot see, wherever the module holding it lies
    d = _lint_dir(
        tmp_path,
        А__xbsl="@ВПроекте\nметод ОбновитьСчётчик()\n;\n",
        Б__xbsl=(
            "метод Разметка(): Строка\n"
            "    возврат \"<script>bridge.call('ОбновитьСчётчик')</script>\"\n"
            ";\n"
        ),
        Б__yaml="Обработчик: Разметка\n",
    )
    assert not _hits(d)


def test_dead_method_named_nowhere_keeps_the_plain_message(tmp_path):
    # the negative control: with no comment anywhere the wording does not change
    d = _lint_dir(tmp_path, М__xbsl="@ВПроекте\nметод Мёртвый()\n;\n")
    hits = _hits(d)
    assert len(hits) == 1
    assert hits[0].message == i18n.t("code/unused-method.unreferenced", name="Мёртвый")


# --- Guard: annotations -----------------------------------------------------------------

def test_platform_annotation_not_flagged(tmp_path):
    # the platform and the contracts call these themselves - no project mention is required
    d = _lint_dir(
        tmp_path,
        М__xbsl=(
            "@Обработчик\nметод ПриСобытии()\n;\n\n"
            "@Подписка\nстатический метод НаЗапись()\n;\n\n"
            "@Реализация\nметод Выполнить()\n;\n\n"
            "@Переопределение\nметод Заголовок()\n;\n\n"
            "@Устарело\nметод Старый()\n;\n"
        ),
    )
    assert not _hits(d)


def test_unknown_annotation_not_flagged(tmp_path):
    # a project may declare its own annotation; an unknown name silences the finding
    d = _lint_dir(tmp_path, М__xbsl="@МояАннотация\nметод Помеченный()\n;\n")
    assert not _hits(d)


def test_annotation_with_arguments_not_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl='@ОбновлениеПроекта(Ид = "Конвертация", Номер = 1)\nметод Конвертация()\n;\n',
    )
    assert not _hits(d)


# --- The signal: visibility and environment annotations do NOT silence -------------------

def test_public_method_without_callers_flagged(tmp_path):
    # the public API of a common module is exactly where dead code piles up
    d = _lint_dir(
        tmp_path,
        М__xbsl="@НаСервере @ВПроекте\nметод Осиротевший()\n;\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and "Осиротевший" in hits[0].message


def test_public_method_with_caller_not_flagged(tmp_path):
    # the negative control of the test above: one caller elsewhere silences the rule
    d = _lint_dir(
        tmp_path,
        М__xbsl="@НаСервере @ВПроекте\nметод Осиротевший()\n;\n",
        П__xbsl="@НаСервере\nметод Главный()\n    М.Осиротевший()\n;\n",
        П__yaml="Обработчик: Главный\n",
    )
    assert not _hits(d)


def test_environment_annotation_still_judged(tmp_path):
    d = _lint_dir(tmp_path, М__xbsl="@ДоступноСКлиента\nметод Клиентский()\n;\n")
    hits = _hits(d)
    assert len(hits) == 1 and "Клиентский" in hits[0].message


def test_english_visibility_annotation_still_judged(tmp_path):
    # the project is bilingual: the English spelling of the annotation is the same guard
    d = _lint_dir(tmp_path, M__xbsl="@OnServer @InProject\nmethod Orphan()\n;\n")
    hits = _hits(d)
    assert len(hits) == 1 and "Orphan" in hits[0].message


def test_comment_between_annotation_and_method(tmp_path):
    # the annotation block is read through a comment line, so the guard still applies
    d = _lint_dir(
        tmp_path,
        М__xbsl="@Обработчик\n// платформа зовёт его сама\nметод ПриСобытии()\n;\n",
    )
    assert not _hits(d)


def test_annotation_of_next_method_not_inherited(tmp_path):
    # the annotation belongs to the next method, not the previous one
    d = _lint_dir(
        tmp_path,
        М__xbsl="метод Мёртвый()\n;\n\n@НаСервере\nметод Живой()\n;\n\nметод Главный()\n    Живой()\n;\n",
        Ф__yaml="Обработчик: Главный\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and "Мёртвый" in hits[0].message


def test_static_between_annotation_and_method(tmp_path):
    # the modifier does not hide the annotation: the platform one still silences the method
    d = _lint_dir(tmp_path, М__xbsl="@Обработчик\nстатический метод Утилита()\n;\n")
    assert not _hits(d)


def test_static_public_method_flagged(tmp_path):
    # the same walk, the other verdict: a visibility annotation leaves the method judged
    d = _lint_dir(tmp_path, М__xbsl="@ВПроекте\nстатический метод Утилита()\n;\n")
    hits = _hits(d)
    assert len(hits) == 1 and "Утилита" in hits[0].message


# --- Guard: platform events -------------------------------------------------------------

def test_platform_event_without_annotation_not_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl="метод ПослеСоздания()\n;\n\nметод ПередЗаписью()\n;\n",
    )
    assert not _hits(d)


#: Handler lists of the data's shape, with made-up handlers: a name only these tables know
#: proves the guard reads them. A component base, and an element kind with two modules.
_COMPONENTS = {"Панель": ({"ru": "ПослеПоказаПанели", "en": "AfterPanelShow"},)}
_ELEMENTS = {
    "Склад": {
        "": {"handlers": ({"ru": "ПроверитьОстатки", "en": "CheckStock"},), "dynamic": ()},
        "Объект": {"handlers": ({"ru": "ПослеПересчетаОстатков", "en": "AfterStockRecount"},),
                   "dynamic": ()},
    },
}


@pytest.fixture
def lists(monkeypatch):
    """Put handler lists in place of the data sections; the guard keeps what it read, so its
    cache goes with them (an earlier test of the run leaves it filled from the real data)."""
    from functools import lru_cache

    from xbsl import modulehandlers
    from xbsl.rules import unused_methods

    def use(components: dict, elements: dict) -> None:
        monkeypatch.setattr(modulehandlers, "_table", lru_cache(maxsize=1)(lambda: components))
        monkeypatch.setattr(modulehandlers, "_elements", lru_cache(maxsize=1)(lambda: elements))
        modulehandlers._reset()
        unused_methods.platform_handlers.cache_clear()

    yield use
    monkeypatch.undo()
    modulehandlers._reset()
    unused_methods.platform_handlers.cache_clear()


def _dead(tmp_path, *names: str) -> list[str]:
    """The names among `names` the rule reports, each declared once in a module of its own."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    files = {f"М{index}__xbsl": f"метод {name}()\n;\n" for index, name in enumerate(names)}
    return sorted(hit.message.split("'")[1] for hit in _hits(_lint_dir(tmp_path, **files)))


def test_the_handlers_of_the_lists_are_not_flagged_in_either_spelling(tmp_path, lists):
    lists(_COMPONENTS, _ELEMENTS)
    assert _dead(tmp_path, "ПослеПоказаПанели", "AfterPanelShow", "ПроверитьОстатки",
                 "CheckStock", "ПослеПересчетаОстатков", "AfterStockRecount",
                 "ПослеПересчетаЦен") == ["ПослеПересчетаЦен"]


def test_control_a_handler_taken_out_of_the_lists_is_flagged(tmp_path, lists):
    """The negative control: the same declarations, the rows gone - and the old list with them."""
    lists({"Панель": ()}, {"Склад": {"": {"handlers": (), "dynamic": ()}}})
    assert _dead(tmp_path, "ПослеПоказаПанели", "AfterStockRecount", "ПередЗаписью") == [
        "AfterStockRecount", "ПередЗаписью", "ПослеПоказаПанели"]


def test_the_record_security_handlers_are_not_flagged_whatever_the_lists(tmp_path, lists):
    """The build names them after the access settings: no section lists them."""
    lists(_COMPONENTS, _ELEMENTS)
    assert _dead(tmp_path, "ВычислитьРазрешенияДоступаДляОбъектов", "ComputeAccessKeysForRead",
                 "ВычислитьКлючиДоступаДляИзменения") == []
    lists({}, {})
    assert _dead(tmp_path / "без", "ComputeAccessPermissionsForObjects",
                 "ВычислитьКлючиДоступаДляЧтения", "ComputeAccessKeysForUpdate") == []


def test_the_object_form_names_of_format_5_0_are_judged(tmp_path, lists):
    """The converter of format 6.0 renames them, and no supported mode is older."""
    lists(_COMPONENTS, _ELEMENTS)
    assert _dead(tmp_path, "ПередЗаписьюОбъекта", "ПослеЗаписиОбъекта", "ПередУдалениемОбъекта",
                 "ПослеУдаленияОбъекта") == [
        "ПередЗаписьюОбъекта", "ПередУдалениемОбъекта", "ПослеЗаписиОбъекта",
        "ПослеУдаленияОбъекта"]


def test_without_the_sections_the_fallback_keeps_the_names_listed_by_hand(tmp_path, lists):
    lists({}, {})
    assert _dead(tmp_path, "ПослеСоздания", "ПриОткрытииПоСсылке", "ПриЗаполнении",
                 "ВычислитьПараметрыРаботыКлиента", "ПроверитьНаличиеКлючейДоступа",
                 "ПослеПересчетаОстатков") == ["ПослеПересчетаОстатков"]


def test_a_section_the_data_lacks_falls_back_alone(tmp_path, lists):
    """The component lists are there, the element ones are not: each part answers for itself."""
    lists(_COMPONENTS, {})
    # A name of the element fallback is kept, one of the component fallback is not: the
    # component lists of the data answer for the components now, and they do not name it.
    assert _dead(tmp_path, "ПослеПоказаПанели", "ПриЗаполнении", "ПриОбновлении") == [
        "ПриОбновлении"]


# --- Guard: special modules -------------------------------------------------------------

def test_object_module_skipped(tmp_path):
    d = _lint_dir(
        tmp_path,
        Полезное__Объект__xbsl="метод ПодготовитьКод()\n;\n",
    )
    assert not _hits(d)


def test_http_service_module_skipped(tmp_path):
    d = _lint_dir(
        tmp_path,
        Апи__yaml="ВидЭлемента: HttpСервис\nИмя: Апи\n",
        Апи__xbsl="метод ОбработатьЗапрос()\n;\n",
    )
    assert not _hits(d)


def test_http_service_with_trailing_comment_skipped(tmp_path):
    # a comment after the kind does not hide the HTTP service from the exemption
    d = _lint_dir(
        tmp_path,
        Апи__yaml="ВидЭлемента: HttpСервис # публичное апи\nИмя: Апи\n",
        Апи__xbsl="метод ОбработатьЗапрос()\n;\n",
    )
    assert not _hits(d)


# --- Miscellaneous ----------------------------------------------------------------------

def test_same_name_in_two_modules_not_flagged(tmp_path):
    # two same-named declarations silence each other (a mention exists - no verdict possible)
    d = _lint_dir(
        tmp_path,
        А__xbsl="метод Общий()\n;\n",
        Б__xbsl="метод Общий()\n;\n",
    )
    assert not _hits(d)


def test_structure_method_checked(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl=(
            "структура Держатель\n"
            "    метод МёртвыйЧлен()\n    ;\n"
            ";\n"
        ),
    )
    hits = _hits(d)
    assert len(hits) == 1 and "МёртвыйЧлен" in hits[0].message
