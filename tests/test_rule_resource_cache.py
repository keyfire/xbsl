"""A client-available server method that only reads the text of a package resource."""

import json

import pytest

from xbsl import engine, i18n, parser as P

RULE = "code/resource-read-without-cache"

RU = {
    "module": "ВидЭлемента: ОбщийМодуль\nИмя: Files\nОкружение: Сервер\n",
    "both": "ВидЭлемента: ОбщийМодуль\nИмя: Files\nОкружение: КлиентИСервер\n",
    "catalog": "ВидЭлемента: Справочник\nИмя: Files\n",
    "form": "ВидЭлемента: КомпонентИнтерфейса\nИмя: Files\n",
    "server": "@НаСервере", "client": "@НаКлиенте", "available": "@ДоступноСКлиента",
    "handler": "@Обработчик", "scope": "@ВПроекте", "cache": "КешироватьРезультат",
    "true": "Истина", "false": "Ложь", "or": "или",
    "method": "метод", "return": "возврат", "string": "Строка",
    "root": "ПакетРесурсов", "current": "Текущий", "get": "Получить",
    "open": "ОткрытьПотокЧтения", "read": "ПрочитатьКакСтроку",
}
EN = {
    "module": "ElementKind: CommonModule\nName: Files\nEnvironment: Server\n",
    "both": "ElementKind: CommonModule\nName: Files\nEnvironment: ClientAndServer\n",
    "catalog": "ElementKind: Catalog\nName: Files\n",
    "form": "ElementKind: InterfaceComponent\nName: Files\n",
    "server": "@OnServer", "client": "@OnClient", "available": "@AvailableFromClient",
    "handler": "@Handler", "scope": "@InProject", "cache": "CacheResult",
    "true": "True", "false": "False", "or": "or",
    "method": "method", "return": "return", "string": "String",
    "root": "ResourcesPackage", "current": "Current", "get": "Get",
    "open": "OpenReadableStream", "read": "ReadAsString",
}


def words(english):
    return EN if english else RU


def chain(english=False, *, path="FileName", encoding="", root=None):
    w = words(english)
    return (f"{root or w['root']}.{w['current']}().{w['get']}({path})"
            f".{w['open']}().{w['read']}({encoding})")


def reader(english=False, *, annotations=None, params=None, body=None, **chain_parts):
    w = words(english)
    if annotations is None:
        annotations = f"{w['server']} {w['available']}"
    if params is None:
        params = f"FileName: {w['string']}"
    if body is None:
        body = f"{w['return']} {chain(english, **chain_parts)}"
    return f"{annotations}\n{w['method']} Text({params}): {w['string']}\n    {body}\n;\n"


def project(english=False, *, kind="module", **kwargs):
    return {"Files.yaml": words(english)[kind], "Files.xbsl": reader(english, **kwargs)}


def lint(files):
    return engine.run_sources([engine.load_text(p, t) for p, t in files.items()], select={RULE})


def assert_parses(files, *skip):
    for path, text in files.items():
        if path.endswith(".xbsl") and path not in skip:
            assert P.parse(engine.load_text(path, text))[1] == [], path


def test_registration_is_info_project_scope_and_on_by_default():
    rule = next(r for r in engine.RULES if r.id == RULE)
    assert rule.severity.value == "info"
    assert rule.scope == "project"
    assert rule.tier == "D"
    assert rule.enabled_by_default
    assert rule.mapper is not None


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_client_available_reader_without_cache_is_reported(english):
    files = project(english)
    assert_parses(files)
    found = lint(files)
    assert len(found) == 1
    diagnostic = found[0]
    keyword = words(english)["method"]
    assert (diagnostic.path, diagnostic.line, diagnostic.col) == ("Files.xbsl", 2, len(keyword) + 2)
    assert diagnostic.severity.value == "info"
    assert diagnostic.fix is None
    assert "'Files.Text'" in diagnostic.message


