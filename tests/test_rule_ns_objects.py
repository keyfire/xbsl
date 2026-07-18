"""Checks of the code/unknown-ns-object rule - object qualification via the kind namespace."""

import pytest

from xbsl import engine
from xbsl.cli import discover

_ПРАВИЛО = "code/unknown-ns-object"

# A project with one object of every checked kind; the catalog has a tabular section and a module structure.
_ОБЪЕКТЫ = {
    "Программа.yaml": (
        "ВидЭлемента: Справочник\nИмя: Программа\nТабличныеЧасти:\n    -\n        Имя: Состав\n"
    ),
    "Заказ.yaml": "ВидЭлемента: Документ\nИмя: Заказ\n",
    "Настройки.yaml": "ВидЭлемента: РегистрСведений\nИмя: Настройки\n",
    "Остатки.yaml": "ВидЭлемента: РегистрНакопления\nИмя: Остатки\n",
    "ВидСообщения.yaml": (
        "ВидЭлемента: Перечисление\nИмя: ВидСообщения\nЭлементы:\n    -\n        Имя: Важное\n"
    ),
    "Обмен.yaml": "ВидЭлемента: ПланОбмена\nИмя: Обмен\n",
}


def _проект(tmp_path, code=None, form_yaml=None):
    for имя, текст in _ОБЪЕКТЫ.items():
        (tmp_path / имя).write_text(текст, encoding="utf-8")
    (tmp_path / "Программа.xbsl").write_text(
        "структура Сводка\n    пер Всего: Число\n;\n", encoding="utf-8",
    )
    if code is not None:
        (tmp_path / "м.xbsl").write_text(code, encoding="utf-8")
    if form_yaml is not None:
        (tmp_path / "Ф.yaml").write_text(form_yaml, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={_ПРАВИЛО})


def _has(diags):
    return any(d.rule_id == _ПРАВИЛО for d in diags)


# --- Code: positive ------------------------------------------------------------------

def test_ns_valid_all_kinds_code(tmp_path):
    # a correct NS qualification of every kind in a signature is not flagged
    d = _проект(
        tmp_path,
        "метод Ф(\n"
        "    А: Справочник.Программа.Ссылка,\n"
        "    Б: Документ.Заказ.Объект,\n"
        "    В: РегистрСведений.Настройки.НаборЗаписей,\n"
        "    Г: РегистрНакопления.Остатки.НаборЗаписей,\n"
        "    Д: Перечисление.ВидСообщения,\n"
        "    Е: ПланОбмена.Обмен.Ссылка)\n"
        ";\n",
    )
    assert not _has(d)


def test_ns_var_declaration_nullable_ok(tmp_path):
    d = _проект(
        tmp_path,
        "метод Ф()\n    пер А: Справочник.Программа.Ссылка? = Неопределено\n;\n",
    )
    assert not _has(d)


def test_ns_generic_nesting_ok(tmp_path):
    # nesting inside generics: both the argument and the map's second argument
    d = _проект(
        tmp_path,
        "метод Ф(Списки: Массив<Справочник.Программа.Ссылка>,\n"
        "        Карта: Соответствие<Строка, Документ.Заказ.Ссылка>)\n;\n",
    )
    assert not _has(d)


def test_ns_tabular_and_module_structure_ok(tmp_path):
    # the third segment - a tabular section from yaml and a structure from the object module
    d = _проект(
        tmp_path,
        "метод Ф(Т: Справочник.Программа.Состав, С: Справочник.Программа.Сводка)\n;\n",
    )
    assert not _has(d)


def test_ns_dotted_stdlib_generic_not_flagged(tmp_path):
    # 'Справочник.Ссылка' / 'Документ.Объект' are generic stdlib types, not project objects
    d = _проект(
        tmp_path,
        "метод Ф(А: Справочник.Ссылка, Б: Документ.Объект)\n;\n",
    )
    assert not _has(d)


def test_ns_bare_kind_not_flagged(tmp_path):
    # a lone kind name is a root stdlib type, not a qualification
    d = _проект(tmp_path, "метод Ф(Х: Справочник)\n;\n")
    assert not _has(d)


