"""Short type names have no priority between a subsystem root and its packages."""
import pytest
from xbsl import engine

pytestmark=pytest.mark.needs_data

def project(where="Storage", imports="", written="SharedEntry.Reference?", public=True):
    scope="InProject" if public else "InSubsystem"
    files={
        "Project.yaml":"Vendor: Acme\nName: Checks\nVersion: 1.0\n",
        "Storage/Subsystem.yaml":"",
        "Remote/Subsystem.yaml":"Using: [Storage]\n",
        "Storage/SharedEntry.yaml":f"ElementKind: Catalog\nName: SharedEntry\nVisibilityScope: {scope}\n",
        "Storage/History/SharedEntry.yaml":f"ElementKind: Catalog\nName: SharedEntry\nVisibilityScope: {scope}\n",
        f"{where}/Probe.yaml":"ElementKind: CommonModule\nName: Probe\n",
        f"{where}/Probe.xbsl":imports+f"method Check(Value: {written})\n;\n",
        f"{where}/Consumer.yaml":"ElementKind: Catalog\nName: Consumer\n"+(
            "Import: [Storage, 'Storage::History']\n" if where=="Remote" and imports.count("import")==2 else
            "Import: [Storage]\n" if where=="Remote" and imports else "")+
            f"Attributes:\n    - Name: Value\n      Type: {written}\n",
    }
    return {"Acme/Checks/"+name: text for name,text in files.items()}

def lint(files, rule):
    return list(engine.run_sources([engine.load_text(name,text) for name,text in files.items()],select={rule}))

@pytest.mark.parametrize("rule",["code/ambiguous-type","yaml/ambiguous-type"])
@pytest.mark.parametrize("where,imports",[("Storage",""),("Storage/History",""),("Remote","import Storage\nimport Storage::History\n")])
def test_short_reference_is_ambiguous_in_each_visible_namespace(rule,where,imports):
    diag,=lint(project(where,imports),rule)
    assert diag.severity.value=="error"
    assert diag.data=={"namespaces":["Storage","Storage::History"],"name":"SharedEntry"}
    assert diag.fix is None

@pytest.mark.parametrize("rule",["code/ambiguous-type","yaml/ambiguous-type"])
def test_a_qualified_reference_names_one_owner(rule):
    assert lint(project(written="Storage::SharedEntry.Reference?"),rule)==[]

@pytest.mark.parametrize("rule",["code/ambiguous-type","yaml/ambiguous-type"])
@pytest.mark.parametrize("imports",["", "import Storage\n"])
def test_a_foreign_reference_needs_two_visible_imports(rule,imports):
    assert lint(project("Remote",imports),rule)==[]

@pytest.mark.parametrize("rule",["code/ambiguous-type","yaml/ambiguous-type"])
def test_invisible_foreign_types_are_not_candidates(rule):
    assert lint(project("Remote","import Storage\nimport Storage::History\n",public=False),rule)==[]

@pytest.mark.parametrize("rule",["code/ambiguous-type","yaml/ambiguous-type"])
def test_removing_the_duplicate_resolves_the_same_reference(rule):
    files=project()
    del files["Acme/Checks/Storage/History/SharedEntry.yaml"]
    assert lint(files,rule)==[]

def test_a_local_type_declaration_explains_the_name():
    files=project(written="SharedEntry?")
    files["Acme/Checks/Storage/Probe.xbsl"]="structure SharedEntry\n;\n"+files["Acme/Checks/Storage/Probe.xbsl"]
    assert lint(files,"code/ambiguous-type")==[]

def test_names_from_separate_projects_are_not_combined():
    files=project()
    del files["Acme/Checks/Storage/History/SharedEntry.yaml"]
    other=project()
    del other["Acme/Checks/Storage/SharedEntry.yaml"]
    files.update({k.replace("Acme/Checks/","Acme/Other/"):v for k,v in other.items()})
    assert lint(files,"code/ambiguous-type")==[]

def test_literal_text_and_value_names_are_not_type_references():
    files=project(written="String")
    files["Acme/Checks/Storage/Probe.xbsl"]='method Check(SharedEntry: String)\n    val Text = "SharedEntry.Reference"\n;\n'
    assert lint(files,"code/ambiguous-type")==[]

@pytest.mark.parametrize("rule", ["code/ambiguous-type", "yaml/ambiguous-type"])
@pytest.mark.parametrize("written", [
    "SharedEntry.Reference|Storage::SharedEntry.Reference",
    "Map<SharedEntry.Reference, Storage::SharedEntry.Reference>",
])
def test_short_type_in_a_mixed_qualified_expression_is_still_checked(rule, written):
    assert len(lint(project(written=written), rule)) == 1

@pytest.mark.parametrize("rule", ["code/ambiguous-type", "yaml/ambiguous-type"])
def test_project_types_take_priority_over_a_platform_namesake(rule):
    files = {path.replace("SharedEntry", "String"): text.replace("SharedEntry", "String")
             for path, text in project().items()}
    assert len(lint(files, rule)) == 1

@pytest.mark.parametrize("written", ['=GetType("SharedEntry")', '$SharedEntry', 'GetType(SharedEntry)'])
def test_yaml_bindings_and_other_non_type_values_are_not_scanned(written):
    assert lint(project(written=written), "yaml/ambiguous-type") == []

@pytest.mark.parametrize("rule", ["code/ambiguous-type", "yaml/ambiguous-type"])
def test_whitespace_around_a_namespace_separator_preserves_qualification(rule):
    assert lint(project(written="Storage :: SharedEntry.Reference?"), rule) == []
