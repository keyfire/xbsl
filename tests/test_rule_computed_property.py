"""Computed property calls use proven endpoints and retain every property site."""

import json

import pytest

from xbsl import engine, i18n, parser as P

RULE = "code/computed-property-server-call"
IMAGE_RULE = "code/image-binding-server-call"


def project(*, english=False, annotation="", expression="=Caption()", prop=None):
    if english:
        return {
            "Data.yaml": "ElementKind: CommonModule\nName: Data\nEnvironment: Server\n",
            "Data.xbsl": f"@OnServer @AvailableFromClient{annotation}\nmethod Read(): String\n    return \"text\"\n;\n",
            "Panel.yaml": "ElementKind: InterfaceComponent\nName: Panel\nContent:\n  - Type: Label\n"
                          f"    {prop or 'Title'}: {expression}\n",
            "Panel.xbsl": "method Caption(): String\n    return Wrapper()\n;\nmethod Wrapper(): String\n    return Data.Read()\n;\n",
        }
    return {
        "Data.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Data\nОкружение: Сервер\n",
        "Data.xbsl": f"@НаСервере @ДоступноСКлиента{annotation}\nметод Read(): Строка\n    возврат \"text\"\n;\n",
        "Panel.yaml": "ВидЭлемента: КомпонентИнтерфейса\nИмя: Panel\nСодержимое:\n  - Тип: Надпись\n"
                      f"    {prop or 'Заголовок'}: {expression}\n",
        "Panel.xbsl": "метод Caption(): Строка\n    возврат Wrapper()\n;\nметод Wrapper(): Строка\n    возврат Data.Read()\n;\n",
    }


def lint(files, *rules):
    return engine.run_sources([engine.load_text(p, t) for p, t in files.items()],
                              select=set(rules or (RULE,)))


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_groups_properties_and_reports_full_chain(english):
    files = project(english=english)
    files["Panel.yaml"] += "    Visible: =Data.Read()\n" if english else "    Видимость: =Data.Read()\n"
    i18n.set_lang("en")
    try:
        found = lint(files)
        assert len(found) == 1
        assert found[0].line == 5
        assert "Caption -> Wrapper -> Data.Read" in found[0].message
        assert ("Title:5" if english else "Заголовок:5") in found[0].message
        assert ("Visible:6" if english else "Видимость:6") in found[0].message
        assert found[0].fix is None and found[0].severity.value == "info"
        assert "every" not in found[0].message
    finally:
        i18n.set_lang(None)


def test_registration_is_info_and_opt_in():
    rule = next(r for r in engine.RULES if r.id == RULE)
    assert rule.severity.value == "info"
    assert not rule.enabled_by_default
    assert rule.scope == "project"


@pytest.mark.parametrize("english", [False, True])
def test_yaml_only_installation_without_platform_data_is_silent(english, tmp_path, monkeypatch):
    from xbsl import dataset

    def unavailable(*_args, **_kwargs):
        raise dataset.DatasetError("no language data")

    files = {path: text for path, text in project(english=english, prop="Image" if english else "Изображение").items()
             if path.endswith(".yaml")}
    files["Other.yaml"] = files["Panel.yaml"].replace("Panel", "Other")
    files["Other.yaml"] = files["Other.yaml"].replace("Image", "Title").replace("Изображение", "Заголовок")
    monkeypatch.setattr(P, "parse", unavailable)
    dataset.set_data_root(tmp_path)
    try:
        assert lint(files, RULE, IMAGE_RULE) == []
    finally:
        dataset.set_data_root(None)


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("state,expected", [("missing", 1), ("false", 1), ("true", 0), ("unknown", 0), ("expression", 0)])
def test_cache_states(english, state, expected):
    value = {"false": "False" if english else "Ложь", "true": "True" if english else "Истина",
             "unknown": "Setting", "expression": "False or Setting" if english else "Ложь или Setting"}
    argument = "" if state == "missing" else f"({'CacheResult' if english else 'КешироватьРезультат'} = {value[state]})"
    assert len(lint(project(english=english, annotation=argument))) == expected


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_client_variant_wins_and_can_reach_another_endpoint(english):
    files = project(english=english)
    files["Data.xbsl"] = ("@OnClient " if english else "@НаКлиенте ") + files["Data.xbsl"]
    assert lint(files) == []
    files["Other.yaml"] = files["Data.yaml"].replace("Data", "Other")
    files["Other.xbsl"] = project(english=english)["Data.xbsl"]
    files["Data.xbsl"] = files["Data.xbsl"].replace('"text"', "Other.Read()")
    assert "Other.Read" in lint(files)[0].message