def test_ns_plain_object_chain_untouched(tmp_path):
    # a plain object qualification (no namespace) is code/unknown-object-type territory
    d = _проект(tmp_path, "метод Ф(Т: Программа.Ссылка, О: Программа.Ерунда)\n;\n")
    assert not _has(d)


def test_ns_cast_ok(tmp_path):
    d = _проект(
        tmp_path,
        "метод Ф(Х: Строка): Булево\n"
        "    знч О = Х как Справочник.Программа.Ссылка\n"
        "    возврат О != Неопределено\n"
        ";\n",
    )
    assert not _has(d)


# --- Code: negative -------------------------------------------------------------------

@pytest.mark.parametrize("тип", [
    "Справочник.Программма.Ссылка",
    "Документ.Закааз.Объект",
    "РегистрСведений.Настройкии.НаборЗаписей",
    "РегистрНакопления.Остаткии.НаборЗаписей",
    "Перечисление.ВидСообщенияя",
    "ПланОбмена.Обменн.Ссылка",
])
def test_ns_unknown_object_flagged_code(tmp_path, тип):
    d = _проект(tmp_path, f"метод Ф(Х: {тип})\n;\n")
    имя = тип.split(".")[1]
    assert any(x.rule_id == _ПРАВИЛО and имя in x.message for x in d)


def test_ns_kind_mismatch_flagged_code(tmp_path):
    # the object exists but the kind is wrong: Программа is a Справочник, not a Документ
    d = _проект(tmp_path, "метод Ф(Х: Документ.Программа.Ссылка)\n;\n")
    сообщения = [x.message for x in d if x.rule_id == _ПРАВИЛО]
    assert len(сообщения) == 1 and "Справочник" in сообщения[0] and "Документ" in сообщения[0]


def test_ns_bad_member_flagged_code(tmp_path):
    d = _проект(tmp_path, "метод Ф(Х: Справочник.Программа.Сылка)\n;\n")
    assert any(
        x.rule_id == _ПРАВИЛО and "Справочник.Программа.Сылка" in x.message for x in d
    )


def test_ns_generic_nesting_flagged(tmp_path):
    d = _проект(tmp_path, "метод Ф(Списки: Массив<Справочник.Программма.Ссылка>)\n;\n")
    assert any(x.rule_id == _ПРАВИЛО and "Программма" in x.message for x in d)


def test_ns_new_unknown_flagged(tmp_path):
    d = _проект(tmp_path, "метод Ф()\n    знч А = новый Справочник.Программма()\n;\n")
    assert any(x.rule_id == _ПРАВИЛО and "Программма" in x.message for x in d)


# --- YAML: positive -------------------------------------------------------------------

def test_ns_yaml_valid_all_kinds(tmp_path):
    d = _проект(
        tmp_path,
        form_yaml=(
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\n"
            "Содержимое:\n"
            "    -\n        Тип: ПолеВвода<Справочник.Программа.Ссылка?>\n"
            "    -\n        Тип: ПолеВвода<Перечисление.ВидСообщения?>\n"
            "Реквизиты:\n"
            "    -\n        Имя: А\n        Тип: Документ.Заказ.Ссылка?\n"
            "    -\n        Имя: Б\n        Тип: Массив<ПланОбмена.Обмен.Ссылка>\n"
            "    -\n        Имя: В\n        Тип: РегистрСведений.Настройки.НаборЗаписей?\n"
            "    -\n        Имя: Г\n        Тип: РегистрНакопления.Остатки.НаборЗаписей?\n"
        ),
    )
    assert not _has(d)


def test_ns_yaml_non_element_file_skipped(tmp_path):
    (tmp_path / "конфиг.yaml").write_text(
        "Тип: Справочник.Ерунда.Ссылка\n", encoding="utf-8",
    )
    d = _проект(tmp_path)
    assert not _has(d)


# --- YAML: negative -------------------------------------------------------------------

