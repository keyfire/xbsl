"""Проверки правил тиров A/B/C через ядро."""

import pytest

from xbsl import engine
from xbsl.cli import discover


def _lint(name, content, **kw):
    return engine.run_sources([engine.load_text(name, content)], **kw)


def _has(diags, rule_id):
    return any(d.rule_id == rule_id for d in diags)


# --- Тир B ---------------------------------------------------------------------------

def test_curly_quotes_flagged():
    d = _lint("М.xbsl", "// текст “в кавычках”\n", select={"typography/curly-quotes"})
    assert _has(d, "typography/curly-quotes")


def test_em_dash_off_by_default_then_selectable():
    from xbsl.engine import SEVERITY_OVERRIDES

    if "typography/em-dash" in SEVERITY_OVERRIDES:
        pytest.skip("уровень переопределён установленным плагином – публичный дефолт не виден")
    content = "// длинное тире — здесь\n"
    assert _lint("М.xbsl", content) == []  # выключено по умолчанию
    d = _lint("М.xbsl", content, select={"typography/em-dash"})
    assert len(d) == 1 and d[0].severity.value == "info"


def test_trailing_whitespace():
    d = _lint("М.xbsl", "метод Ф()  \n;\n", select={"whitespace/trailing"})
    assert len(d) == 1


# --- Тир C ---------------------------------------------------------------------------

def test_unclosed_paren():
    d = _lint("М.xbsl", "метод Ф()\n    возврат (1\n;\n", select={"code/brackets"})
    assert _has(d, "code/brackets")


def test_extra_semicolon():
    d = _lint("М.xbsl", "метод Ф()\n;\n;\n", select={"code/blocks"})
    assert any("Лишний" in x.message for x in d)


def test_else_if_same_line_balances():
    content = (
        "метод Ф(Х: Число): Число\n"
        "    если Х == 1\n        возврат 1\n"
        "    иначе если Х == 2\n        возврат 2\n"
        "    ;\n    возврат 0\n;\n"
    )
    assert _lint("М.xbsl", content, select={"C"}) == []


def test_ternary_compound_condition_flagged():
    content = (
        "метод Ф(А: Булево, Б: Строка): Строка\n"
        '    возврат (А и Б это Строка ? Б как Строка : "")\n'
        ";\n"
    )
    d = _lint("М.xbsl", content, select={"code/ternary-and-or"})
    assert len(d) == 1 and "скобки" in d[0].message


def test_ternary_compound_condition_or_flagged_without_parens():
    content = (
        "метод Ф(А: Булево, Б: Булево): Число\n"
        "    возврат А или Б ? 1 : 0\n"
        ";\n"
    )
    d = _lint("М.xbsl", content, select={"code/ternary-and-or"})
    assert len(d) == 1 and "или" in d[0].message


def test_ternary_parenthesized_condition_ok():
    content = (
        "метод Ф(А: Булево, Б: Строка): Строка\n"
        '    возврат ((А и Б это Строка) ? Б как Строка : "")\n'
        ";\n"
    )
    assert _lint("М.xbsl", content, select={"code/ternary-and-or"}) == []


def test_ternary_simple_condition_ok():
    content = (
        "метод Ф(Б: Строка): Строка\n"
        '    возврат (Б != "" ? Б : "нет")\n'
        ";\n"
    )
    assert _lint("М.xbsl", content, select={"code/ternary-and-or"}) == []


def test_ternary_and_in_other_arg_ok():
    # 'и' в другом аргументе (до запятой) не относится к тернарному условию
    content = (
        "метод Ф(А: Булево, Б: Булево, В: Строка): Строка\n"
        '    возврат Свести(А и Б, В != "" ? В : "нет")\n'
        ";\n"
    )
    assert _lint("М.xbsl", content, select={"code/ternary-and-or"}) == []


def test_ternary_and_after_question_ok():
    # 'и' в ветке результата (после '?') – корректный код
    content = (
        "метод Ф(А: Булево, Б: Булево): Булево\n"
        "    возврат (А ? А и Б : Ложь)\n"
        ";\n"
    )
    assert _lint("М.xbsl", content, select={"code/ternary-and-or"}) == []


