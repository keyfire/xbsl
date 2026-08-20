"""Rules that read a SECTION of a yaml: the section has to be found in either spelling.

1C:Element sources are bilingual all the way into the keys - `Attributes`, `Import`,
`VisibilityScope`, `Environment` with its `Server`/`Client` values are the English spellings
of the same keys and values a Russian project writes. A rule that asks the parsed document
for the Russian spelling alone finds nothing in a project written in English, and the
consequence is never neutral: the rule either goes silent on a whole project, or - where the
missing section is what CLEARS a finding - reports working code.

Every check below is a pair: the Russian project (the rule already worked there) next to
the English one, plus the negative controls that keep the wider reading from turning into
a blind one. Everything is linted from memory (engine.load_text), on a demo project of its
own - a Tasks catalog, a Steps module and a Goods catalog, in both languages.
"""

import pytest

from xbsl import engine
import xbsl.rules  # noqa: F401 - registers every rule

pytestmark = pytest.mark.needs_data


def _lint(files: dict[str, str], rule: str) -> list:
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return [d for d in engine.run_sources(sources, select={rule}) if d.rule_id == rule]


# --- Import / VisibilityScope: the two cross-subsystem yaml rules -------------------------

_SUB_KEEPS_TO_ITSELF_RU = "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n"
_SUB_KEEPS_TO_ITSELF_EN = "Interface:\n    IncludeInAutoInterface: False\n"
_SUB_USES_RU = "Использование:\n    - Прочее\n"
_SUB_USES_EN = "Usage:\n    - Other\n"

_GOODS_RU = "ВидЭлемента: Справочник\nИмя: Товары\nОбластьВидимости: ВПроекте\n"
_GOODS_EN = "ElementKind: Catalog\nName: Goods\nVisibilityScope: InProject\n"
_GOODS_PRIVATE_EN = "ElementKind: Catalog\nName: Goods\n"

_TASKS_RU = (
    "ВидЭлемента: Справочник\n"
    "Имя: Задачи\n"
    "{imports}"
    "Реквизиты:\n"
    "    -\n"
    "        Имя: Товар\n"
    "        Тип: Товары.Ссылка?\n"
)
# The type key stays as the metamodel names it while the rest is English: the walk that
# collects type VALUES out of a document still matches that one key literally (_type_values
# in xbsl/rules/yaml_types.py) - a blind spot of its own, and not what these checks are
# about. Everything the rules under test read here - the section keys and the visibility
# value - is spelled in English.
_TASKS_EN = (
    "ElementKind: Catalog\n"
    "Name: Tasks\n"
    "{imports}"
    "Attributes:\n"
    "    -\n"
    "        Name: Product\n"
    "        Тип: Goods.Reference?\n"
)


def _two_subsystems_ru(imports: str = "", *, descriptor: str = _SUB_USES_RU) -> dict[str, str]:
    return {
        "Основное/Подсистема.yaml": descriptor,
        "Прочее/Подсистема.yaml": _SUB_KEEPS_TO_ITSELF_RU,
        "Прочее/Товары.yaml": _GOODS_RU,
        "Основное/Задачи.yaml": _TASKS_RU.format(imports=imports),
    }


def _two_subsystems_en(
    imports: str = "", *, descriptor: str = _SUB_USES_EN, goods: str = _GOODS_EN,
) -> dict[str, str]:
    return {
        "Main/Subsystem.yaml": descriptor,
        "Other/Subsystem.yaml": _SUB_KEEPS_TO_ITSELF_EN,
        "Other/Goods.yaml": goods,
        "Main/Tasks.yaml": _TASKS_EN.format(imports=imports),
    }


def test_missing_import_russian_project():
    found = _lint(_two_subsystems_ru(), "yaml/missing-import")
    assert [d.line for d in found] == [6]


def test_missing_import_english_project():
    # The regression: VisibilityScope read as one spelling left the foreign catalog
    # "not public", and a non-public element is not this rule's case - it kept quiet.
    found = _lint(_two_subsystems_en(), "yaml/missing-import")
    assert [d.line for d in found] == [6]
    assert "Goods.Reference" in found[0].message and "'Other'" in found[0].message


