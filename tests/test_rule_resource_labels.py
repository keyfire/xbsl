"""code/resource-replace-absent and code/resource-label-unfilled: labels of a resource template.

A module reads the text of a resource file and replaces its labels; the rules evaluate that chain
on the file itself. The fixtures are small projects written to a temporary folder: the resource
keys resolve against the resources folder on disk. The rules parse the modules, so the tests need
the language data.
"""

from pathlib import Path

import pytest

from xbsl import engine, i18n, plugins

pytestmark = pytest.mark.needs_data

ABSENT = "code/resource-replace-absent"
UNFILLED = "code/resource-label-unfilled"
BASE = Path("Демо") / "Учет"

CARD = "/* Подстановки:\n   {{COLOR}} - цвет\n   {{OLD}} - прежняя метка */\n.card { color: {{COLOR}}; width: {{WIDTH}}; }\n"
BLOCK = "<!-- {{NOTE}} в комментарии не метка -->\n<div class=\"{{CLASS}}\">{{TITLE}}</div>\n"
PICTURE = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{{W}}\"><text>{{T}}</text></svg>\n"

READER = (
    "метод Текст(Путь: Строка): Строка\n"
    "    возврат ПакетРесурсов.Текущий().Получить(Путь).ОткрытьПотокЧтения().ПрочитатьКакСтроку()\n"
    ";\n"
)


def _write(root: Path, files: dict[str, str]) -> list[Path]:
    written = []
    for rel, text in files.items():
        path = root / BASE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    return written


def _project(root: Path, code: str, modules: dict[str, str] | None = None,
             extra: dict[str, str] | None = None) -> list[Path]:
    files = {
        "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
        "Задачи/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Задачи/Ресурсы/Макеты/card.css": CARD,
        "Задачи/Ресурсы/Макеты/block.html": BLOCK,
        "Задачи/Ресурсы/Макеты/picture.svg": PICTURE,
    }
    for name, text in {"Оформление": code, **(modules or {})}.items():
        files[f"Задачи/{name}.yaml"] = f"ВидЭлемента: ОбщийМодуль\nИмя: {name}\n"
        files[f"Задачи/{name}.xbsl"] = text
    files.update(extra or {})
    return [path for path in _write(root, files) if path.suffix in (".yaml", ".xbsl")]


def _lint(paths: list[Path]):
    return engine.run(paths, select={ABSENT, UNFILLED})


def _found(paths: list[Path]) -> list[tuple[str, str, int]]:
    return sorted((d.rule_id, Path(d.path).stem, d.line) for d in _lint(paths))


# --- what is reported -------------------------------------------------------------------------


def test_a_renamed_label_is_reported_at_the_replace_and_at_the_end_of_the_chain(tmp_path):
    code = (
        "метод Карточка(): Строка\n"
        "    возврат Ресурс{Макеты/card.css}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()\n"
        "        .Заменить(\"{{COLOR}}\", \"red\")\n"
        "        .Заменить(\"{{SIZE}}\", \"10px\")\n"
        ";\n"
    )
    found = sorted(_lint(_project(tmp_path, code)), key=lambda d: d.rule_id)

    assert [(d.rule_id, d.line, d.col, d.severity.value) for d in found] == [
        (UNFILLED, 2, 13, "warning"),
        (ABSENT, 4, 10, "warning"),
    ]
    absent, unfilled = found[1], found[0]
    assert "Макеты/card.css" in absent.message and "\"{{SIZE}}\"" in absent.message
    assert "{{WIDTH}}" in absent.message, "the label the chain leaves is named as a likely rename"
    assert "{{WIDTH}}" in unfilled.message and "{{SIZE}}" in unfilled.message


def test_a_label_only_in_a_comment_of_the_file_is_named_so(tmp_path):
    code = (
        "метод Карточка(): Строка\n"
        "    возврат Ресурс{Макеты/card.css}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()\n"
        "        .Заменить(\"{{COLOR}}\", \"red\").Заменить(\"{{WIDTH}}\", \"1px\")\n"
        "        .Заменить(\"{{OLD}}\", \"x\")\n"
        ";\n"
    )
    found = _lint(_project(tmp_path, code))

    assert [(d.rule_id, d.line) for d in found] == [(ABSENT, 4)]
    assert i18n.t(f"{ABSENT}.comment").strip() in found[0].message


def test_a_second_replace_of_the_same_label_changes_nothing(tmp_path):
    code = (
        "метод Картинка(): Строка\n"
        "    возврат Ресурс{Макеты/picture.svg}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()\n"
        "        .Заменить(\"{{W}}\", \"1\").Заменить(\"{{W}}\", \"2\").Заменить(\"{{T}}\", \"t\")\n"
        ";\n"
    )
    found = _lint(_project(tmp_path, code))

    assert [(d.rule_id, d.line, d.col) for d in found] == [(ABSENT, 3, 33)]
    assert i18n.t(f"{ABSENT}.earlier").strip() in found[0].message


