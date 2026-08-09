"""The variable-and-constant-names standard rules (style_variables).

For every rule both sides are checked: firing on the standard's own "wrong" examples and
silence on its "right" ones - including the standard's explicit exceptions (short lambda
parameters, structure fields as a serialization contract, universal stems inside longer
names). The rules need no Element data, so the module runs in the public CI too
(the shadow rule reads the yaml kind as written - Russian kinds resolve without data).
"""

from xbsl import engine


def _lint(content, rule_id, name="М.xbsl"):
    return engine.run_sources([engine.load_text(name, content)], select={rule_id})


def _clean(content, rule_id, name="М.xbsl"):
    return _lint(content, rule_id, name) == []


# --- style/abstract-name ---------------------------------------------------------------

def test_abstract_name_flagged():
    d = _lint("метод Ф()\n    знч Данные = 1\n;\n", "style/abstract-name")
    assert len(d) == 1 and d[0].line == 2 and "Данные" in d[0].message


def test_abstract_name_numbered_flagged():
    # 1.5: a digit instead of a meaningful qualifier (Данные1, Значение2).
    d = _lint("метод Ф()\n    знч Данные2 = 1\n;\n", "style/abstract-name")
    assert len(d) == 1 and "уточнени" in d[0].message


def test_abstract_name_parameter_flagged():
    d = _lint("метод Ф(Значение: Число)\n;\n", "style/abstract-name")
    assert len(d) == 1 and "Значение" in d[0].message


def test_abstract_name_loop_flagged():
    d = _lint("метод Ф()\n    для Строка из Таблица\n    ;\n;\n", "style/abstract-name")
    assert len(d) == 1 and "Строка" in d[0].message


def test_abstract_stem_inside_longer_name_ok():
    # The stem must stand alone: ДанныеКлиента is the standard's own "right" example.
    assert _clean("метод Ф()\n    знч ДанныеКлиента = 1\n;\n", "style/abstract-name")


def test_abstract_name_structure_field_ok():
    # A structure field is a serialization contract, not a naming choice.
    src = "структура Ответ\n    пер Данные: Строка\n;\n"
    assert _clean(src, "style/abstract-name")


def test_abstract_name_constant_ok():
    # Constants live under their own rules; ДАННЫЕ is not a variable.
    assert _clean("конст ДАННЫЕ = 1\n", "style/abstract-name")


# --- style/single-letter-name ----------------------------------------------------------

def test_single_letter_variable_flagged():
    d = _lint("метод Ф()\n    знч О = 1\n;\n", "style/single-letter-name")
    assert len(d) == 1 and "'О'" in d[0].message


def test_single_letter_loop_flagged():
    # The standard's own wrong example is `для И = 0`; И lexes as a keyword, so the
    # nearest real-world case is any other letter.
    d = _lint("метод Ф()\n    для К = 0 по 5\n        Сообщить(К)\n    ;\n;\n",
              "style/single-letter-name")
    assert len(d) == 1 and d[0].line == 2


def test_single_letter_parameter_flagged():
    d = _lint("метод Ф(С: Строка)\n;\n", "style/single-letter-name")
    assert len(d) == 1


def test_single_letter_lambda_parameter_ok():
    # The standard's explicit exception: short lambdas use one-letter capital parameters.
    src = "метод Ф()\n    знч Итог = Задачи.Фильтровать(З -> З.Статус)\n;\n"
    assert _clean(src, "style/single-letter-name")


def test_single_letter_typed_lambda_parameters_ok():
    src = "метод Ф()\n    знч Сумматор = метод(А: Число, Б: Число) -> возврат А + Б\n;\n"
    assert _clean(src, "style/single-letter-name")


def test_two_letter_name_ok():
    # Two letters are not a single letter: the length boundary stays exact.
    assert _clean("метод Ф()\n    знч Ид = 1\n;\n", "style/single-letter-name")


# --- style/negated-boolean-name --------------------------------------------------------

def test_negated_boolean_annotation_flagged():
    d = _lint("метод Ф()\n    пер НеПодключен: Булево\n;\n", "style/negated-boolean-name")
    assert len(d) == 1 and "Подключен" in d[0].message