def test_missing_import_english_project_with_the_import_present():
    # The negative control of the other key: the Import section has to CLEAR the finding.
    assert _lint(_two_subsystems_en("Import:\n    - Other\n"), "yaml/missing-import") == []


def test_missing_import_russian_project_with_the_import_present():
    assert _lint(_two_subsystems_ru("Импорт:\n    - Прочее\n"), "yaml/missing-import") == []


def test_foreign_not_public_stays_quiet_on_a_public_english_element():
    # The regression the other way round: the section was unread, every foreign element
    # looked private, and a project that publishes its catalog properly was reported.
    files = _two_subsystems_en("Import:\n    - Other\n")
    assert _lint(files, "yaml/foreign-not-public") == []


def test_foreign_not_public_still_reports_a_private_english_element():
    files = _two_subsystems_en("Import:\n    - Other\n", goods=_GOODS_PRIVATE_EN)
    found = _lint(files, "yaml/foreign-not-public")
    assert [d.line for d in found] == [8]
    assert "Goods.Reference" in found[0].message


def test_foreign_not_public_still_reports_a_private_russian_element():
    files = _two_subsystems_ru("Импорт:\n    - Прочее\n")
    files["Прочее/Товары.yaml"] = "ВидЭлемента: Справочник\nИмя: Товары\n"
    assert len(_lint(files, "yaml/foreign-not-public")) == 1


# --- VisibilityScope in the module-side twin: code/missing-import --------------------------

_STEPS_MODULE_RU = "метод Взять(): Товары.Ссылка?\n    возврат Неопределено\n;\n"
_STEPS_MODULE_EN = "method Take(): Goods.Reference?\n    return Undefined\n;\n"


def _module_import_project_ru() -> dict[str, str]:
    return {
        "Основное/Подсистема.yaml": _SUB_USES_RU,
        "Прочее/Подсистема.yaml": _SUB_KEEPS_TO_ITSELF_RU,
        "Прочее/Товары.yaml": _GOODS_RU,
        "Основное/Шаги.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Шаги\n",
        "Основное/Шаги.xbsl": _STEPS_MODULE_RU,
    }


def _module_import_project_en() -> dict[str, str]:
    return {
        "Main/Subsystem.yaml": _SUB_USES_EN,
        "Other/Subsystem.yaml": _SUB_KEEPS_TO_ITSELF_EN,
        "Other/Goods.yaml": _GOODS_EN,
        "Main/Steps.yaml": "ElementKind: CommonModule\nName: Steps\n",
        "Main/Steps.xbsl": _STEPS_MODULE_EN,
    }


def test_code_missing_import_russian_project():
    assert len(_lint(_module_import_project_ru(), "code/missing-import")) == 1


def test_code_missing_import_english_project():
    found = _lint(_module_import_project_en(), "code/missing-import")
    assert len(found) == 1
    assert "Goods.Reference" in found[0].message


def test_code_missing_import_english_project_with_the_import_present():
    files = _module_import_project_en()
    files["Main/Steps.xbsl"] = "import Other\n" + _STEPS_MODULE_EN
    assert _lint(files, "code/missing-import") == []


# --- Import of a yaml: yaml/missing-subsystem-usage ----------------------------------------

def test_missing_subsystem_usage_russian_project():
    files = _two_subsystems_ru(
        "Импорт:\n    - Прочее\n", descriptor=_SUB_KEEPS_TO_ITSELF_RU,
    )
    found = _lint(files, "yaml/missing-subsystem-usage")
    assert len(found) == 1 and "Прочее" in found[0].message


def test_missing_subsystem_usage_english_project():
    # The regression: the yaml Import section was unread, so the import that has to be
    # permitted by the subsystem descriptor was never noticed.
    files = _two_subsystems_en(
        "Import:\n    - Other\n", descriptor=_SUB_KEEPS_TO_ITSELF_EN,
    )
    found = _lint(files, "yaml/missing-subsystem-usage")
    assert len(found) == 1 and "Other" in found[0].message