@pytest.mark.needs_data
@pytest.mark.parametrize("expression", ["=Unknown()", "=Data.Missing()", "=Data.Read", "=Data.Part.Read()", "=Space::Data.Read()", "=() -> Data.Read()", '=new Data.Read()'])
def test_unproven_expression_is_silent(expression):
    assert lint(project(english=True, expression=expression)) == []


@pytest.mark.needs_data
def test_events_and_literals_are_silent():
    for prop, expr in [("OnClick", "=Data.Read()"), ("Title", "'=Data.Read()'"), ("Unknown", "=Data.Read()")]:
        assert lint(project(english=True, prop=prop, expression=expr)) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("change", ["duplicate_module", "broken_module", "duplicate_method", "unknown_method", "broken_yaml", "parameter", "local", "field", "property", "stdlib", "lambda", "reference"])
def test_ambiguous_broken_shadowed_and_deferred_targets(change):
    files = project(english=True)
    if change == "duplicate_module":
        files["other/Data.yaml"] = files["Data.yaml"]
    elif change == "broken_module":
        files["Data.xbsl"] += "method Broken(\n"
    elif change == "duplicate_method":
        files["Data.xbsl"] *= 2
    elif change == "unknown_method":
        files["Data.xbsl"] = files["Data.xbsl"].replace("Read", "Different")
    elif change == "broken_yaml":
        files["Data.yaml"] += "bad: [\n"
    elif change == "parameter":
        files["Panel.xbsl"] = files["Panel.xbsl"].replace("method Wrapper()", "method Wrapper(Data: String)")
    elif change == "local":
        files["Panel.xbsl"] = files["Panel.xbsl"].replace("return Data.Read()", 'var Data = "local"\n    return Data.Read()')
    elif change == "field":
        files["Panel.xbsl"] += "var Data: String\n"
    elif change == "property":
        files["Panel.yaml"] += "Properties:\n  - Name: Data\n    Type: String\n"
    elif change == "stdlib":
        files = {p: t.replace("Data", "Users") for p, t in files.items()}
    elif change == "lambda":
        files["Panel.xbsl"] = files["Panel.xbsl"].replace("return Data.Read()", "var callback = () -> Data.Read()\n    return \"text\"")
    elif change == "reference":
        files["Panel.xbsl"] = files["Panel.xbsl"].replace("return Data.Read()", "var callback = Data.Read\n    return \"text\"")
    if change != "broken_module":
        for path, text in files.items():
            if path.endswith(".xbsl"):
                assert P.parse(engine.load_text(path, text))[1] == []
    assert lint(files) == []


@pytest.mark.needs_data
def test_project_properties_inheritance_and_image_ownership():
    files = project(english=True, expression="=Data.Read()", prop="Image")
    assert lint(files, RULE, IMAGE_RULE)[0].rule_id == IMAGE_RULE
    assert len(lint(files, RULE, IMAGE_RULE)) == 1
    files["Panel.yaml"] = files["Panel.yaml"].replace("Type: Label", "Type: Custom")
    files["Custom.yaml"] = "ElementKind: InterfaceComponent\nName: Custom\nProperties:\n  - Name: Image\n    Type: String\n"
    assert lint(files, RULE, IMAGE_RULE)[0].rule_id == RULE
    files["Custom.yaml"] = "ElementKind: InterfaceComponent\nName: Custom\nInherits:\n  Type: Base\n"
    files["Base.yaml"] = "ElementKind: InterfaceComponent\nName: Base\nProperties:\n  - Name: Image\n    Type: String\n"
    assert len(lint(files)) == 1
    files["Base.yaml"] = "ElementKind: InterfaceComponent\nName: Base\nInherits:\n  Type: Custom\n"
    assert lint(files) == []