@pytest.mark.needs_data
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_message_suggests_lifetime_cache_and_client_parameters_in_its_language(lang):
    i18n.set_lang(lang)
    try:
        message = lint(project())[0].message
    finally:
        i18n.set_lang("ru")
    if lang == "en":
        for part in ("CacheResult = True", "AvailableFromClient", "ClientWorkParameters",
                     "ResourcesPackage", "how long"):
            assert part in message
    else:
        for part in ("КешироватьРезультат = Истина", "ДоступноСКлиента", "ПараметрыРаботыКлиента",
                     "ПакетРесурсов", "как долго"):
            assert part in message


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_annotations_on_separate_lines_anchor_on_the_method_name(english):
    w = words(english)
    files = project(english, annotations=f"// Reads a style sheet.\n{w['scope']}\n{w['server']} {w['available']}")
    assert_parses(files)
    found = lint(files)
    assert [(d.line, d.col) for d in found] == [(4, len(w["method"]) + 2)]


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("state,expected", [
    ("missing", 1), ("false", 1), ("true", 0), ("unknown", 0), ("expression", 0),
])
def test_cache_states(english, state, expected):
    w = words(english)
    value = {"false": w["false"], "true": w["true"], "unknown": "Setting",
             "expression": f"{w['false']} {w['or']} Setting"}
    argument = "" if state == "missing" else f"({w['cache']} = {value[state]})"
    files = project(english, annotations=f"{w['server']} {w['available']}{argument}")
    assert_parses(files)
    assert len(lint(files)) == expected


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("server-only", 0),
    ("client-variant", 0),
    ("handler", 0),
    ("both-environments-module", 1),
    ("both-environments-module-without-server-annotation", 0),
    ("server-kind-without-server-annotation", 1),
    ("form-module", 1),
])
def test_execution_environment_follows_the_shared_facts(english, case, expected):
    w = words(english)
    annotations, kind = {
        "server-only": (w["server"], "module"),
        "client-variant": (f"{w['server']} {w['client']} {w['available']}", "module"),
        "handler": (f"{w['handler']} {w['server']} {w['available']}", "module"),
        "both-environments-module": (None, "both"),
        "both-environments-module-without-server-annotation": (w["available"], "both"),
        "server-kind-without-server-annotation": (w["available"], "catalog"),
        "form-module": (None, "form"),
    }[case]
    files = project(english, kind=kind, annotations=annotations)
    assert_parses(files)
    assert len(lint(files)) == expected


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("case", ["literal-path", "literal-encoding", "parameter-encoding",
                                  "named-arguments", "literal-default"])
