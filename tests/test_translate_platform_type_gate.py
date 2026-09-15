"""A platform type keeps its spelling wherever only a type can stand.

The project gate (names.py) keeps the names a project declares away from the platform tables, so
that a declaration and its uses move together. It held every declared word, and a field is a
declaration too: a structure whose field was spelled like the users catalog left that catalog
half translated in every type expression, `Пользователи.Reference`, and an attribute spelled
like the privilege facet did the same to the generic entity, `Entity.Право.Чтение`. The language
has neither name. A type expression, the root of a static call and the owner of a facet name a
TYPE, and the only project names that can mean one there are the types the project declares.
"""

from __future__ import annotations

from pathlib import Path

from xbsl import engine
from xbsl.translation import dictionary as dict_module
from xbsl.translation import names
from xbsl.translation.code import type_ranges
from xbsl.translation.project import translate_project


def _dictionary(tokens: dict | None = None) -> dict_module.Dictionary:
    return dict_module.Dictionary(tokens=dict(tokens or {}), phrases={}, literals={})


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- what counts as a type the project declares ----------------------------------------------


def test_the_declared_types_are_elements_structures_enumerations_and_exceptions():
    module = engine.load_text("Склады.xbsl", (
        "структура Партия\n"
        "    пер Код: Строка\n"
        ";\n"
        "\n"
        "перечисление Статус\n"
        "    Новый\n"
        ";\n"
        "\n"
        "исключение ОшибкаСклада\n"
        ";\n"
        "\n"
        "метод Проба()\n"
        "    попытка\n"
        "        Проба()\n"
        "    поймать Ошибка: Исключение\n"
        "        Задачи.Записать()\n"
        "    ;\n"
        ";\n"
    ))
    # The exception type after `поймать` is a type word in an expression, not a declaration:
    # the name on the next line has nothing to do with it.
    assert names.declared_types(module) == {"Партия", "Статус", "ОшибкаСклада"}

    element = engine.load_text("Склады.yaml", (
        "ВидЭлемента: Справочник\n"
        "Имя: Склады\n"
        "Реквизиты:\n"
        "    -\n"
        "        Имя: Партия\n"
        "        Тип: Строка\n"
    ))
    # The element is a type; its attribute is a name of the project, not a type.
    assert names.declared_types(element) == {"Склады"}


# --- an annotation name --------------------------------------------------------------------


def test_a_platform_annotation_keeps_its_platform_context_next_to_a_project_homonym(
        tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Module.xbsl", (
        "@Обработчик\n"
        "метод Выполнить()\n"
        ";\n"
        "\n"
        "метод Обработчик()\n"
        ";\n"
        "\n"
        "@МеткаПроверки\n"
        "структура МеткаПроверки\n"
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary({
        "Выполнить": "Execute",
        "Обработчик": "ProjectHandler",
        "МеткаПроверки": "AuditMark",
    }), out, swap_localization=False)

    module = _read(out / "Module.xbsl")
    assert "@Handler\nmethod Execute()" in module
    assert "method ProjectHandler()" in module
    # A name that the platform does not declare as an annotation stays on the project plane.
    assert "@AuditMark\nstructure AuditMark" in module


# --- a type expression ----------------------------------------------------------------------


def test_a_field_named_like_a_platform_type_does_not_hold_a_type_expression(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Выгрузка.xbsl", (
        "структура ЗаписьВыгрузки\n"
        "    пер Пользователи: Массив<Строка>\n"
        ";\n"
        "\n"
        "метод Отобрать(Кладовщик: Пользователи.Ссылка,\n"
        "        Претенденты: ЧитаемыйМассив<Пользователи.Ссылка>): Пользователи.Объект?\n"
        "    пер Отобранные = новый Массив<Пользователи.Ссылка>()\n"
        "    Пользователи.ПересчитатьКлючиДоступа(<Пользователи.Ссылка>[Кладовщик])\n"
        "    возврат Неопределено\n"
        ";\n"
    ))
    _write(root / "Склады.yaml", (
        "ВидЭлемента: Справочник\n"
        "Имя: Склады\n"
        "Реквизиты:\n"
        "    -\n"
        "        Имя: Кладовщик\n"
        "        Тип: Пользователи.Ссылка?\n"
    ))
    out = tmp_path / "en"
    report = translate_project(root, _dictionary(), out, swap_localization=False)

    module = _read(out / "Выгрузка.xbsl")
    assert "(Кладовщик: Users.Reference," in module
    assert "Претенденты: ReadableArray<Users.Reference>): Users.Object?" in module
    assert "new Array<Users.Reference>()" in module
    assert "Users.RecomputeAccessKeys(<Users.Reference>[Кладовщик])" in module
    assert "Пользователи.Reference" not in module
    assert "Type: Users.Reference?" in _read(out / "Склады.yaml")
    # The field is still the project's own word: without an entry it stays as written and is
    # reported, the declaration and every read of it together.
    assert "var Пользователи: Array<String>" in module
    assert "Пользователи" in report.merged_missing_tokens()