@pytest.mark.needs_data
def test_cycles_do_not_hide_other_endpoints():
    files = project(english=True)
    files["Panel.xbsl"] = files["Panel.xbsl"].replace("return Data.Read()", "Caption()\n    return Data.Read()")
    assert len(lint(files)) == 1


@pytest.mark.needs_data
def test_unavailable_server_method_is_not_proven_endpoint():
    files = project(english=True)
    files["Data.xbsl"] = files["Data.xbsl"].replace("@AvailableFromClient", "")
    assert lint(files) == []


@pytest.mark.needs_data
def test_non_module_metadata_name_does_not_poison_module():
    files = project(english=True)
    files["assets/Data.yaml"] = "ОбластьВидимости: ВПроекте\n"
    assert len(lint(files)) == 1


@pytest.mark.needs_data
def test_method_named_like_receiver_and_binding_field_are_shadows():
    files = project(english=True)
    files["Panel.xbsl"] += "method Data(): String\n    return \"text\"\n;\n"
    assert lint(files) == []
    files = project(english=True, expression="=Data.Read()")
    files["Panel.xbsl"] += "var Data: String\n"
    assert lint(files) == []


@pytest.mark.needs_data
def test_each_reachable_endpoint_is_grouped_separately():
    files = project(english=True)
    files["Other.yaml"] = files["Data.yaml"].replace("Data", "Other")
    files["Other.xbsl"] = files["Data.xbsl"]
    files["Panel.xbsl"] = files["Panel.xbsl"].replace("return Data.Read()", "Other.Read()\n    return Data.Read()")
    found = lint(files)
    assert len(found) == 2
    assert {d.line for d in found} == {5}


@pytest.mark.needs_data
def test_project_event_and_inherited_property_receiver():
    files = project(english=True, expression="=Data.Read()", prop="Action")
    files["Panel.yaml"] = files["Panel.yaml"].replace("Type: Label", "Type: Custom")
    files["Custom.yaml"] = "ElementKind: InterfaceComponent\nName: Custom\nEvents:\n  - Name: Action\n"
    assert lint(files) == []
    files["Custom.yaml"] = files["Custom.yaml"].replace("Events", "Properties")
    assert len(lint(files)) == 1
    files["Base.yaml"] = "ElementKind: InterfaceComponent\nName: Base\nProperties:\n  - Name: Data\n    Type: String\n"
    files["Panel.yaml"] += "Inherits:\n  Type: Base\n"
    assert lint(files) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("annotation", ["(CacheResult = True)", "(CacheResult = Setting)"])