def test_nullable_type_annotations_not_ternary():
    content = (
        "метод Ф(П: Строка?, Д: Число?): Строка?\n"
        "    пер Х: Строка? = Неопределено\n"
        "    возврат Х\n"
        ";\n"
    )
    assert _lint("М.xbsl", content, select={"code/ternary-and-or"}) == []


def test_capitalized_keyword_used_as_identifier_balances():
    # 'Выбор' как имя переменной не должно считаться блоком выбор/case
    content = "метод Ф(): Число\n    знч Выбор = 1\n    возврат Выбор\n;\n"
    assert _lint("М.xbsl", content, select={"C"}) == []


def test_unused_local_flagged():
    content = "метод Ф(): Число\n    знч НеНужна = 5\n    знч Итог = 10\n    возврат Итог\n;\n"
    d = _lint("М.xbsl", content, select={"code/unused-local"})
    assert len(d) == 1 and "НеНужна" in d[0].message


def test_local_used_in_string_interpolation_not_flagged():
    content = 'метод Ф(): Строка\n    знч Кол = Считать()\n    возврат "загружено: %{Кол}"\n;\n'
    assert _lint("М.xbsl", content, select={"code/unused-local"}) == []


def test_unused_loop_var_flagged():
    content = "метод Ф(): Число\n    пер n = 0\n    для В из Коллекция\n        n = n + 1\n    ;\n    возврат n\n;\n"
    d = _lint("М.xbsl", content, select={"code/unused-loop-var"})
    assert len(d) == 1 and "'В'" in d[0].message


def test_used_loop_var_not_flagged():
    content = "метод Ф(): Число\n    пер s = 0\n    для В из Коллекция\n        s = s + В\n    ;\n    возврат s\n;\n"
    assert _lint("М.xbsl", content, select={"code/unused-loop-var"}) == []


# --- Тир A ---------------------------------------------------------------------------

def test_yaml_bad_uuid():
    d = _lint("О.yaml", "ВидЭлемента: Справочник\nИд: nope\nИмя: О\n", select={"yaml/id-uuid"})
    assert _has(d, "yaml/id-uuid")


def test_yaml_name_mismatch():
    d = _lint(
        "Имя.yaml",
        "ВидЭлемента: Справочник\nИд: 11111111-1111-1111-1111-111111111111\nИмя: Другое\n",
        select={"yaml/name-matches-file"},
    )
    assert _has(d, "yaml/name-matches-file")


def test_yaml_name_mismatch_with_trailing_comment():
    # комментарий после значения не мешает ни правилу, ни позиции на значении
    d = _lint(
        "Имя.yaml",
        "ВидЭлемента: Справочник\nИд: 11111111-1111-1111-1111-111111111111\nИмя: Другое # к\n",
        select={"yaml/name-matches-file"},
    )
    assert _has(d, "yaml/name-matches-file")
    assert (d[0].line, d[0].col) == (3, 6)


def test_yaml_structural_file_exempt():
    d = _lint("Подсистема.yaml", "Наименование: Тест\n", select={"A"})
    assert d == []


def test_id_unique_across_files(tmp_path):
    same = "ВидЭлемента: Справочник\nИд: 11111111-1111-1111-1111-111111111111\nИмя: {n}\n"
    (tmp_path / "a.yaml").write_text(same.format(n="a"), encoding="utf-8")
    (tmp_path / "b.yaml").write_text(same.format(n="b"), encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={"yaml/id-unique"})
    assert len([x for x in d if x.rule_id == "yaml/id-unique"]) == 2