def test_safe_literal_and_parameter_arguments_are_accepted(english, case):
    w = words(english)
    path_name, encoding_name = ("Path", "Encoding") if english else ("Путь", "Кодировка")
    kwargs = {
        "literal-path": {"path": '"styles/site.css"'},
        "literal-encoding": {"encoding": '"utf-8"'},
        "parameter-encoding": {"params": f"FileName: {w['string']}, Charset: {w['string']}",
                               "encoding": "Charset"},
        "named-arguments": {"path": f"{path_name} = FileName", "encoding": f'{encoding_name} = "utf-8"'},
        "literal-default": {"params": f'FileName: {w["string"]} = "site.css"'},
    }[case]
    files = project(english, **kwargs)
    assert_parses(files)
    assert len(lint(files)) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("case", [
    "write", "external-call", "user", "settings", "unknown-dependency", "own-method",
    "nested-call-in-argument", "concatenation", "interpolation", "interpolated-call",
    "encoding-member", "bytes", "reference", "safe-navigation", "non-null", "deferred-lambda",
    "try-catch", "local-then-return", "ternary", "default-from-call", "extra-argument",
    "stream-without-read", "extra-link", "type-arguments", "current-with-argument",
    "get-without-argument", "open-with-argument",
])
def test_reads_with_any_other_dependency_are_silent(english, case):
    w = words(english)
    ret = w["return"]
    users, current_user = ("Users", "CurrentUser") if english else ("Пользователи", "ТекущийПользователь")
    bytes_read, reference = ("ReadAsBytes", "Reference") if english else ("ПрочитатьКакБайты", "Ссылка")
    charset = "Encoding.Utf8" if english else "Кодировка.Utf8"
    val = "val" if english else "знч"
    try_block = (f"try\n        {ret} {chain(english)}\n    catch Error: ResourceNotFoundException\n"
                 f"        {ret} \"\"\n    ;" if english else
                 f"попытка\n        {ret} {chain(english)}\n    поймать Ошибка: ИсключениеРесурсНеНайден\n"
                 f"        {ret} \"\"\n    ;")
    kwargs = {
        "write": {"body": f"Audit.Write(FileName)\n    {ret} {chain(english)}"},
        "external-call": {"path": "Gateway.Fetch(FileName)"},
        "user": {"path": f"{users}.{current_user}().ToString()" if english
                 else f"{users}.{current_user}().ВСтроку()"},
        "settings": {"path": "Settings.Theme"},
        "unknown-dependency": {"path": "DefaultName"},
        "own-method": {"path": "Normalize(FileName)"},
        "nested-call-in-argument": {"path": "FileName.Trim()" if english else "FileName.Обрезать()"},
        "concatenation": {"path": '"styles/" + FileName'},
        "interpolation": {"path": '"styles/%FileName"'},
        "interpolated-call": {"path": '"styles/%{Settings.Theme()}.css"'},
        "encoding-member": {"encoding": charset},
        "bytes": {"body": f"{ret} {chain(english).replace(w['read'], bytes_read)}"},
        "reference": {"body": f"{ret} {chain(english).rsplit('.', 2)[0]}.{reference}"},
        "safe-navigation": {"body": f"{ret} {chain(english).replace(').', ')?.', 1)}"},
        "non-null": {"body": f"{ret} {chain(english).replace('(FileName).', '(FileName)!.')}"},
        "deferred-lambda": {"body": f"{ret} () -> {chain(english)}"},
        "try-catch": {"body": try_block},
        "local-then-return": {"body": f"{val} Content = {chain(english)}\n    {ret} Content"},
        "ternary": {"body": f'{ret} FileName == "" ? "" : {chain(english)}'},
        "default-from-call": {"params": f"FileName: {w['string']} = Settings.Name()"},
        "extra-argument": {"encoding": '"utf-8", FileName'},
        "current-with-argument": {"body": f"{ret} {chain(english).replace(w['current'] + '()', w['current'] + '(FileName)')}"},
        "get-without-argument": {"path": ""},
        "open-with-argument": {"body": f"{ret} {chain(english).replace(w['open'] + '()', w['open'] + '(FileName)')}"},
        "stream-without-read": {"body": f"{ret} {chain(english).rsplit('.', 1)[0]}"},
        "extra-link": {"body": f"{ret} {chain(english)}.{'ToString' if english else 'ВСтроку'}()"},
        "type-arguments": {"body": f"{ret} {chain(english).replace(w['get'] + '(', w['get'] + '<' + w['string'] + '>(')}"},
    }[case]
    files = project(english, **kwargs)
    if case == "deferred-lambda":
        files["Files.xbsl"] = files["Files.xbsl"].replace(f"): {w['string']}\n", f"): () -> {w['string']}\n")
    assert_parses(files)
    assert lint(files) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_text_already_delivered_by_client_parameters_is_silent(english):
    w = words(english)
    files = project(english, annotations=w["server"])
    if english:
        files["Shared.yaml"] = ("ElementKind: ClientWorkParameters\nName: Shared\n"
                                "Parameters:\n  - Name: Styles\n    Type: String\n")
        files["Shared.xbsl"] = ("@Handler @OnServer\nstatic method ComputeClientWorkParameters(): Shared.Parameters\n"
                                "    return new Shared.Parameters(Styles = Files.Text(\"site.css\"))\n;\n")
    else:
        files["Shared.yaml"] = ("ВидЭлемента: ПараметрыРаботыКлиента\nИмя: Shared\n"
                                "Параметры:\n  - Имя: Styles\n    Тип: Строка\n")
        files["Shared.xbsl"] = ("@Обработчик @НаСервере\nстатический метод ВычислитьПараметрыРаботыКлиента(): Shared.Параметры\n"
                                "    возврат новый Shared.Параметры(Styles = Files.Text(\"site.css\"))\n;\n")
    assert_parses(files)
    assert lint(files) == []
    # The same reader opened to the client is reported again.
    files["Files.xbsl"] = reader(english)
    assert len(lint(files)) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("case", [
    "parameter", "parameter-other-case", "module-structure", "module-constant", "module-method",
    "import", "project-element", "project-element-other-spelling", "broken-project-element",
    "own-metadata-attribute", "component-property", "unknown-base", "inherited-project-property",
])
def test_root_must_denote_the_platform_type(english, case):
    w = words(english)
    root = w["root"]
    other = EN["root"] if not english else RU["root"]
    files = project(english)
    healthy = dict(files)
    kind_line = "ElementKind: CommonModule\nName: " if english else "ВидЭлемента: ОбщийМодуль\nИмя: "
    if case == "parameter":
        files["Files.xbsl"] = reader(english, params=f"FileName: {w['string']}, {root}: {w['string']}")
    elif case == "parameter-other-case":
        files["Files.xbsl"] = reader(english, params=f"FileName: {w['string']}, {root.lower()}: {w['string']}")
    elif case == "module-structure":
        files["Files.xbsl"] += ("\nstructure " if english else "\nструктура ") + f"{root}\n" + (
            f"    var Path: {w['string']}\n;\n" if english else f"    пер Путь: {w['string']}\n;\n")
    elif case == "module-constant":
        files["Files.xbsl"] += ("\nconst " if english else "\nконст ") + f'{root} = "x"\n'
    elif case == "module-method":
        files["Files.xbsl"] += f"\n{w['method']} {root}(): {w['string']}\n    {w['return']} \"x\"\n;\n"
    elif case == "import":
        files["Files.xbsl"] = ("import" if english else "импорт") + f" Acme::{root}\n\n" + files["Files.xbsl"]
    elif case == "project-element":
        files["other/Package.yaml"] = kind_line + root + "\n"
    elif case == "project-element-other-spelling":
        files["other/Package.yaml"] = kind_line + other + "\n"
    elif case == "broken-project-element":
        files[f"other/{root}.yaml"] = "bad: [\n"
    elif case == "own-metadata-attribute":
        attributes = "Attributes" if english else "Реквизиты"
        name, kind = ("Name", "Type") if english else ("Имя", "Тип")
        files["Files.yaml"] = w["catalog"] + f"{attributes}:\n  - {name}: {root}\n    {kind}: {w['string']}\n"
        healthy["Files.yaml"] = w["catalog"]
    elif case == "component-property":
        properties = "Properties" if english else "Свойства"
        name, kind = ("Name", "Type") if english else ("Имя", "Тип")
        files["Files.yaml"] = w["form"] + f"{properties}:\n  - {name}: {root}\n    {kind}: {w['string']}\n"
        healthy["Files.yaml"] = w["form"]
    elif case == "unknown-base":
        # An unknown base may give the form a property named like the root.
        inherits = "Inherits:\n  Type: " if english else "Наследует:\n  Тип: "
        files["Files.yaml"] = w["form"] + inherits + "UnknownBase\n"
        healthy["Files.yaml"] = w["form"] + inherits + ("Form" if english else "Форма") + "\n"
    elif case == "inherited-project-property":
        inherits = "Inherits:\n  Type: " if english else "Наследует:\n  Тип: "
        properties = "Properties" if english else "Свойства"
        name, kind = ("Name", "Type") if english else ("Имя", "Тип")
        base = w["form"].replace("Files", "Base")
        files["Files.yaml"] = healthy["Files.yaml"] = w["form"] + inherits + "Base\n"
        files["Base.yaml"] = base + f"{properties}:\n  - {name}: {root}\n    {kind}: {w['string']}\n"
        healthy["Base.yaml"] = base + f"{properties}:\n  - {name}: Caption\n    {kind}: {w['string']}\n"
    assert_parses(files)
    assert lint(files) == []
    assert len(lint(healthy)) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("root", ["qualified", "lower-case", "other-type"])