def test_missing_subsystem_usage_english_project_with_the_usage_declared():
    files = _two_subsystems_en("Import:\n    - Other\n")
    assert _lint(files, "yaml/missing-subsystem-usage") == []


# --- Import of an external namespace: code/undefined-name ----------------------------------

_EXTERNAL_IMPORT_RU = (
    "ВидЭлемента: ОбщийМодуль\nИмя: Шаги\nИмпорт:\n    - e1c::Поставщик::Библиотека\n"
)
_EXTERNAL_IMPORT_EN = (
    "ElementKind: CommonModule\nName: Steps\nImport:\n    - e1c::Vendor::Library\n"
)


def test_undefined_name_skips_a_russian_module_with_an_external_import():
    files = {"Шаги.yaml": _EXTERNAL_IMPORT_RU,
             "Шаги.xbsl": "метод Ф()\n    ХелперБиблиотеки()\n;\n"}
    assert _lint(files, "code/undefined-name") == []


def test_undefined_name_skips_an_english_module_with_an_external_import():
    # The regression: the Import section was unread, the module counted as importing
    # nothing external, and every name the library brings in was reported undefined.
    files = {"Steps.yaml": _EXTERNAL_IMPORT_EN,
             "Steps.xbsl": "method M()\n    LibraryHelper()\n;\n"}
    assert _lint(files, "code/undefined-name") == []


def test_undefined_name_still_reports_an_english_module_without_that_import():
    files = {"Steps.yaml": "ElementKind: CommonModule\nName: Steps\n",
             "Steps.xbsl": "method M()\n    LibraryHelper()\n;\n"}
    found = _lint(files, "code/undefined-name")
    assert [d.line for d in found] == [2]


# --- TabularParts: code/unknown-ns-object and yaml/unknown-type ----------------------------

_TASKS_WITH_STEPS_RU = (
    "ВидЭлемента: Справочник\n"
    "Имя: Задачи\n"
    "ТабличныеЧасти:\n"
    "    -\n"
    "        Имя: Шаги\n"
    "        Реквизиты:\n"
    "            -\n"
    "                Имя: Шаг\n"
    "                Тип: Строка\n"
)
_TASKS_WITH_STEPS_EN = (
    "ElementKind: Catalog\n"
    "Name: Tasks\n"
    "TabularParts:\n"
    "    -\n"
    "        Name: Steps\n"
    "        Attributes:\n"
    "            -\n"
    "                Name: Step\n"
    "                Type: String\n"
)


def test_unknown_ns_object_accepts_a_russian_tabular_section():
    files = {
        "Задачи.yaml": _TASKS_WITH_STEPS_RU,
        "Задачи.xbsl": "метод Ф(Строки: Справочник.Задачи.Шаги)\n    возврат\n;\n",
    }
    assert _lint(files, "code/unknown-ns-object") == []


def test_unknown_ns_object_accepts_an_english_tabular_section():
    # Read together with the negative control below: with the section unread the object had
    # no members at all, so the rule could neither accept this chain nor reject the next one.
    files = {
        "Tasks.yaml": _TASKS_WITH_STEPS_EN,
        "Tasks.xbsl": "method M(Rows: Catalog.Tasks.Steps)\n    return\n;\n",
    }
    assert _lint(files, "code/unknown-ns-object") == []


def test_unknown_ns_object_still_reports_a_member_no_english_object_has():
    files = {
        "Tasks.yaml": _TASKS_WITH_STEPS_EN,
        "Tasks.xbsl": "method M(Rows: Catalog.Tasks.Stages)\n    return\n;\n",
    }
    found = _lint(files, "code/unknown-ns-object")
    assert len(found) == 1 and "Stages" in found[0].message


