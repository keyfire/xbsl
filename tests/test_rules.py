"""Проверки правил тиров A/B/C через ядро."""

from xbsllint import engine
from xbsllint.cli import discover


def _lint(name, content, **kw):
    return engine.run_sources([engine.load_text(name, content)], **kw)


def _has(diags, rule_id):
    return any(d.rule_id == rule_id for d in diags)


# --- Тир B ---------------------------------------------------------------------------

def test_curly_quotes_flagged():
    d = _lint("М.xbsl", "// текст “в кавычках”\n", select={"typography/curly-quotes"})
    assert _has(d, "typography/curly-quotes")


def test_em_dash_off_by_default_then_selectable():
    content = "// длинное тире — здесь\n"
    assert _lint("М.xbsl", content) == []  # выключено по умолчанию
    d = _lint("М.xbsl", content, select={"typography/em-dash"})
    assert len(d) == 1 and d[0].severity.value == "info"


def test_trailing_whitespace():
    d = _lint("М.xbsl", "метод Ф()  \n;\n", select={"whitespace/trailing"})
    assert len(d) == 1


def test_task_number_in_comment():
    d = _lint("М.xbsl", "// см. SITE-482\n", select={"conventions/task-number"})
    assert len(d) == 1 and "SITE-482" in d[0].message


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


# --- Тир D (обработчики форм) --------------------------------------------------------

def test_handler_missing_flagged(tmp_path):
    (tmp_path / "Ф.yaml").write_text("Обработчик: НетТакого\n", encoding="utf-8")
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