def test_root_spelled_otherwise_is_not_proven(english, root):
    w = words(english)
    written = {"qualified": f"Std::{w['root']}" if english else f"Стд::{w['root']}",
               "lower-case": w["root"].lower(),
               "other-type": "Resource" if english else "Ресурс"}[root]
    files = project(english, root=written)
    assert_parses(files)
    assert lint(files) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("case", [
    "duplicate-method", "broken-module", "broken-metadata", "missing-metadata",
    "malformed-name", "missing-name", "duplicate-element",
])
def test_ambiguous_or_broken_declarations_are_silent(english, case):
    files = project(english)
    if case == "duplicate-method":
        files["Files.xbsl"] *= 2
    elif case == "broken-module":
        files["Files.xbsl"] += ("method" if english else "метод") + " Broken(\n"
    elif case == "broken-metadata":
        files["Files.yaml"] += "bad: [\n"
    elif case == "missing-metadata":
        del files["Files.yaml"]
    elif case == "malformed-name":
        files["Files.yaml"] = files["Files.yaml"].replace("Files", "2026-01-01")
    elif case == "missing-name":
        files["Files.yaml"] = "\n".join(line for line in files["Files.yaml"].splitlines()
                                        if "Files" not in line) + "\n"
    elif case == "duplicate-element":
        files["other/Files.yaml"] = files["Files.yaml"]
    assert_parses(files, "Files.xbsl" if case == "broken-module" else "")
    assert lint(files) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("change", ["read-returns-bytes", "root-type-unknown"])