def test_a_wrapper_over_the_package_read_is_followed_by_its_path(tmp_path):
    code = (
        "метод Блок(): Строка\n"
        "    возврат Чтение.Текст(\"Макеты/block.html\").Заменить(\"{{CLASS}}\", \"c\")\n"
        ";\n"
    )
    found = _found(_project(tmp_path, code, {"Чтение": READER}))

    assert found == [(UNFILLED, "Оформление", 2)], "the title is left unfilled"


def test_a_wrapper_of_a_folder_takes_the_name_into_its_path(tmp_path):
    wrappers = READER + (
        "\nметод Макет(Имя: Строка): Строка\n"
        "    возврат Текст(\"Макеты/%Имя\").Сократить()\n"
        ";\n"
    )
    code = (
        "метод Блок(): Строка\n"
        "    возврат Чтение.Макет(\"block.html\").Заменить(\"{{CLASS}}\", \"c\")"
        ".Заменить(\"{{TITLE}}\", \"t\").Заменить(\"{{NOTE}}\", \"n\")\n"
        ";\n"
    )
    found = _found(_project(tmp_path, code, {"Чтение": wrappers}))

    assert found == [(ABSENT, "Оформление", 2)], "a label in an html comment is no label"


def test_the_english_spelling_is_judged_as_well(tmp_path):
    code = (
        "method Picture(): String\n"
        "    return Resource{Макеты/picture.svg}.OpenReadableStream().ReadAsString()"
        ".Replace(\"{{W}}\", \"1\")\n"
        ";\n"
    )
    assert _found(_project(tmp_path, code)) == [(UNFILLED, "Оформление", 2)]


def test_a_map_filled_from_a_literal_list_of_paths_is_read_by_its_key(tmp_path):
    maps = READER + (
        "\nметод Все(): Соответствие<Строка, Строка>\n"
        "    пер Файлы = новый Соответствие<Строка, Строка>()\n"
        "    для Имя из [\"card.css\", \"block.html\"]\n"
        "        знч Путь = \"Макеты/%Имя\"\n"
        "        Файлы.Вставить(Путь, Текст(Путь))\n"
        "    ;\n"
        "    возврат Файлы\n"
        ";\n"
    )
    code = (
        "метод Карточка(): Строка\n"
        "    возврат Чтение.Все()[\"Макеты/card.css\"].Заменить(\"{{COLOR}}\", \"red\")"
        ".Заменить(\"{{SIZE}}\", \"1px\")\n"
        ";\n"
    )
    assert _found(_project(tmp_path, code, {"Чтение": maps})) == [
        (UNFILLED, "Оформление", 2), (ABSENT, "Оформление", 2),
    ]


def test_a_map_handed_over_by_a_client_parameters_element_is_followed(tmp_path):
    maps = READER + (
        "\nметод Все(): Соответствие<Строка, Строка>\n"
        "    пер Файлы = новый Соответствие<Строка, Строка>()\n"
        "    для Имя из [\"card.css\"]\n"
        "        знч Путь = \"Макеты/%Имя\"\n"
        "        Файлы.Вставить(Путь, Текст(Путь))\n"
        "    ;\n"
        "    возврат Файлы\n"
        ";\n"
    )
    params = (
        "@Обработчик\n"
        "@НаСервере\n"
        "статический метод ВычислитьПараметрыРаботыКлиента(): ПараметрыМакетов.Параметры\n"
        "    возврат новый ПараметрыМакетов.Параметры(Общие = Чтение.Все())\n"
        ";\n"
    )
    code = (
        "метод Карточка(): Строка\n"
        "    возврат ПараметрыМакетов.Общие[\"Макеты/card.css\"].Заменить(\"{{COLOR}}\", \"red\")\n"
        ";\n"
    )
    extra = {
        "Задачи/ПараметрыМакетов.yaml": (
            "ВидЭлемента: ПараметрыРаботыКлиента\nИмя: ПараметрыМакетов\n"
            "Параметры:\n    -\n        Имя: Общие\n        Тип: Соответствие<Строка, Строка>\n"
        ),
        "Задачи/ПараметрыМакетов.xbsl": params,
    }
    paths = _project(tmp_path, code, {"Чтение": maps}, extra)

    assert _found(paths) == [(UNFILLED, "Оформление", 2)]


def test_a_part_of_the_file_is_judged_only_for_absent_strings(tmp_path):
    code = (
        "метод Кусок(): Строка\n"
        "    возврат Ресурс{Макеты/block.html}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()\n"
        "        .Подстрока(5).Заменить(\"{{CLASS}}\", \"c\").Заменить(\"{{KIND}}\", \"k\")\n"
        ";\n"
    )
    assert _found(_project(tmp_path, code)) == [(ABSENT, "Оформление", 3)]