def test_unknown_ns_object_leaves_an_english_dotted_generic_alone():
    # `Catalog.Reference` is the English spelling of a dotted stdlib generic,
    # not a reference to an object named Reference.
    files = {
        "Tasks.yaml": _TASKS_WITH_STEPS_EN,
        "Tasks.xbsl": "method M(Any: Catalog.Reference?)\n    return\n;\n",
    }
    assert _lint(files, "code/unknown-ns-object") == []


_FORM_OVER_STEPS_RU = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Имя: Форма\n"
    "Реквизиты:\n"
    "    -\n"
    "        Имя: Строки\n"
    "        Тип: Массив<Задачи.Шаги>\n"
)
_FORM_OVER_STEPS_EN = (  # the type key: see the note above the English catalog
    "ElementKind: InterfaceComponent\n"
    "Name: Form\n"
    "Attributes:\n"
    "    -\n"
    "        Name: Rows\n"
    "        Тип: Array<Tasks.Steps>\n"
)


def test_unknown_type_accepts_a_russian_tabular_section():
    files = {"Задачи.yaml": _TASKS_WITH_STEPS_RU, "Форма.yaml": _FORM_OVER_STEPS_RU}
    assert _lint(files, "yaml/unknown-type") == []


def test_unknown_type_accepts_an_english_tabular_section():
    # Read together with the negative control below - see the note on the namespace pair.
    files = {"Tasks.yaml": _TASKS_WITH_STEPS_EN, "Form.yaml": _FORM_OVER_STEPS_EN}
    assert _lint(files, "yaml/unknown-type") == []


def test_unknown_type_still_reports_a_section_the_english_object_lacks():
    files = {
        "Tasks.yaml": _TASKS_WITH_STEPS_EN,
        "Form.yaml": _FORM_OVER_STEPS_EN.replace("Tasks.Steps", "Tasks.Stages"),
    }
    found = _lint(files, "yaml/unknown-type")
    assert len(found) == 1 and "Tasks.Stages" in found[0].message


# --- Inherits / Properties: yaml/builtin-property-name -------------------------------------

_CARD_RU = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Имя: Карточка\n"
    "Наследует:\n"
    "    Тип: СтандартнаяКарточка\n"
    "Свойства:\n"
    "    -\n"
    "        Имя: {prop}\n"
    "        Тип: Строка\n"
)
_CARD_EN = (
    "ElementKind: InterfaceComponent\n"
    "Name: Card\n"
    "Inherits:\n"
    "    Type: StandardCard\n"
    "Properties:\n"
    "    -\n"
    "        Name: {prop}\n"
    "        Type: String\n"
)


def test_builtin_property_name_russian_card():
    found = _lint({"Карточка.yaml": _CARD_RU.format(prop="Заголовок")},
                  "yaml/builtin-property-name")
    assert len(found) == 1 and (found[0].line, found[0].col) == (7, 14)


def test_builtin_property_name_english_card():
    # The regression: neither the base type nor the property list was read, so a property
    # that collides with a built-in one of StandardCard went unreported.
    found = _lint({"Card.yaml": _CARD_EN.format(prop="Title")},
                  "yaml/builtin-property-name")
    assert len(found) == 1 and (found[0].line, found[0].col) == (7, 15)
    assert "Title" in found[0].message


def test_builtin_property_name_leaves_an_english_own_property_alone():
    assert _lint({"Card.yaml": _CARD_EN.format(prop="LargeTitle")},
                 "yaml/builtin-property-name") == []


# --- Attributes of the object behind a dynamic list: yaml/dynlist-missing-field ------------

_GOODS_ATTRS_RU = (
    "ВидЭлемента: Справочник\n"
    "Имя: Товары\n"
    "Реквизиты:\n"
    "    -\n"
    "        Имя: Наименование\n"
    "        Длина: 250\n"
    "    -\n"
    "        Имя: Цена\n"
    "        Тип: Число\n"
)
_GOODS_ATTRS_EN = (
    "ElementKind: Catalog\n"
    "Name: Goods\n"
    "Attributes:\n"
    "    -\n"
    "        Name: Name\n"
    "        Length: 250\n"
    "    -\n"
    "        Name: Price\n"
    "        Type: Number\n"
)