def test_chain_is_proven_by_the_type_catalog(change, monkeypatch):
    from xbsl import dataset
    from xbsl.rules import resource_cache

    original = dataset.load_json

    def altered(name, *args, **kwargs):
        data = original(name, *args, **kwargs)
        if name != "stdlib.json":
            return data
        data = dict(data)
        if change == "read-returns-bytes":
            member_types = dict(data["member_types"])
            member_types["ПотокЧтения"] = {**member_types["ПотокЧтения"], "ПрочитатьКакСтроку": "Байты"}
            data["member_types"] = member_types
        else:
            data["names"] = [n for n in data["names"] if n not in ("ПакетРесурсов", "ResourcesPackage")]
        return data

    resource_cache._PROOF.clear()
    monkeypatch.setattr(dataset, "load_json", altered)
    try:
        assert resource_cache._chain() is None
    finally:
        monkeypatch.undo()
        resource_cache._PROOF.clear()
    assert resource_cache._chain() is not None


@pytest.mark.needs_data
def test_missing_data_is_not_remembered(monkeypatch):
    """Data installed while a server process keeps running is picked up without a reset."""
    from xbsl import dataset

    def unavailable(*_args, **_kwargs):
        raise dataset.DatasetError("no platform data")

    dataset.set_data_root(None)  # the reset hooks empty every cache of the rules
    monkeypatch.setattr(dataset, "load_json", unavailable)
    assert lint(project()) == []
    monkeypatch.undo()
    assert len(lint(project())) == 1


@pytest.mark.needs_data
def test_each_reader_of_the_module_is_reported_once():
    files = project()
    files["Files.xbsl"] += "\n" + reader().replace("Text(", "Script(")
    files["Files.xbsl"] += "\n@НаСервере\nметод Plain(): Строка\n    возврат \"x\"\n;\n"
    assert_parses(files)
    messages = {d.line: d.message for d in lint(files)}
    assert sorted(messages) == [2, 7]
    assert "'Files.Text'" in messages[2]
    assert "'Files.Script'" in messages[7]


@pytest.mark.needs_data
@pytest.mark.parametrize("english", [False, True])
def test_mapper_facts_are_json_safe(english):
    from xbsl.rules.resource_cache import _resource_read_mapper

    files = project(english, kind="form")
    for path, text in files.items():
        json.dumps(_resource_read_mapper(engine.load_text(path, text)))
    # A module that never names the package contributes nothing to the reduce.
    other = engine.load_text("Other.xbsl", reader(english, body=f"{words(english)['return']} \"x\""))
    assert _resource_read_mapper(other) is None


@pytest.mark.parametrize("english", [False, True])
def test_yaml_only_installation_without_platform_data_is_silent(english, tmp_path, monkeypatch):
    from xbsl import dataset

    def unavailable(*_args, **_kwargs):
        raise dataset.DatasetError("no language data")

    files = {"Files.yaml": words(english)["catalog"],
             "Other.yaml": words(english)["module"].replace("Files", "Other")}
    monkeypatch.setattr(P, "parse", unavailable)
    dataset.set_data_root(tmp_path)
    try:
        assert lint(files) == []
    finally:
        dataset.set_data_root(None)