def test_ns_yaml_unknown_object_flagged(tmp_path):
    d = _проект(
        tmp_path,
        form_yaml=(
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n    -\n"
            "        Тип: ПолеВвода<Справочник.Программма.Ссылка?>\n"
        ),
    )
    находка = next((x for x in d if x.rule_id == _ПРАВИЛО), None)
    assert находка is not None and "Программма" in находка.message
    assert находка.line == 5  # the position of the line holding the value


def test_ns_yaml_kind_mismatch_flagged(tmp_path):
    d = _проект(
        tmp_path,
        form_yaml=(
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nРеквизиты:\n"
            "    -\n        Имя: А\n        Тип: Документ.Программа.Ссылка?\n"
        ),
    )
    сообщения = [x.message for x in d if x.rule_id == _ПРАВИЛО]
    assert len(сообщения) == 1 and "Справочник" in сообщения[0]


def test_ns_yaml_bad_member_flagged_in_generic(tmp_path):
    d = _проект(
        tmp_path,
        form_yaml=(
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nРеквизиты:\n"
            "    -\n        Имя: А\n        Тип: Массив<Справочник.Программа.Сылка>\n"
        ),
    )
    assert any(
        x.rule_id == _ПРАВИЛО and "Справочник.Программа.Сылка" in x.message for x in d
    )


# --- Gates ----------------------------------------------------------------------------

def test_ns_no_project_objects_skipped(tmp_path):
    # without project objects the rule stays silent: nothing to judge NS references by
    (tmp_path / "м.xbsl").write_text(
        "метод Ф(Х: Справочник.ЧегоНет.Ссылка)\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={_ПРАВИЛО})
    assert not _has(d)


@pytest.mark.needs_data
def test_row_type_named_by_the_form_is_known():
    # the form names the generated dynamic list row type via the ИмяТипаДанныхСтроки property
    # (docs topics/virtual-table): the type ФормаX.ДанныеСтрокиСписка exists, nothing to complain about
    yaml_text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 6c964b22-6612-43df-aca9-588e385bd2a5\n"
        "Имя: ФормаСписка\n"
        "Содержимое:\n"
        "  - Тип: ДинамическийСписок<ФормаСписка.ДанныеСтрокиСписка>\n"
        "    ЗначениеПоУмолчанию:\n"
        "      ИмяТипаДанныхСтроки: ДанныеСтрокиСписка\n"
    )
    sources = [engine.load_text("ФормаСписка.yaml", yaml_text)]
    diags = engine.run_sources(sources, select={"yaml/unknown-type", "code/unknown-ns-object"})
    assert [d.message for d in diags] == []


# --- English derived-type aliases (bilingual identifiers) -----------------------------

def test_member_family_includes_english_aliases():
    # Банки.Record (= Банки.Запись) must be known: platform identifiers are bilingual, but the
    # extracted catalog carries only the Russian derived-type names.
    from xbsl.rules.semantics import _member_family

    fam = _member_family("РегистрСведений")
    for name in ("Запись", "Record", "Ссылка", "Reference", "НаборЗаписей", "RecordSet"):
        assert name in fam, name
    # a typo is still not in the family
    assert "Recrd" not in fam


def test_unknown_object_type_accepts_english_derived(tmp_path):
    # a bilingual derived-type name on a project object is not flagged, a typo still is
    (tmp_path / "Банки.yaml").write_text("ВидЭлемента: РегистрСведений\nИмя: Банки\n", encoding="utf-8")

    def lint(member: str):
        (tmp_path / "м.xbsl").write_text(f"метод Ф()\n    пер mEl: Банки.{member}\n;\n", encoding="utf-8")
        return engine.run(discover([str(tmp_path)]), select={"code/unknown-object-type"})

    assert not any(d.rule_id == "code/unknown-object-type" for d in lint("Record"))
    assert not any(d.rule_id == "code/unknown-object-type" for d in lint("Reference"))
    assert not any(d.rule_id == "code/unknown-object-type" for d in lint("Запись"))
    assert any(d.rule_id == "code/unknown-object-type" for d in lint("Recrd"))