def _list_form_ru(fields: list[str]) -> str:
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Форма\n"
        "Содержимое:\n"
        "    -\n"
        "        Тип: Таблица<ДинамическийСписок"
        "<Товары.АвтоматическаяФормаСписка.ДанныеСтрокиСписка>>\n"
        "        Имя: Список\n"
        "        Источник:\n"
        "            ОсновнаяТаблица:\n"
        "                Таблица: Товары\n"
        "            Поля:\n"
    )
    for field in fields:
        text += ("                -\n"
                 "                    Тип: ПолеДинамическогоСписка\n"
                 f"                    Выражение: {field}\n")
    return text


def _list_form_en(fields: list[str]) -> str:
    text = (
        "ElementKind: InterfaceComponent\n"
        "Name: Form\n"
        "Content:\n"
        "    -\n"
        "        Type: Table<DynamicList"
        "<Goods.AutomaticListForm.ДанныеСтрокиСписка>>\n"
        "        Name: List\n"
        "        Source:\n"
        "            MainTable:\n"
        "                Table: Goods\n"
        "            Fields:\n"
    )
    for field in fields:
        text += ("                -\n"
                 "                    Type: DynamicListField\n"
                 f"                    Expression: {field}\n")
    return text


def test_dynlist_missing_field_russian_project():
    files = {"Товары.yaml": _GOODS_ATTRS_RU,
             "Форма.yaml": _list_form_ru(["Ссылка", "Наименование"])}
    found = _lint(files, "yaml/dynlist-missing-field")
    assert len(found) == 1 and "'Цена'" in found[0].message


def test_dynlist_missing_field_english_project():
    # The regression: the Attributes section was unread, the object contributed no required
    # attributes, and an incomplete field list of a list over it passed unnoticed.
    files = {"Goods.yaml": _GOODS_ATTRS_EN,
             "Form.yaml": _list_form_en(["Reference", "Name"])}
    found = _lint(files, "yaml/dynlist-missing-field")
    assert len(found) == 1 and "'Price'" in found[0].message


def test_dynlist_complete_field_set_of_an_english_project_not_flagged():
    files = {"Goods.yaml": _GOODS_ATTRS_EN,
             "Form.yaml": _list_form_en(["Reference", "Name", "Price"])}
    assert _lint(files, "yaml/dynlist-missing-field") == []


# --- Environment: the three rules that judge where a module runs ---------------------------

def test_client_annotation_in_a_russian_server_module():
    files = {
        "Модуль.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: Сервер\n",
        "Модуль.xbsl": "@НаСервере @НаКлиенте\nструктура Данные\n    пер Имя: Строка?\n;\n",
    }
    found = _lint(files, "code/client-annotation-in-server-module")
    assert len(found) == 1 and "НаКлиенте" in found[0].message


def test_client_annotation_in_an_english_server_module():
    # The regression: `Environment: Server` was neither found under that key nor recognised
    # by its value, so a server module never counted as one.
    files = {
        "Module.yaml": "ElementKind: CommonModule\nName: Module\nEnvironment: Server\n",
        "Module.xbsl": "@OnServer @OnClient\nstructure Data\n    var Name: String?\n;\n",
    }
    found = _lint(files, "code/client-annotation-in-server-module")
    assert len(found) == 1 and "OnClient" in found[0].message


def test_client_annotation_in_an_english_mixed_module_not_flagged():
    files = {
        "Module.yaml": "ElementKind: CommonModule\nName: Module\nEnvironment: ClientAndServer\n",
        "Module.xbsl": "@OnServer @OnClient\nstructure Data\n    var Name: String?\n;\n",
    }
    assert _lint(files, "code/client-annotation-in-server-module") == []


_CLIENT_HELPER_RU = "статический метод Хелпер(): Строка\n    возврат \"х\"\n;\n"
_CLIENT_HELPER_EN = "static method Helper(): String\n    return \"x\"\n;\n"


