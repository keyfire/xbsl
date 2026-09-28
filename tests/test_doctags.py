"""The two readings of a documentation comment block (xbsl/doctags.py).

`environment_model` is a port of the environment's own parser and keeps its quirks - a tag on
the first line is the description, a name ends at the first character outside its class, an
unknown tag loses its line. `parse` reads the block line by line and keeps positions. Neither
needs the data bundle.
"""

from xbsl import doctags


def _lines(*texts: str) -> list[doctags.DocLine]:
    out = []
    offset = 0
    for number, raw in enumerate(texts, start=1):
        out.append(doctags.doc_line(number, 1, offset, raw))
        offset += len(raw) + 1
    return out


_BLOCK = (
    "/// Вычисляет площадь прямоугольника.",
    "///",
    "/// @параметр Длина - Длина прямоугольника.",
    "/// @параметр Ширина - Ширина прямоугольника,",
    "///   и еще одна строка ширины.",
    "///",
    "/// @возвращает Площадь прямоугольника.",
    "/// @выбрасывает ИсключениеНедопустимыйАргумент - если стороны отрицательные.",
    "/// @см Геометрия.ПлощадьКруга",
)


def test_environment_model_of_a_well_formed_block():
    block = doctags.parse(_lines(*_BLOCK))
    model = block.model()
    assert model.description == "Вычисляет площадь прямоугольника."
    assert [name for name, _text in model.params] == ["Длина", "Ширина"]
    assert model.param("Ширина") == "Ширина прямоугольника,\n  и еще одна строка ширины."
    assert model.returns == "Площадь прямоугольника."
    assert model.throws == (("ИсключениеНедопустимыйАргумент", "если стороны отрицательные."),)
    assert model.see == ("Геометрия.ПлощадьКруга",)


def test_english_spellings_are_tags_too():
    model = doctags.environment_model(
        "Sums two numbers.\n\n@parameter A - The first.\n@parameter B - The second.\n"
        "@returns The sum.\n@throws ArgumentError - never.\n@see Math.Sum"
    )
    assert [name for name, _ in model.params] == ["A", "B"]
    assert model.returns == "The sum."
    assert model.throws == (("ArgumentError", "never."),)
    assert model.see == ("Math.Sum",)


def test_a_tag_on_the_first_line_is_the_description():
    model = doctags.environment_model("@параметр А - первый\n@параметр Б - второй")
    assert model.description == "@параметр А - первый"
    assert model.params == (("Б", "второй"),)


def test_a_name_ends_at_an_underscore_a_dot_and_a_lowercase_yo():
    model = doctags.environment_model(
        "Описание\n@параметр Мой_Параметр - текст\n@параметр Счётчик - т\n"
        "@выбрасывает Модуль.Ошибка - текст"
    )
    assert model.params == (("Мой", "_Параметр - текст"), ("Сч", "ётчик - т"))
    assert model.throws == (("Модуль", ".Ошибка - текст"),)
    tag = doctags.parse(_lines("/// Описание", "/// @параметр Мой_Параметр - текст")).tags[0]
    assert (tag.name, tag.environment_name) == ("Мой_Параметр", "Мой")


def test_an_unknown_tag_ends_the_description_and_is_lost():
    model = doctags.environment_model("Описание.\n@param Имя - текст\nпродолжение")
    assert model.description == "Описание."
    assert model.params == () and model.see == () and model.returns == ""


def test_an_empty_result_tag_swallows_the_next_tag_line():
    model = doctags.environment_model("Описание\n@возвращает\n@см Модуль.Метод")
    assert model.returns == "@см Модуль.Метод"
    assert model.see == ()


def test_two_result_tags_are_glued_without_a_blank():
    model = doctags.environment_model("Описание\n@возвращает Одно.\n@возвращает Другое.")
    assert model.returns == "Одно.Другое."


def test_a_capitalized_keyword_is_no_tag():
    model = doctags.environment_model("Описание\n@Параметр Имя - текст")
    assert model.params == ()


def test_parse_keeps_positions_and_continuations():
    block = doctags.parse(_lines(*_BLOCK))
    kinds = [(tag.kind, tag.index, tag.last) for tag in block.tags]
    assert kinds == [("param", 2, 2), ("param", 3, 5), ("returns", 6, 6), ("throws", 7, 7),
                     ("see", 8, 8)]
    assert block.description_end == 2
    width = block.tags[1]
    line = block.lines[width.index]
    assert line.text[width.keyword_at] == "@"
    assert line.text[width.name_at:width.name_at + len("Ширина")] == "Ширина"
    assert (width.dash, line.text[width.dash_at]) == ("-", "-")
    assert width.text.startswith("Ширина прямоугольника,")
    # The text of a DocLine starts after `/// `: the offset and the column point at it.
    assert (line.offset, line.column) == (sum(len(raw) + 1 for raw in _BLOCK[:3]) + 4, 5)


def test_parse_reads_an_unknown_tag_and_a_dash_of_another_kind():
    block = doctags.parse(_lines(
        "/// Описание.", "///", "/// @param Имя - текст", "/// @параметр Код \u2013 текст",
    ))
    unknown, param = block.tags
    assert (unknown.kind, unknown.keyword) == (None, "param")
    assert (param.kind, param.name, param.dash) == ("param", "Код", "\u2013")
    assert param.text == "текст"


def test_marker_cut_takes_one_blank_only():
    assert doctags.strip_marker("    ///   отступ") == "  отступ"
    assert doctags.strip_marker("////рамка") == "/рамка"


def test_render_markdown_follows_the_environment_card():
    text = doctags.render_markdown(doctags.parse(_lines(*_BLOCK)).model())
    assert text.startswith("Вычисляет площадь прямоугольника.\n\n**Параметры:**\n\n- **Длина** - ")
    assert "**Возвращает:** Площадь прямоугольника." in text
    assert "**Выбрасывает:**\n\n- **ИсключениеНедопустимыйАргумент** - " in text
    assert text.endswith("**Смотреть также:** Геометрия.ПлощадьКруга")
    english = doctags.render_markdown(doctags.environment_model("Sums.\n@returns The sum."), "en")
    assert english == "Sums.\n\n**Returns:** The sum."


def test_render_markdown_of_a_plain_description():
    assert doctags.render_markdown(doctags.environment_model("Только описание.")) == (
        "Только описание."
    )
    assert doctags.render_markdown(doctags.environment_model("")) == ""