def test_xbsl_pair(tmp_path):
    (tmp_path / "orphan.xbsl").write_text("метод Ф()\n;\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={"structure/xbsl-pair"})
    assert _has(d, "structure/xbsl-pair")
    (tmp_path / "orphan.yaml").write_text(
        "ВидЭлемента: Справочник\nИд: 22222222-2222-2222-2222-222222222222\nИмя: orphan\n",
        encoding="utf-8",
    )
    d2 = engine.run(discover([str(tmp_path)]), select={"structure/xbsl-pair"})
    assert not _has(d2, "structure/xbsl-pair")


# --- Тир D (семантика по stdlib) -----------------------------------------------------

def test_unknown_new_type_flagged(tmp_path):
    (tmp_path / "м.xbsl").write_text(
        "метод Ф(): Массив<Число>\n    знч x = новый Массв()\n    возврат x\n;\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert any(x.rule_id == "code/unknown-type" and "Массв" in x.message for x in d)


def test_known_new_type_not_flagged(tmp_path):
    # Массив – stdlib, Л – локальная структура; оба известны
    (tmp_path / "м.xbsl").write_text(
        "структура Л\n    пер a: Число\n;\n"
        "метод Ф(): Массив<Число>\n    знч x = новый Массив<Число>()\n"
        "    знч y = новый Л()\n    возврат x\n;\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert not _has(d, "code/unknown-type")


def test_unknown_type_in_annotation_flagged(tmp_path):
    (tmp_path / "м.xbsl").write_text(
        "структура С\n    пер поле: Стркоа\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert any(x.rule_id == "code/unknown-type" and "Стркоа" in x.message for x in d)


def test_unknown_type_in_return_flagged(tmp_path):
    (tmp_path / "м.xbsl").write_text(
        "метод Ф(): Стркоа\n    возврат ничто\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert any("Стркоа" in x.message for x in d)


def test_unknown_type_in_param_flagged(tmp_path):
    (tmp_path / "м.xbsl").write_text(
        "метод Ф(Значение: Стркоа): Число\n    возврат 0\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert any("Стркоа" in x.message for x in d)


def test_unknown_type_in_cast_flagged(tmp_path):
    (tmp_path / "м.xbsl").write_text(
        "метод Ф(): Число\n    возврат Данные как Стркоа\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert any("Стркоа" in x.message for x in d)


def test_entity_root_known_by_its_facets(tmp_path):
    # у Сущность нет своей страницы в доках, но её фасеты задокументированы - тип известен
    (tmp_path / "м.xbsl").write_text(
        "метод Ф(Ссылка: Сущность.Ключ): Число\n    возврат 1\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert not [x for x in d if "Сущность" in x.message]


def test_qualified_type_judged_by_last_segment(tmp_path):
    # квалифицированное имя: значим тип, пространство имён лишь говорит, где он лежит
    (tmp_path / "м.xbsl").write_text(
        "метод Ф(): Число\n"
        "    знч x = новый Массив<acme::Проект::Подсистема::Стркоа>()\n"
        "    возврат x.Количество()\n;\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert not [x for x in d if "acme" in x.message]
    assert [x for x in d if "Стркоа" in x.message]


def test_query_alias_not_a_cast(tmp_path):
    # внутри Запрос{...} КАК – псевдоним колонки языка запросов, а не приведение к типу
    (tmp_path / "м.xbsl").write_text(
        "метод Ф(): Число\n"
        "    знч Запрос = Запрос{\n"
        "        ВЫБРАТЬ\n"
        "            Количество(Идентификатор) как Количество\n"
        "        ИЗ\n"
        "            Товар\n"
        "    }\n"
        "    возврат Запрос.Выполнить().ЕдинственныйИлиНеопределено().Количество\n"
        ";\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert not [x for x in d if "Количество" in x.message]


def test_generic_arg_unknown_flagged(tmp_path):
    # база (Массив) известна, аргумент (Стркоа) – нет
    (tmp_path / "м.xbsl").write_text(
        "структура С\n    пер список: Массив<Стркоа>\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    msgs = [x.message for x in d if x.rule_id == "code/unknown-type"]
    assert any("Стркоа" in m for m in msgs) and not any("Массив" in m for m in msgs)


def test_fqn_tail_not_flagged(tmp_path):
    # корень FQN (локальная структура Кэш) известен; вложенный хвост не резолвится и не шумит
    (tmp_path / "м.xbsl").write_text(
        "структура Кэш\n    пер a: Число\n;\n"
        "метод Ф(): Кэш.СтрокаДанных?\n    возврат ничто\n;\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert not _has(d, "code/unknown-type")


def test_unknown_type_in_catch_flagged(tmp_path):
    (tmp_path / "м.xbsl").write_text(
        "метод Ф()\n    поймать Ошибка: НетТакого\n        ;\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert any("НетТакого" in x.message for x in d)


def test_known_type_in_catch_not_flagged(tmp_path):
    (tmp_path / "м.xbsl").write_text(
        "метод Ф()\n    поймать Ошибка: Исключение\n        ;\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert not _has(d, "code/unknown-type")


def test_catch_unknown_keyword_type_not_flagged(tmp_path):
    # 'неизвестно' – ключевое слово-тип (any), корня-идентификатора нет: не шумим
    (tmp_path / "м.xbsl").write_text(
        "метод Ф()\n    поймать Исключение: неизвестно\n        ;\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert not _has(d, "code/unknown-type")


def test_multi_name_declaration_flagged(tmp_path):
    # список имён через запятую с общим типом – тип проверяется
    (tmp_path / "м.xbsl").write_text(
        "метод Ф()\n    знч a, b: НетТакого\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert any("НетТакого" in x.message for x in d)


def test_multi_name_declaration_known_not_flagged(tmp_path):
    (tmp_path / "м.xbsl").write_text(
        "метод Ф()\n    знч a, b: Число\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-type"})
    assert not _has(d, "code/unknown-type")


# --- Тир D (типы, порождаемые объектами проекта) --------------------------------------

_ТОВАРЫ_YAML = "ВидЭлемента: Справочник\nИмя: Товары\nТабличныеЧасти:\n    -\n        Имя: Состав\n"


def _товары(tmp_path, code, module="метод М()\n;\n"):
    (tmp_path / "Товары.yaml").write_text(_ТОВАРЫ_YAML, encoding="utf-8")
    (tmp_path / "Товары.xbsl").write_text(module, encoding="utf-8")
    (tmp_path / "м.xbsl").write_text(code, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={"code/unknown-object-type"})


def test_object_derived_type_not_flagged(tmp_path):
    d = _товары(tmp_path, "метод Ф(Т: Товары.Ссылка): Товары.Объект?\n    возврат ничто\n;\n")
    assert not _has(d, "code/unknown-object-type")


def test_object_derived_type_typo_flagged(tmp_path):
    d = _товары(tmp_path, "метод Ф(Т: Товары.Сылка)\n;\n")
    assert any(x.rule_id == "code/unknown-object-type" and "Товары.Сылка" in x.message for x in d)


def test_object_tabular_section_not_flagged(tmp_path):
    d = _товары(tmp_path, "метод Ф(Строки: Массив<Товары.Состав>)\n;\n")
    assert not _has(d, "code/unknown-object-type")


def test_object_tabular_section_typo_flagged(tmp_path):
    d = _товары(tmp_path, "метод Ф(Строки: Массив<Товары.Соства>)\n;\n")
    assert any("Товары.Соства" in x.message for x in d)


def test_object_module_structure_not_flagged(tmp_path):
    # структура объявлена в модуле объекта и использована из другого модуля квалифицированно
    d = _товары(
        tmp_path,
        "метод Ф(): Товары.Сводка?\n    возврат ничто\n;\n",
        module="структура Сводка\n    пер Всего: Число\n;\n",
    )
    assert not _has(d, "code/unknown-object-type")


def test_object_submodule_structure_not_flagged(tmp_path):
    # структура из модуля объекта (файл <Имя>.Объект.xbsl) тоже входит в семейство типов
    (tmp_path / "Товары.Объект.xbsl").write_text(
        "структура Черновик\n    пер a: Число\n;\n", encoding="utf-8",
    )
    d = _товары(tmp_path, "метод Ф(Ч: Товары.Черновик)\n;\n")
    assert not _has(d, "code/unknown-object-type")


def test_unchecked_kind_skipped(tmp_path):
    # вид вне проверяемого списка – хвосты не проверяются
    (tmp_path / "Настройки.yaml").write_text(
        "ВидЭлемента: Роль\nИмя: Настройки\n", encoding="utf-8",
    )
    (tmp_path / "м.xbsl").write_text("метод Ф(Н: Настройки.ЧтоУгодно)\n;\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={"code/unknown-object-type"})
    assert not _has(d, "code/unknown-object-type")


def test_cast_then_call_chain_not_merged(tmp_path):
    # `как Товары` в конце выражения + вызов метода со следующей строки: точка вызова
    # не продолжает цепочку типа – ложного 'Товары.Записать' быть не должно
    d = _товары(
        tmp_path,
        "метод Ф(Б: Товары.Объект)\n    знч А = Б как Товары\n    Хранилище.Записать(А)\n;\n",
    )
    assert not _has(d, "code/unknown-object-type")


def test_object_member_family_from_catalog():
    # каталог версии несёт порождаемые члены по видам (object_members из дистрибутива);
    # страховочное объединение дополняет их членами без шаблонных страниц
    from xbsl.rules.semantics import _checked_kinds, _member_family
    family = _member_family("Справочник")
    assert {"Ссылка", "Объект", "СоздатьОбъект", "АвтоматическаяФормаСписка"} <= family
    assert "ПараметрыЗаполнения" in family  # только из страховочного списка
    assert "Обработка" in _checked_kinds()  # вид добавлен данными каталога


# --- Тир D (типы в yaml) --------------------------------------------------------------

def _товары_yaml(tmp_path, form_yaml):
    (tmp_path / "Товары.yaml").write_text(_ТОВАРЫ_YAML, encoding="utf-8")
    (tmp_path / "Товары.xbsl").write_text("структура Сводка\n    пер Всего: Число\n;\n", encoding="utf-8")
    (tmp_path / "Ф.yaml").write_text(form_yaml, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={"yaml/unknown-type"})


def test_yaml_type_known_not_flagged(tmp_path):
    d = _товары_yaml(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n    Тип: ФормаОбъекта<Товары.Объект>\n"
        "Содержимое:\n    -\n        Тип: ПолеВвода<Товары.Ссылка?>\n    -\n        Тип: Группа\n",
    )
    assert not _has(d, "yaml/unknown-type")


def test_yaml_type_unknown_root_flagged(tmp_path):
    d = _товары_yaml(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n    -\n        Тип: Групппа\n",
    )
    assert any(x.rule_id == "yaml/unknown-type" and "Групппа" in x.message for x in d)


def test_yaml_type_member_typo_flagged(tmp_path):
    d = _товары_yaml(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n    -\n        Тип: ПолеВвода<Товары.Сылка?>\n",
    )
    assert any("Товары.Сылка" in x.message for x in d)
    line = next(x for x in d if "Товары.Сылка" in x.message)
    assert line.line == 5  # позиция строки со значением


def test_yaml_type_union_and_nullable(tmp_path):
    d = _товары_yaml(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n    -\n        Тип: ПолеВвода<Булево|Число|Строка|ДатаВремя|?>\n",
    )
    assert not _has(d, "yaml/unknown-type")


def test_yaml_type_attribute_and_tc(tmp_path):
    # реквизит с опечаткой в типе флагается, табличная часть и структура модуля - нет
    yaml_text = (
        "ВидЭлемента: Справочник\nИмя: Склады\nРеквизиты:\n"
        "    -\n        Имя: Основной\n        Тип: Товары.Ссылка?\n"
        "    -\n        Имя: Сломанный\n        Тип: Товары.Сылка?\n"
        "    -\n        Имя: Сострукт\n        Тип: Массив<Товары.Сводка>\n"
    )
    d = _товары_yaml(tmp_path, yaml_text)
    msgs = [x for x in d if x.rule_id == "yaml/unknown-type"]
    assert len(msgs) == 1 and "Товары.Сылка" in msgs[0].message


def test_yaml_type_automatic_list_form(tmp_path):
    d = _товары_yaml(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n    -\n"
        "        Тип: СтандартнаяКолонкаТаблицы<СтрокаДинамическогоСписка<Товары.АвтоматическаяФормаСписка.ДанныеСтрокиСписка>>\n",
    )
    assert not _has(d, "yaml/unknown-type")


def test_yaml_type_block_scalar_not_scanned(tmp_path):
    # строка 'Тип: Ерунда' внутри литерального блока - текст, а не тип
    d = _товары_yaml(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nОписание: |\n    Тип: Ерунда\n",
    )
    assert not _has(d, "yaml/unknown-type")


def test_yaml_type_non_element_file_skipped(tmp_path):
    (tmp_path / "конфиг.yaml").write_text("Тип: Ерунда\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={"yaml/unknown-type"})
    assert not _has(d, "yaml/unknown-type")


# --- Тир D (значения перечислений) ----------------------------------------------------

_ВИД_YAML = (
    "ВидЭлемента: Перечисление\nИмя: ВидСообщения\nЭлементы:\n"
    "    -\n        Имя: Важное\n    -\n        Имя: Обычное\n"
)


def _вид(tmp_path, code=None, extra_yaml=None):
    (tmp_path / "ВидСообщения.yaml").write_text(_ВИД_YAML, encoding="utf-8")
    if code is not None:
        (tmp_path / "м.xbsl").write_text(code, encoding="utf-8")
    if extra_yaml is not None:
        (tmp_path / "Ф.yaml").write_text(extra_yaml, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={"code/unknown-enum-value"})


def test_enum_value_known_not_flagged(tmp_path):
    d = _вид(tmp_path, "метод Ф(): ВидСообщения\n    возврат ВидСообщения.Важное\n;\n")
    assert not _has(d, "code/unknown-enum-value")



def test_enum_module_method_not_a_value(tmp_path):
    # у перечисления есть парный модуль: ВидСообщения.ПолучитьЗаголовок(...) - вызов, не значение
    (tmp_path / "ВидСообщения.xbsl").write_text(
        "статический метод ПолучитьЗаголовок(Вид: ВидСообщения): Строка\n"
        "    возврат Вид.Представление()\n;\n",
        encoding="utf-8",
    )
    d = _вид(
        tmp_path,
        "метод Ф(): Строка\n"
        "    возврат ВидСообщения.ПолучитьЗаголовок(ВидСообщения.Важное)\n;\n",
    )
    assert not _has(d, "code/unknown-enum-value")


def test_enum_type_object_members_not_values(tmp_path):
    # имя перечисления - это ещё и тип-объект Стд::Тип<>: ПоИмени и Элементы - его члены
    d = _вид(
        tmp_path,
        "метод Ф(): ВидСообщения\n"
        "    знч Все = ВидСообщения.Элементы()\n"
        '    возврат ВидСообщения.ПоИмени("Важное")\n;\n',
    )
    assert not _has(d, "code/unknown-enum-value")


def test_enum_value_typo_flagged(tmp_path):
    d = _вид(tmp_path, "метод Ф(): ВидСообщения\n    возврат ВидСообщения.Важнейшее\n;\n")
    assert any(x.rule_id == "code/unknown-enum-value" and "Важнейшее" in x.message for x in d)


def test_enum_builtin_member_not_flagged(tmp_path):
    d = _вид(tmp_path, "метод Ф(): Строка\n    возврат ВидСообщения.Важное.Представление()\n;\n")
    assert not _has(d, "code/unknown-enum-value")


def test_enum_shadowed_name_skipped(tmp_path):
    # локальная переменная затеняет перечисление - файл не проверяется по этому имени
    d = _вид(
        tmp_path,
        "метод Ф(Данные: Структура): Строка\n"
        "    знч ВидСообщения = Данные.Вид\n    возврат ВидСообщения.Что\n;\n",
    )
    assert not _has(d, "code/unknown-enum-value")


def test_enum_member_assignment_not_shadowing(tmp_path):
    # присваивание реквизита 'Объект.ВидСообщения = ...' затенением не считается
    d = _вид(
        tmp_path,
        "метод Ф(Объект: Структура)\n    Объект.ВидСообщения = ВидСообщения.Важнейшее\n;\n",
    )
    assert any("Важнейшее" in x.message for x in d)


def test_enum_member_of_other_object_not_flagged(tmp_path):
    # 'Данные.ВидСообщения.Что' - обращение к полю, корень не перечисление
    d = _вид(tmp_path, "метод Ф(Данные: Структура): Строка\n    возврат Данные.ВидСообщения.Что\n;\n")
    assert not _has(d, "code/unknown-enum-value")


def test_enum_in_query_not_scanned(tmp_path):
    d = _вид(
        tmp_path,
        "метод Ф(): Число\n    знч Р = Запрос{\n        ВЫБРАТЬ ВидСообщения.Ерунда ИЗ Т\n    }\n    возврат 0\n;\n",
    )
    assert not _has(d, "code/unknown-enum-value")


def test_enum_yaml_binding_typo_flagged(tmp_path):
    d = _вид(
        tmp_path,
        extra_yaml=(
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n    -\n"
            "        Тип: Надпись\n        Видимость: '=Вид == ВидСообщения.Важнейшее'\n"
        ),
    )
    assert any(x.rule_id == "code/unknown-enum-value" and "Важнейшее" in x.message for x in d)
    assert next(x for x in d if "Важнейшее" in x.message).line == 6


def test_enum_yaml_binding_known_not_flagged(tmp_path):
    d = _вид(
        tmp_path,
        extra_yaml=(
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nСодержимое:\n    -\n"
            "        Тип: Надпись\n        Видимость: '=Вид == ВидСообщения.Важное'\n"
        ),
    )
    assert not _has(d, "code/unknown-enum-value")


def test_enum_yaml_field_named_as_enum_skipped(tmp_path):
    # у формы есть реквизит с именем перечисления - биндинги файла не проверяются по нему
    d = _вид(
        tmp_path,
        extra_yaml=(
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nРеквизиты:\n    -\n"
            "        Имя: ВидСообщения\n        Тип: Строка\n"
            "Содержимое:\n    -\n        Тип: Надпись\n"
            "        Значение: '=ВидСообщения.Чтото'\n"
        ),
    )
    assert not _has(d, "code/unknown-enum-value")


# --- Тир D (обработчики форм) --------------------------------------------------------

def test_handler_missing_flagged(tmp_path):
    (tmp_path / "Ф.yaml").write_text("Обработчик: НетТакого\n", encoding="utf-8")
    (tmp_path / "Ф.xbsl").write_text("метод Другой()\n;\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={"form/unknown-handler"})
    assert any(x.rule_id == "form/unknown-handler" and "НетТакого" in x.message for x in d)


def test_handler_trailing_comment_flagged(tmp_path):
    # хвостовой комментарий - не часть значения и не повод молчать
    (tmp_path / "Ф.yaml").write_text("Обработчик: НетТакого # комментарий\n", encoding="utf-8")
    (tmp_path / "Ф.xbsl").write_text("метод Другой()\n;\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={"form/unknown-handler"})
    assert any(x.rule_id == "form/unknown-handler" and "НетТакого" in x.message for x in d)


def test_handler_present_not_flagged(tmp_path):
    (tmp_path / "Ф.yaml").write_text("ПриНажатии: Клик\n", encoding="utf-8")
    (tmp_path / "Ф.xbsl").write_text("метод Клик()\n;\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={"form/unknown-handler"})
    assert not _has(d, "form/unknown-handler")


def test_handler_fqn_not_flagged(tmp_path):
    # значение с точкой – ссылка на внешний модуль, не судим
    (tmp_path / "Ф.yaml").write_text("Обработчик: Общий.Метод\n", encoding="utf-8")
    (tmp_path / "Ф.xbsl").write_text("метод Клик()\n;\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={"form/unknown-handler"})
    assert not _has(d, "form/unknown-handler")


def test_handler_no_pair_module_not_flagged(tmp_path):
    # форма без парного модуля – резолвить не из чего, молчим
    (tmp_path / "Ф.yaml").write_text("Обработчик: Клик\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={"form/unknown-handler"})
    assert not _has(d, "form/unknown-handler")


# --- Тир D (свойства объектов по метамодели) -----------------------------------------

def test_unknown_property_flagged():
    content = (
        "ВидЭлемента: Справочник\n"
        "Ид: 11111111-1111-1111-1111-111111111111\n"
        "Имя: Товары\n"
        "Заголовок: Лишнее\n"  # свойство компонента, недопустимое у справочника
    )
    d = _lint("Товары.yaml", content, select={"yaml/unknown-property"})
    assert any(x.rule_id == "yaml/unknown-property" and "Заголовок" in x.message for x in d)


def test_known_property_not_flagged():
    content = (
        "ВидЭлемента: Справочник\n"
        "Ид: 11111111-1111-1111-1111-111111111111\n"
        "Имя: Товары\n"
        "Реквизиты:\n"
    )
    d = _lint("Товары.yaml", content, select={"yaml/unknown-property"})
    assert not _has(d, "yaml/unknown-property")


def test_unverified_vid_not_flagged():
    # вид не в vid2class метамодели – объект не проверяется (0 ложных на непроверенном)
    content = (
        "ВидЭлемента: РегистрНакопления\n"
        "Ид: 11111111-1111-1111-1111-111111111111\n"
        "Имя: Остатки\n"
        "ЧтоТоЛевое: 1\n"
    )
    d = _lint("Остатки.yaml", content, select={"yaml/unknown-property"})
    assert not _has(d, "yaml/unknown-property")


# Четыре ложных срабатывания code/blocks, найденные на боевом корпусе БизКуба (17.07.2026):
# правило считало блоки по СЫРЫМ токенам и не знало трёх конструкций языка.


@pytest.mark.needs_data
def test_blocks_batch_query_semicolon_is_not_a_block_close():
    # ';' внутри Запрос{...} - разделитель ПАКЕТНОГО запроса, а не закрытие блока
    content = (
        "метод Ф(): Массив<Строка>\n"
        "    знч Запрос = Запрос{\n"
        "        ВЫБРАТЬ Ид ПОМЕСТИТЬ вт_Ид ИЗ Приложения\n"
        "        ;\n"
        "        ВЫБРАТЬ URI ИЗ вт_Ид\n"
        "    }\n"
        "    возврат новый Массив<Строка>()\n"
        ";\n"
    )
    assert _lint("М.xbsl", content, select={"code/blocks"}) == []


@pytest.mark.needs_data
def test_blocks_constructor_marker_opens_nothing():
    # `конструктор` в структуре - маркер настройки конструктора, тела и ';' у него нет
    content = (
        "структура Т\n"
        "    пер Х: Число\n"
        "    @ИменованныеПараметры\n"
        "    конструктор\n"
        ";\n"
    )
    assert _lint("М.xbsl", content, select={"code/blocks"}) == []


@pytest.mark.needs_data
def test_blocks_abstract_method_has_no_body():
    content = "@НаСервере\nабстрактный метод Ф(): Число\n\nметод Г()\n;\n"
    assert _lint("М.xbsl", content, select={"code/blocks"}) == []


@pytest.mark.needs_data
def test_blocks_scope_is_a_block():
    # `область` закрывается ';' наравне с прочими блоками
    valid = "метод Ф()\n    область\n        Г()\n    ;\n;\n"
    assert _lint("М.xbsl", valid, select={"code/blocks"}) == []
    broken = "метод Ф()\n    область\n        Г()\n;\n"
    assert _has(_lint("М.xbsl", broken, select={"code/blocks"}), "code/blocks")


@pytest.mark.needs_data
def test_trailing_blank_line_message():
    # строка из одних пробелов - тот же фикс, но сообщение про пустую строку, а не про
    # "хвост в конце строки" (на такой строке кода нет вовсе)
    d = _lint("М.xbsl", "метод Ф()\n    Г()   \n        \n;\n", select={"whitespace/trailing"})
    msgs = {x.line: x.message for x in d}
    assert "Хвостовые" in msgs[2]
    assert "только из пробелов" in msgs[3]