def test_a_type_the_project_declares_under_a_platform_name_keeps_the_gate(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Журнал.xbsl", (
        "структура Событие\n"
        "    пер Текст: Строка\n"
        ";\n"
        "\n"
        "метод Скопировать(Исходное: Событие): Событие\n"
        "    возврат новый Событие(Текст = Исходное.Текст)\n"
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary(), out, swap_localization=False)
    module = _read(out / "Журнал.xbsl")
    # Without an entry the structure and its uses stay together under the Russian name - the
    # platform's own type of that spelling is not what the module means.
    assert "structure Событие" in module
    assert "(Исходное: Событие): Событие" in module
    assert "new Событие(" in module

    out = tmp_path / "en2"
    translate_project(root, _dictionary({"Событие": "Occurrence"}), out, swap_localization=False)
    module = _read(out / "Журнал.xbsl")
    assert "structure Occurrence" in module
    assert "(Исходное: Occurrence): Occurrence" in module
    assert "new Occurrence(" in module


def test_a_type_literal_marks_its_argument_as_a_type_and_leaves_an_expression_alone(
        tmp_path: Path):
    source = engine.load_text("Проверка.xbsl", (
        "метод Проверить()\n"
        "    знч ТипПроекта = Тип<ПроектныйТип.Объект>\n"
        "    знч Обычное = ПроектныйТип.Объект\n"
        ";\n"
    ))
    spans = [source.text[start:end] for start, end in type_ranges(source)]
    assert "ПроектныйТип.Объект" in spans

    root = tmp_path / "Acme" / "Demo"
    _write(root / "ПроектныйТип.yaml", (
        "ВидЭлемента: Справочник\n"
        "Имя: ПроектныйТип\n"
        "Реквизиты:\n"
        "    -\n"
        "        Имя: Объект\n"
        "        Тип: Строка\n"
    ))
    _write(root / "TypeCheck.xbsl", source.text)
    out = tmp_path / "en"
    translate_project(root, _dictionary({
        "ПроектныйТип": "ProjectType",
        "Объект": "ProjectObjectField",
        "Проверить": "Check",
        "ТипПроекта": "ProjectTypeValue",
        "Обычное": "Ordinary",
    }), out, swap_localization=False)

    module = _read(out / "TypeCheck.xbsl")
    assert "Type<ProjectType.Object>" in module
    assert "ProjectType.ProjectObjectField" in module


# --- a typed yaml node ----------------------------------------------------------------------


def test_platform_keys_of_a_typed_command_ignore_project_homonyms(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Project.yaml", "Vendor: Acme\nName: Demo\nVersion: 1.0.0\n")
    _write(root / "Панель.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Панель\n"
        "Свойства:\n"
        "    -\n"
        "        Имя: Обработчик\n"
        "        Тип: Строка\n"
        "    -\n"
        "        Имя: Представление\n"
        "        Тип: Строка\n"
        "    -\n"
        "        Имя: Изображение\n"
        "        Тип: Строка\n"
        "    -\n"
        "        Имя: Элементы\n"
        "        Тип: Строка\n"
        "    -\n"
        "        Имя: КомандаСПараметром\n"
        "        Тип: Строка\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйКомпонент\n"
    ))
    _write(root / "Команды.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Команды\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйШаблонФормы\n"
        "    Содержимое:\n"
        "        Тип: КомандаСПараметром<Строка>\n"
        "        Обработчик: Запустить\n"
        "        Представление: Команда\n"
        "        Изображение: Значок\n"
        "        Элементы: []\n"
    ))
    _write(root / "Использование.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Использование\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйШаблонФормы\n"
        "    Содержимое:\n"
        "        Тип: Acme::Demo::Панель\n"
        "        Обработчик: Run\n"
    ))
    _write(root / "External.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: External\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйШаблонФормы\n"
        "    Содержимое:\n"
        "        Тип: Std::Interface::Панель\n"
        "        Обработчик: Run\n"
    ))
    component_types = names.component_types(root, engine.load)
    assert {"Панель", "Acme::Demo::Панель"} <= component_types
    assert "Std::Interface::Панель" not in component_types
    out = tmp_path / "en"
    translate_project(root, _dictionary({
        "Панель": "Panel",
        "Команды": "Commands",
        "Обработчик": "ProjectHandler",
        "Представление": "ProjectPresentation",
        "Изображение": "ProjectImage",
        "Элементы": "ProjectItems",
        "КомандаСПараметром": "ProjectCommandName",
        "Использование": "Usage",
        "Запустить": "Run",
    }), out, swap_localization=False)

    command = _read(out / "Commands.yaml")
    assert "Type: CommandWithParameter<String>" in command
    assert "Handler: Run" in command
    assert "Presentation: Команда" in command
    assert "Image: Значок" in command
    assert "Items: []" in command
    assert "ProjectHandler:" not in command
    usage = _read(out / "Usage.yaml")
    assert "ProjectHandler: Run" in usage
    external = _read(out / "External.yaml")
    assert "Handler: Run" in external
    panel = _read(out / "Panel.yaml")
    assert "Name: ProjectHandler" in panel
    assert "Name: ProjectPresentation" in panel
    assert "Name: ProjectImage" in panel
    assert "Name: ProjectItems" in panel
    assert "Name: ProjectCommandName" in panel