def test_client_module_in_a_russian_http_service():
    files = {
        "МодульКлиент.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: МодульКлиент\nОкружение: Клиент\n",
        "МодульКлиент.xbsl": _CLIENT_HELPER_RU,
        "Апи.yaml": "ВидЭлемента: HttpСервис\nИмя: Апи\n",
        "Апи.xbsl": "метод Обработать()\n    знч Х = МодульКлиент.Хелпер()\n;\n",
    }
    found = _lint(files, "code/client-module-in-http-service")
    assert len(found) == 1 and "МодульКлиент.Хелпер" in found[0].message


def test_client_module_in_an_english_http_service():
    # The regression: `Environment: Client` was unread, no module counted as client-side,
    # and a call the platform rejects at runtime went unreported.
    files = {
        "ClientModule.yaml": "ElementKind: CommonModule\nName: ClientModule\n"
                             "Environment: Client\n",
        "ClientModule.xbsl": _CLIENT_HELPER_EN,
        "Api.yaml": "ElementKind: HttpСервис\nName: Api\n",
        "Api.xbsl": "method Handle()\n    val X = ClientModule.Helper()\n;\n",
    }
    found = _lint(files, "code/client-module-in-http-service")
    assert len(found) == 1 and "ClientModule.Helper" in found[0].message


def test_mixed_english_module_in_an_http_service_not_flagged():
    files = {
        "ClientModule.yaml": "ElementKind: CommonModule\nName: ClientModule\n"
                             "Environment: ClientAndServer\n",
        "ClientModule.xbsl": _CLIENT_HELPER_EN,
        "Api.yaml": "ElementKind: HttpСервис\nName: Api\n",
        "Api.xbsl": "method Handle()\n    val X = ClientModule.Helper()\n;\n",
    }
    assert _lint(files, "code/client-module-in-http-service") == []


_QUERY_RU = (
    "    знч Итог = Запрос{\n"
    "        ВЫБРАТЬ ПЕРВЫЕ 1\n"
    "            Код КАК Код\n"
    "        ИЗ\n"
    "            Тест\n"
    "    }\n"
)
_QUERY_EN = (
    "    val Total = Query{\n"
    "        ВЫБРАТЬ ПЕРВЫЕ 1\n"
    "            Код КАК Код\n"
    "        ИЗ\n"
    "            Тест\n"
    "    }\n"
)


def test_query_needs_server_in_a_russian_mixed_module():
    files = {
        "Модуль.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: КлиентИСервер\n",
        "Модуль.xbsl": "метод Считать()\n" + _QUERY_RU + ";\n",
    }
    found = _lint(files, "code/query-needs-server")
    assert len(found) == 1 and "Считать" in found[0].message


def test_query_needs_server_in_an_english_mixed_module():
    # The regression: `Environment: ClientAndServer` was unread, the module never counted as
    # client-side, and a query block the compiler rejects there passed the check.
    files = {
        "Module.yaml": "ElementKind: CommonModule\nName: Module\n"
                       "Environment: ClientAndServer\n",
        "Module.xbsl": "method Read()\n" + _QUERY_EN + ";\n",
    }
    found = _lint(files, "code/query-needs-server")
    assert len(found) == 1 and "Read" in found[0].message


def test_query_with_the_server_annotation_of_an_english_module_not_flagged():
    files = {
        "Module.yaml": "ElementKind: CommonModule\nName: Module\n"
                       "Environment: ClientAndServer\n",
        "Module.xbsl": "@OnServer\nmethod Read()\n" + _QUERY_EN + ";\n",
    }
    assert _lint(files, "code/query-needs-server") == []


def test_server_english_module_leaves_its_query_alone():
    files = {
        "Module.yaml": "ElementKind: CommonModule\nName: Module\nEnvironment: Server\n",
        "Module.xbsl": "method Read()\n" + _QUERY_EN + ";\n",
    }
    assert _lint(files, "code/query-needs-server") == []