def test_image_rule_uses_shared_cache_facts(annotation):
    files = project(english=True, prop="Image", expression="=Data.Read()", annotation=annotation)
    assert lint(files, IMAGE_RULE, RULE) == []
    files["Data.xbsl"] = files["Data.xbsl"].replace(annotation, "")
    assert len(lint(files, IMAGE_RULE, RULE)) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_unannotated_method_of_both_environment_module_is_client_wrapper(english):
    files = project(english=english)
    files["WrapperModule.yaml"] = (
        "ElementKind: CommonModule\nName: WrapperModule\nEnvironment: ClientAndServer\n" if english
        else "ВидЭлемента: ОбщийМодуль\nИмя: WrapperModule\nОкружение: КлиентИСервер\n")
    files["WrapperModule.xbsl"] = (
        "method Read(): String\n    return Data.Read()\n;\n" if english
        else "метод Read(): Строка\n    возврат Data.Read()\n;\n")
    files["Panel.xbsl"] = files["Panel.xbsl"].replace("Data.Read()", "WrapperModule.Read()")
    assert len(lint(files)) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("image", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
def test_platform_base_properties_shadow_modules(english, image, indirect):
    receiver = "WriteAndClose" if english else "ЗаписатьИЗакрыть"
    call = "Execute" if english else "Выполнить"
    files = project(english=english, prop=("Image" if english else "Изображение") if image else None)
    files = {p: text.replace("Data", receiver).replace("Read", call) for p, text in files.items()}
    files["Tasks.yaml"] = "ElementKind: Catalog\nName: Tasks\n" if english else "ВидЭлемента: Справочник\nИмя: Tasks\n"
    base = "ObjectForm<Tasks.Object>" if english else "ФормаОбъекта<Tasks.Объект>"
    inherit = "Inherits:\n  Type: " if english else "Наследует:\n  Тип: "
    files["Panel.yaml"] += inherit + ("Base<String>" if indirect else base) + "\n"
    if indirect:
        files["Base.yaml"] = ("ElementKind: InterfaceComponent\nName: Base\n" if english else
                              "ВидЭлемента: КомпонентИнтерфейса\nИмя: Base\n") + inherit + base + "\n"
    assert lint(files, RULE, IMAGE_RULE) == []
    # Removing inheritance restores the actual module call.
    files["Panel.yaml"] = files["Panel.yaml"].split(inherit)[0]
    assert len(lint(files, RULE, IMAGE_RULE)) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_platform_base_namesake_blocks_metadata_only_image_calls(english):
    receiver = "WriteAndClose" if english else "ЗаписатьИЗакрыть"
    call = "Execute" if english else "Выполнить"
    files = project(english=english, prop="Image" if english else "Изображение",
                    expression=f"={receiver}.{call}()")
    files["Data.yaml"] = files["Data.yaml"].replace("Data", receiver)
    del files["Data.xbsl"], files["Panel.xbsl"]
    files["Tasks.yaml"] = "ElementKind: Catalog\nName: Tasks\n" if english else "ВидЭлемента: Справочник\nИмя: Tasks\n"
    inherit = "Inherits:\n  Type: " if english else "Наследует:\n  Тип: "
    files["Panel.yaml"] += inherit + ("ObjectForm<Tasks.Object>" if english else "ФормаОбъекта<Tasks.Объект>") + "\n"
    assert lint(files, IMAGE_RULE) == []
    files["Panel.yaml"] = files["Panel.yaml"].split(inherit)[0]
    assert len(lint(files, IMAGE_RULE)) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_component_context_names_shadow_modules(english):
    receiver = "Components" if english else "Компоненты"
    files = {p: text.replace("Data", receiver) for p, text in project(english=english).items()}
    assert lint(files, RULE, IMAGE_RULE) == []
    files = {p: text.replace(receiver, "Data") for p, text in files.items()}
    assert len(lint(files, RULE, IMAGE_RULE)) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("base", ["unknown", "ambiguous", "cycle"])
def test_unresolved_base_leaves_receivers_unproven(english, base):
    files = project(english=english)
    inherit = "Inherits:\n  Type: " if english else "Наследует:\n  Тип: "
    component = ("ElementKind: InterfaceComponent\nName: Base\n" if english
                 else "ВидЭлемента: КомпонентИнтерфейса\nИмя: Base\n")
    if base == "unknown":
        files["Panel.yaml"] += inherit + "UnknownBase\n"
    elif base == "ambiguous":
        files["Panel.yaml"] += inherit + "Base\n"
        files["one/Base.yaml"] = files["two/Base.yaml"] = component
    else:
        files["Panel.yaml"] += inherit + "Base\n"
        files["Base.yaml"] = component + inherit + "Panel\n"
    assert lint(files, RULE, IMAGE_RULE) == []
    # A resolved platform base without a namesake keeps the module call.
    files["Panel.yaml"] = files["Panel.yaml"].split(inherit)[0] + inherit + ("Form" if english else "Форма") + "\n"
    assert len(lint(files, RULE, IMAGE_RULE)) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_own_method_named_like_inherited_property_is_still_called(english):
    title = "Title" if english else "Заголовок"
    files = {
        "Panel.yaml": ("ElementKind: InterfaceComponent\nName: Panel\nInherits:\n  Type: Form\n"
                       f"  {title}: ={title}()\n" if english else
                       "ВидЭлемента: КомпонентИнтерфейса\nИмя: Panel\nНаследует:\n  Тип: Форма\n"
                       f"  {title}: ={title}()\n"),
        "Panel.xbsl": (f"@OnServer @AvailableFromClient\nmethod {title}(): String\n    return \"text\"\n;\n" if english else
                       f"@НаСервере @ДоступноСКлиента\nметод {title}(): Строка\n    возврат \"text\"\n;\n"),
    }
    found = lint(files)
    assert len(found) == 1
    assert f"Panel.{title}" in found[0].message


@pytest.mark.needs_data
def test_unknown_base_keeps_calls_of_the_own_module():
    files = project(english=True)
    files["Panel.yaml"] += "Inherits:\n  Type: UnknownBase\n"
    files["Panel.xbsl"] = (files["Panel.xbsl"].replace("return Data.Read()", "return Load()")
                           + "@OnServer @AvailableFromClient\nmethod Load(): String\n    return \"text\"\n;\n")
    found = lint(files)
    assert len(found) == 1
    assert "Caption -> Wrapper -> Load" in found[0].message


@pytest.mark.needs_data
@pytest.mark.parametrize("image", [False, True])
@pytest.mark.parametrize("metadata_only", [False, True])
def test_invalid_environment_does_not_abort_healthy_targets(image, metadata_only):
    files = project(english=True, prop="Image" if image else "Title")
    files["Good.yaml"] = files["Data.yaml"].replace("Data", "Good")
    files["Good.xbsl"] = files["Data.xbsl"]
    files["Panel.xbsl"] = files["Panel.xbsl"].replace("return Data.Read()", "Data.Read()\n    return Good.Read()")
    files["Data.yaml"] = files["Data.yaml"].replace("Environment: Server", "Environment: [Server]")
    files["Data.xbsl"] = files["Data.xbsl"].replace("@OnServer ", "")
    if metadata_only:
        del files["Data.xbsl"]
    found = lint(files, RULE, IMAGE_RULE)
    assert len(found) == 1
    assert found[0].severity.value == "info"
    assert "Good.Read" in found[0].message
    assert "Data.Read" not in found[0].message


@pytest.mark.needs_data
@pytest.mark.parametrize("field", [
    "Name: 2026-01-01", "Name: [Panel]", "Name: {key: value}",
    "Environment: [Client]", "Environment: {key: value}", "Environment: 2026-01-01",
    "Inherits: [Base]", "Inherits:\n  Type: 2026-01-01", "Inherits:\n  Type: [Base]", "Inherits: {}",
    "Properties: {Name: Data}", "Properties:\n  - Name: 2026-01-01", "Properties:\n  - Type: String",
    "Events:\n  - Name: [Data]", "Events:\n  - OnSave",
])
def test_invalid_used_metadata_fields_are_json_safe_and_not_analyzed(field):
    from xbsl.rules._server_calls import server_call_mapper

    files = project(english=True)
    files["Healthy.yaml"] = files["Panel.yaml"].replace("Panel", "Healthy")
    files["Healthy.xbsl"] = files["Panel.xbsl"]
    if field.startswith("Name:"):
        files["Panel.yaml"] = files["Panel.yaml"].replace("Name: Panel", field)
    else:
        files["Panel.yaml"] += field + "\n"
    source = engine.load_text("Panel.yaml", files["Panel.yaml"])
    json.dumps(server_call_mapper(source))
    found = lint(files)
    assert len(found) == 1
    assert found[0].path == "Healthy.yaml"
    assert found[0].severity.value == "info"
