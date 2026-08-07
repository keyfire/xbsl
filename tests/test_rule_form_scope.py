"""code/undefined-name: what a form module gets from the type its component inherits.

A form's built-in command is a PROPERTY of the base type (WriteAndClose of type
Command), and running it is `WriteAndClose.Execute()` - the shape the working sources
use. Two defects met here and are covered separately:

- an ENGLISH project spells the section `Inherits`, and the base type was looked up under the
  Russian key alone: the base never resolved, its members never reached the module scope, and
  every bare member name of an English form module was reported undefined (an ERROR rule);
- `ВыполнитьЗаписать` / `ВыполнитьЗаписатьИЗакрыть` sat in the rule's whitelist as "members
  the docs do not carry". They are not members: the compiler answers `Unknown method` to both
  (checked by compiling them), and the whitelist silenced this rule on code that cannot compile.

The module needs the metamodel and the member catalogue - it is listed in
conftest._DATA_DEPENDENT.
"""

from xbsl import engine
from xbsl.cli import discover

_RULE = "code/undefined-name"

_CATALOG_RU = """\
ВидЭлемента: Справочник
Ид: 6f0b6a44-0000-4000-8000-00000000f001
Имя: Задачи
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 6f0b6a44-0000-4000-8000-00000000f002
        Имя: Наименование
"""

_CATALOG_EN = """\
ElementKind: Catalog
Id: 6f0b6a44-0000-4000-8000-00000000f003
Name: Tasks
VisibilityScope: InProject
Attributes:
    -
        Id: 6f0b6a44-0000-4000-8000-00000000f004
        Name: Name
"""

_FORM_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 6f0b6a44-0000-4000-8000-00000000f005
Имя: Карточка
ОбластьВидимости: ВПроекте
Наследует:
    Тип: ФормаОбъекта<Задачи.Объект>
"""

_FORM_EN = """\
ElementKind: InterfaceComponent
Id: 6f0b6a44-0000-4000-8000-00000000f006
Name: Card
VisibilityScope: InProject
Inherits:
    Type: ObjectForm<Tasks.Object>
"""


def _lint(tmp_path, *, english: bool, module: str):
    (tmp_path / ("Tasks.yaml" if english else "Задачи.yaml")).write_text(
        _CATALOG_EN if english else _CATALOG_RU, encoding="utf-8"
    )
    stem = "Card" if english else "Карточка"
    (tmp_path / f"{stem}.yaml").write_text(
        _FORM_EN if english else _FORM_RU, encoding="utf-8"
    )
    (tmp_path / f"{stem}.xbsl").write_text(module, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)])) if d.rule_id == _RULE]


def test_russian_form_sees_the_commands_of_its_base_type(tmp_path):
    module = "метод Записать1(Команда: ОбычнаяКоманда)\n    ЗаписатьИЗакрыть.Выполнить()\n;\n"
    assert _lint(tmp_path, english=False, module=module) == []


def test_english_form_sees_them_too(tmp_path):
    # The regression: with the base read under the Russian key alone this was two errors.
    module = "method Save(Command: UsualCommand)\n    WriteAndClose.Execute()\n;\n"
    assert _lint(tmp_path, english=True, module=module) == []


def test_an_undeclared_command_method_is_reported(tmp_path):
    # The name the whitelist used to cover: nothing declares it, and the compiler rejects it.
    module = "метод Записать1(Команда: ОбычнаяКоманда)\n    ВыполнитьЗаписатьИЗакрыть()\n;\n"
    found = _lint(tmp_path, english=False, module=module)
    assert [d.line for d in found] == [2]
    assert "ВыполнитьЗаписатьИЗакрыть" in found[0].message


def test_a_handler_of_that_name_declared_in_the_module_is_fine(tmp_path):
    # ...and the same name is legal the moment the module declares it - that is what the
    # working sources do: an author's handler method around the platform call.
    module = (
        "метод ВыполнитьЗаписатьИЗакрыть(Команда: ОбычнаяКоманда)\n"
        "    ЗаписатьИЗакрыть.Выполнить()\n"
        ";\n"
        "\n"
        "метод Прочее(Команда: ОбычнаяКоманда)\n"
        "    ВыполнитьЗаписатьИЗакрыть(Команда)\n"
        ";\n"
    )
    assert _lint(tmp_path, english=False, module=module) == []


def test_an_unknown_name_in_an_english_form_is_still_reported(tmp_path):
    # The negative control of the bilingual scope: it must not turn the rule blind.
    module = "method Save(Command: UsualCommand)\n    WriteAndCloze.Execute()\n;\n"
    found = _lint(tmp_path, english=True, module=module)
    assert [d.line for d in found] == [2]
    assert "WriteAndCloze" in found[0].message
