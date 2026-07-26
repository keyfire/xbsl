"""Checks of the query/deletion-mark-immediate rule (a mark on an object without one)."""

from xbsl import engine

_RULE = "query/deletion-mark-immediate"

_IMMEDIATE = (
    "ВидЭлемента: Справочник\nИд: 4d7a1c92-3e85-4b26-9f01-8c5d2a7e6b33\n"
    "Имя: Абоненты\nРежимУдаления: Немедленно\n"
)
_MARKED = (
    "ВидЭлемента: Справочник\nИд: 5d7a1c92-3e85-4b26-9f01-8c5d2a7e6b34\nИмя: Акции\n"
)


def _lint(code: str, *yamls: str):
    sources = [engine.load_text("acme/П/О/М.xbsl", code)]
    for i, text in enumerate(yamls or (_IMMEDIATE, _MARKED)):
        sources.append(engine.load_text(f"acme/П/О/Об{i}.yaml", text))
    return engine.run_sources(sources, select={_RULE})


def test_mark_on_an_immediately_deleted_object_is_reported():
    d = _lint(
        "метод М()\n"
        "    знч З = Запрос{ВЫБРАТЬ А.Ссылка ИЗ Абоненты КАК А ГДЕ не А.ПометкаУдаления}\n"
        ";\n"
    )
    assert len(d) == 1 and d[0].rule_id == _RULE and d[0].line == 2
    assert "Абоненты" in d[0].message


def test_mark_on_an_ordinary_object_is_silent():
    d = _lint(
        "метод М()\n"
        "    знч З = Запрос{ВЫБРАТЬ К.Ссылка ИЗ Акции КАК К ГДЕ не К.ПометкаУдаления}\n"
        ";\n"
    )
    assert d == []


def test_table_addressed_without_an_alias_is_reported():
    d = _lint(
        "метод М()\n"
        "    знч З = Запрос{ВЫБРАТЬ Абоненты.Ссылка ИЗ Абоненты "
        "ГДЕ не Абоненты.ПометкаУдаления}\n"
        ";\n"
    )
    assert len(d) == 1


def test_a_chain_through_another_object_is_silent():
    # `А.Владелец.ПометкаУдаления` is the mark of the OWNER, whose mode is not known here
    d = _lint(
        "метод М()\n"
        "    знч З = Запрос{ВЫБРАТЬ А.Ссылка ИЗ Абоненты КАК А ГДЕ не А.Владелец.ПометкаУдаления}\n"
        ";\n"
    )
    assert d == []


def test_english_spelling_is_judged():
    immediate_en = (
        "ElementKind: Catalog\nId: 4d7a1c92-3e85-4b26-9f01-8c5d2a7e6b33\n"
        "Name: Абоненты\nDeletionMode: Immediately\n"
    )
    d = _lint(
        "метод М()\n"
        "    знч З = Запрос{ВЫБРАТЬ А.Ссылка ИЗ Абоненты КАК А ГДЕ не А.DeletionMark}\n"
        ";\n",
        immediate_en,
    )
    assert len(d) == 1