def test_negated_boolean_literal_flagged():
    d = _lint("метод Ф()\n    знч НетОшибок = Истина\n;\n", "style/negated-boolean-name")
    assert len(d) == 1


def test_negated_boolean_nullable_flagged():
    d = _lint("метод Ф()\n    пер НеАктивен: Булево?\n;\n", "style/negated-boolean-name")
    assert len(d) == 1


def test_negated_boolean_parameter_flagged():
    d = _lint("метод Ф(НеВиден: Булево)\n;\n", "style/negated-boolean-name")
    assert len(d) == 1


def test_negated_name_without_boolean_type_ok():
    # НеПрочитанные may be a perfectly good array - the type must be certain.
    assert _clean("метод Ф()\n    знч НеПрочитанные = ПолучитьМассив()\n;\n",
                  "style/negated-boolean-name")


def test_negation_lookalike_word_ok():
    # Неделя and Нетто only start with the same letters.
    assert _clean("метод Ф()\n    знч Неделя = Истина\n;\n", "style/negated-boolean-name")


def test_affirmative_boolean_ok():
    assert _clean("метод Ф()\n    знч ЕстьОшибки = Ложь\n;\n", "style/negated-boolean-name")


# --- style/type-in-name ----------------------------------------------------------------

def test_type_in_name_flagged():
    # The standard's own wrong example: МассивСтруктурИмен instead of Имена.
    d = _lint("метод Ф()\n    знч МассивСтруктурИмен = []\n;\n", "style/type-in-name")
    assert len(d) == 1 and "Массив" in d[0].message


def test_type_in_name_structure_prefix_flagged():
    d = _lint("метод Ф()\n    знч СтруктураОтвета = Разобрать()\n;\n", "style/type-in-name")
    assert len(d) == 1


def test_type_word_alone_not_matched():
    # The prefix must be followed by a capital: a bare Массив is a shadow problem,
    # not a type-in-name one, and lowercase continuations are ordinary words.
    assert _clean("метод Ф()\n    знч Массивы = []\n;\n", "style/type-in-name")


# --- style/numeral-in-const-name -------------------------------------------------------

def test_numeral_in_const_name_flagged():
    # The standard's own wrong example: конст ТАЙМАУТ_ОДНА_МИНУТА = 1м.
    d = _lint("конст ТАЙМАУТ_ОДНА_МИНУТА = 60\n", "style/numeral-in-const-name")
    assert len(d) == 1 and "ОДНА" in d[0].message


def test_abstract_const_name_ok():
    assert _clean("конст ТАЙМАУТ = 60\n", "style/numeral-in-const-name")


def test_numeral_substring_not_matched():
    # The numeral must be a whole word between underscores: СЕМЬЯ is not СЕМЬ.
    assert _clean("конст КОД_СЕМЬИ = 1\n", "style/numeral-in-const-name")


# --- style/shadow-project-name ---------------------------------------------------------

_OBJECT_YAML = "ВидЭлемента: Модуль\nИд: 11111111-1111-1111-1111-111111111111\nИмя: Задачи\n"


def _project(module_source):
    return engine.run_sources(
        [
            engine.load_text("Задачи.yaml", _OBJECT_YAML),
            engine.load_text("Меню.xbsl", module_source),
        ],
        select={"style/shadow-project-name"},
    )


def test_shadow_project_name_variable_flagged():
    d = _project("метод Ф()\n    знч Задачи = 1\n;\n")
    assert len(d) == 1 and d[0].line == 2 and "Задачи" in d[0].message
    assert str(d[0].path).endswith("Меню.xbsl")


def test_shadow_project_name_parameter_flagged():
    d = _project("метод Ф(Задачи: Число)\n;\n")
    assert len(d) == 1


def test_shadow_project_name_method_flagged():
    d = _project("метод Задачи()\n;\n")
    assert len(d) == 1


def test_other_names_do_not_shadow():
    d = _project("метод Ф()\n    знч СписокПрограмм = 1\n;\n")
    assert d == []


def test_no_objects_no_shadow():
    d = engine.run_sources(
        [engine.load_text("Меню.xbsl", "метод Ф()\n    знч Задачи = 1\n;\n")],
        select={"style/shadow-project-name"},
    )
    assert d == []
