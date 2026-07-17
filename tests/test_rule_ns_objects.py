"""Проверки правила code/unknown-ns-object – квалификация объекта через пространство имён вида."""

import pytest

from xbsl import engine
from xbsl.cli import discover

_ПРАВИЛО = "code/unknown-ns-object"

# Проект с объектом каждого проверяемого вида; у справочника – табличная часть и структура модуля.
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


# --- Код: позитив --------------------------------------------------------------------

def test_ns_valid_all_kinds_code(tmp_path):
    # верная NS-квалификация каждого вида в сигнатуре не флагается
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
    # вложенность в дженерики: и аргумент, и второй аргумент соответствия
    d = _проект(
        tmp_path,
        "метод Ф(Списки: Массив<Справочник.Программа.Ссылка>,\n"
        "        Карта: Соответствие<Строка, Документ.Заказ.Ссылка>)\n;\n",
    )
    assert not _has(d)


def test_ns_tabular_and_module_structure_ok(tmp_path):
    # третий сегмент – табличная часть из yaml и структура из модуля объекта
    d = _проект(
        tmp_path,
        "метод Ф(Т: Справочник.Программа.Состав, С: Справочник.Программа.Сводка)\n;\n",
    )
    assert not _has(d)


def test_ns_dotted_stdlib_generic_not_flagged(tmp_path):
    # 'Справочник.Ссылка' / 'Документ.Объект' – обобщённые типы stdlib, а не объекты проекта
    d = _проект(
        tmp_path,
        "метод Ф(А: Справочник.Ссылка, Б: Документ.Объект)\n;\n",
    )
    assert not _has(d)


def test_ns_bare_kind_not_flagged(tmp_path):
    # одиночное имя вида – корневой тип stdlib, не квалификация
    d = _проект(tmp_path, "метод Ф(Х: Справочник)\n;\n")
    assert not _has(d)


def test_ns_plain_object_chain_untouched(tmp_path):
    # обычная квалификация от объекта (без namespace) – зона code/unknown-object-type
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


# --- Код: негатив ---------------------------------------------------------------------

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
    # объект есть, но вид не тот: Программа – Справочник, а не Документ
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


# --- YAML: позитив --------------------------------------------------------------------

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


# --- YAML: негатив --------------------------------------------------------------------

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
    assert находка.line == 5  # позиция строки со значением


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


# --- Гейты ----------------------------------------------------------------------------

def test_ns_no_project_objects_skipped(tmp_path):
    # без объектов проекта правило молчит: судить о NS-ссылках не по чему
    (tmp_path / "м.xbsl").write_text(
        "метод Ф(Х: Справочник.ЧегоНет.Ссылка)\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={_ПРАВИЛО})
    assert not _has(d)


@pytest.mark.needs_data
def test_row_type_named_by_the_form_is_known():
    # форма именует порождаемый тип строки динсписка свойством ИмяТипаДанныхСтроки
    # (доки topics/virtual-table): тип ФормаX.ДанныеСтрокиСписка существует, ругаться не на что
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