def test_an_element_named_like_a_platform_type_keeps_the_gate_at_a_static_root(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Язык.yaml", (
        "ВидЭлемента: Перечисление\n"
        "Имя: Язык\n"
        "Элементы:\n"
        "    -\n"
        "        Имя: Основной\n"
    ))
    _write(root / "Настройки.xbsl", (
        "метод ЯзыкПоУмолчанию(): Язык\n"
        "    возврат Язык.Основной\n"
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary(), out, swap_localization=False)
    module = _read(out / "Настройки.xbsl")
    assert "(): Язык" in module
    assert "return Язык." in module


# --- the owner of a facet -------------------------------------------------------------------


def test_the_facet_of_the_generic_entity_is_the_platform_s_word(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Склады.yaml", (
        "ВидЭлемента: Справочник\n"
        "Имя: Склады\n"
        "Реквизиты:\n"
        "    -\n"
        "        Имя: Право\n"
        "        Тип: Строка\n"
    ))
    _write(root / "Доступ.xbsl", (
        "метод Разрешения(): Массив<Сущность.Право>\n"
        "    возврат [Сущность.Право.Чтение, Сущность.Право.Изменение]\n"
        ";\n"
        "\n"
        "метод ПравоСклада(Склад: Склады.Объект): Строка\n"
        "    возврат Склад.Право\n"
        ";\n"
        "\n"
        "метод ПравоЗаписи(Сущность: Склады.Объект): Строка\n"
        "    возврат Сущность.Право\n"
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary(), out, swap_localization=False)
    module = _read(out / "Доступ.xbsl")
    assert "(): Array<Entity.Privilege>" in module
    assert "return [Entity.Privilege.Чтение, Entity.Privilege.Изменение]" in module
    # The attribute read off a record is the project's word. So is the member of a parameter
    # spelled like the entity: the parameter takes the flat spelling of its own name, and what
    # follows it is its member, not the facet.
    assert "return Склад.Право" in module
    assert "return Entity.Право" in module
    assert module.count("Entity.Privilege") == 3
    assert "Name: Право" in _read(out / "Склады.yaml")


# --- the editor's twin: conventions/missing-translation -------------------------------------


def _findings(paths: list[Path]) -> list[tuple[str, str]]:
    """(file name, message) of the project rule, run the way the engine runs it."""
    from xbsl.rules import translation_gaps

    translation_gaps._dictionary_at.cache_clear()
    facts = {}
    for path in paths:
        source = engine.load(path)
        fact = translation_gaps._gaps_mapper(source)
        if fact is not None:
            facts[source.rel] = fact
    return [(Path(d.path).name, d.message) for d in translation_gaps.missing_translation(facts)]


def test_the_rule_asks_for_a_type_word_only_where_the_project_declares_the_type(tmp_path: Path):
    _write(tmp_path / "xbsl-translation" / "dict.yaml",
           "version: 1\nlanguage: en\ntokens:\n    Склады: Warehouses\n")
    field = tmp_path / "Выгрузка.xbsl"
    _write(field, "структура ЗаписьВыгрузки\n    пер Пользователи: Массив<Строка>\n;\n")
    typed = tmp_path / "Отбор.xbsl"
    _write(typed, (
        "метод Отобрать(Пользователь: Пользователи.Ссылка): Событие\n"
        "    Пользователи.ПересчитатьКлючиДоступа([Пользователь])\n"
        "    возврат новый Событие()\n"
        ";\n"
    ))
    declared = tmp_path / "Журнал.xbsl"
    _write(declared, "структура Событие\n    пер Текст: Строка\n;\n")

    found = _findings([field, typed, declared])

    def reported(file: str, name: str) -> bool:
        return any(where == file and f"'{name}'" in text for where, text in found)

    # The field is a gap where it is declared...
    assert reported("Выгрузка.xbsl", "Пользователи")
    # ...and the platform type spelled the same way is not a gap anywhere it stands as a type.
    assert not reported("Отбор.xbsl", "Пользователи"), found
    # A type the project declares under a platform name is a gap at its type positions too.
    assert reported("Отбор.xbsl", "Событие"), found