# --- what is not reported ---------------------------------------------------------------------


def test_a_complete_chain_is_silent(tmp_path):
    code = (
        "метод Карточка(): Строка\n"
        "    знч Текст = Ресурс{Макеты/card.css}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()\n"
        "    возврат Текст.Заменить(\"{{COLOR}}\", \"red\").Заменить(\"{{WIDTH}}\", \"1px\")\n"
        ";\n"
    )
    assert _lint(_project(tmp_path, code)) == []


def test_a_caller_that_fills_the_rest_keeps_the_chain_complete(tmp_path):
    code = (
        "метод Заготовка(): Строка\n"
        "    возврат Ресурс{Макеты/picture.svg}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()"
        ".Заменить(\"{{W}}\", \"10\")\n"
        ";\n\n"
        "метод Картинка(): Строка\n"
        "    возврат Заготовка().Заменить(\"{{T}}\", \"t\")\n"
        ";\n"
    )
    assert _lint(_project(tmp_path, code)) == []


def test_a_computed_search_string_further_on_opens_the_chain(tmp_path):
    code = (
        "метод Картинка(Что: Строка): Строка\n"
        "    знч Т = Ресурс{Макеты/picture.svg}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()"
        ".Заменить(\"{{W}}\", \"10\")\n"
        "    возврат Доделать(Т, Что)\n"
        ";\n\n"
        "метод Доделать(Разметка: Строка, Что: Строка): Строка\n"
        "    возврат Разметка.Заменить(Что, \"y\")\n"
        ";\n"
    )
    assert _lint(_project(tmp_path, code)) == []


def test_a_computed_path_and_a_choice_between_files_are_not_judged(tmp_path):
    code = (
        "метод Макет(Имя: Строка): Строка\n"
        "    возврат Чтение.Текст(Имя + \".html\").Заменить(\"{{KIND}}\", \"k\")\n"
        ";\n\n"
        "метод Выбор(Флаг: Булево): Строка\n"
        "    возврат (Флаг ? Чтение.Текст(\"Макеты/block.html\") : Чтение.Текст(\"Макеты/picture.svg\"))"
        ".Заменить(\"{{KIND}}\", \"k\")\n"
        ";\n"
    )
    assert _lint(_project(tmp_path, code, {"Чтение": READER})) == []


def test_a_helper_that_serves_several_files_is_not_blamed_for_one_of_them(tmp_path):
    helper = (
        "метод Покрасить(Разметка: Строка): Строка\n"
        "    возврат Разметка.Заменить(\"{{COLOR}}\", \"red\")\n"
        ";\n"
    )
    code = (
        "метод Карточка(): Строка\n"
        "    возврат Кисть.Покрасить(Ресурс{Макеты/card.css}.ОткрытьПотокЧтения().ПрочитатьКакСтроку())"
        ".Заменить(\"{{WIDTH}}\", \"1px\")\n"
        ";\n\n"
        "метод Картинка(): Строка\n"
        "    возврат Кисть.Покрасить(Ресурс{Макеты/picture.svg}.ОткрытьПотокЧтения().ПрочитатьКакСтроку())"
        ".Заменить(\"{{W}}\", \"1\").Заменить(\"{{T}}\", \"t\")\n"
        ";\n"
    )
    assert _lint(_project(tmp_path, code, {"Кисть": helper})) == []


def test_a_project_without_replacements_costs_nothing(tmp_path):
    code = "метод Карточка(): Строка\n    возврат Ресурс{Макеты/card.css}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()\n;\n"
    assert _lint(_project(tmp_path, code)) == []


def test_the_rules_are_project_wide_and_off_by_default():
    """The engine ships both rules off, with the reason. A project profile may turn a rule on
    through a plugin, and then the registry says enabled: that state is the plugin's, not the
    engine's default, so it is checked only for a rule no installed plugin overrides."""
    rules = {info.id: info for info in engine.RULES}
    overridden = plugins.severity_overrides()
    for rule_id in (ABSENT, UNFILLED):
        assert rules[rule_id].scope == "project"
        assert rules[rule_id].off_reason
        if rule_id not in overridden:
            assert rules[rule_id].enabled_by_default is False


def test_the_messages_read_in_english(tmp_path):
    code = (
        "метод Карточка(): Строка\n"
        "    возврат Ресурс{Макеты/card.css}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()\n"
        "        .Заменить(\"{{COLOR}}\", \"red\").Заменить(\"{{SIZE}}\", \"1px\")\n"
        ";\n"
    )
    i18n.set_lang("en")
    try:
        found = sorted(_lint(_project(tmp_path, code)), key=lambda d: d.rule_id)
    finally:
        i18n.set_lang("ru")
    assert found[0].message.startswith("The label {{WIDTH}} of the resource Макеты/card.css")
    assert found[1].message.startswith("The text of the resource Макеты/card.css has no \"{{SIZE}}\"")
