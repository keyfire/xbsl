"""xbsl/extract/elementhandlers.py: the handlers the compiler declares for element modules.

The interpreter itself runs over the classes of a distribution, which a checkout does not
carry; these tests hold the parts that decide the shape of the data on their own - how a
project type class names its element and module, how the modes of several paths join, what one
value stands for when the paths disagree, and how the branches of the access-control target and
of a kind test are told apart.
"""

from xbsl.extract import elementhandlers as eh

_KINDS = {"Справочник": "Catalog", "РегистрСведений": "InformationRegister",
          "ПланОбмена": "ExchangePlan", "ЗапланированноеЗадание": "ScheduledJob",
          "КлючДоступа": "AccessKey", "Проект": "Project"}
_WORDS = {"Object": "Объект", "RecordSet": "НаборЗаписей", "Record": "Запись"}
_TYPES = {"Users": "Пользователи"}


def _element(name):
    return eh.element_of(name, _KINDS, _WORDS, _TYPES)


def test_a_class_names_the_kind_and_the_module():
    assert _element("acme/catalog/CatalogG5ProjectType") == ("Справочник", "")
    assert _element("acme/catalog/CatalogObjectG5ProjectType") == ("Справочник", "Объект")
    assert _element("acme/register/InformationRegisterRecordSetG5ProjectType") == (
        "РегистрСведений", "НаборЗаписей")
    assert _element("acme/register/InformationRegisterRecordG5ProjectType") == (
        "РегистрСведений", "Запись")


def test_a_nested_class_and_the_node_of_an_exchange_plan():
    assert _element("acme/job/JobTypes$ScheduledJobG5ProjectType") == (
        "ЗапланированноеЗадание", "")
    assert _element("acme/plan/ExchangePlanNodeG5ProjectType") == ("ПланОбмена", "Объект")


def test_a_type_outside_the_kind_table_is_named_by_the_facet_pages():
    assert _element("acme/users/UsersObjectG5ProjectType") == ("Пользователи", "Объект")


def test_what_names_no_module_is_left_unmapped():
    assert _element("acme/keys/AccessKeyForAdminG5ProjectType") is None
    assert _element("acme/misc/SomethingElse") is None


def test_the_modes_of_the_paths_join_into_one_range():
    # Below 8.0 on one path, from 8.0 on on the other: every mode, no range at all.
    assert eh._merge_modes([(None, (8, 0)), ((8, 0), None)]) == (None, None)
    assert eh._merge_modes([(None, (8, 0))]) == (None, (8, 0))
    assert eh._merge_modes([((9, 0), None), ((9, 0), None)]) == ((9, 0), None)


def test_a_gap_between_the_ranges_gives_no_range():
    assert eh._merge_modes([(None, (7, 0)), ((9, 0), None)]) is None


def test_paths_that_disagree_keep_what_they_may_hold():
    first, second = ("meth", ("term", "A", "А")), ("meth", ("term", "B", "Б"))
    assert eh._join([first, first]) == first
    assert eh._join([first, second]) == ("oneof", (first, second))
    assert eh._join([("list", ()), ("list", (first,))]) == ("list", (first,))
    assert eh._join([None, None]) is None


def test_the_application_project_is_the_module_of_the_project():
    assert _element("acme/prj/ApplicationProjectG5ProjectType") == ("Проект", "")
    # A library and an extension project keep classes of their own and no kind.
    assert _element("acme/prj/LibraryProjectG5ProjectType") is None


# --- the branches the interpreter tells apart ------------------------------------------------

_ENTITY = "acme/entity/IEntityType"
_KEY_TEST = next(iter(eh._KIND_TESTS))


class _Classes:
    """The ancestors of a few made-up classes, in place of the classes of a distribution."""

    _PARENTS = {"acme/catalog/CatalogObjectG5ProjectType": frozenset({_ENTITY}),
                "acme/service/HttpServiceG5ProjectType": frozenset()}

    def get(self, _name):
        return None

    def ancestors(self, name):
        return self._PARENTS.get(name, frozenset())


def _interpreter():
    return eh.Interpreter(_Classes())


def _path():
    return eh._Path(0, [], {}, tested="acme/IG5SingletonProjectType")


def test_the_target_of_the_module_is_asked_of_the_access_control_info():
    found = _interpreter()._call("P", _path(), 0xB9, eh._ACCESS_INFO, "getTargetType",
                                 "(Lx;)Ly;", ["Lx;"], [("param", 1)], None, 0, True, "P")
    assert found == ("target",)


def test_a_path_past_the_target_test_stands_for_the_managers_alone():
    _continue, fall, jump = _interpreter()._condition(_path(), 0xC7, ("target",), 40, 10)
    assert jump.managed and not fall.managed  # ifnonnull jumps when there is a target


def test_a_test_of_the_target_is_kept_apart_from_the_other_tests():
    value = ("isinst", ("target",), _ENTITY)
    _continue, fall, jump = _interpreter()._condition(_path(), 0x99, value, 40, 10)
    assert fall.target_requires == {_ENTITY} and not fall.requires  # ifeq falls when true
    assert not jump.target_requires


def test_a_kind_test_names_the_kind_it_fails_for():
    interpreter = _interpreter()
    term = ("term", "PrivilegeOnAction", "ПравоНаДействие")
    interpreter.static = lambda owner, name, depth: term
    _continue, fall, jump = interpreter._condition(_path(), 0x99, ("kindtest", _KEY_TEST), 40, 10)
    assert jump.kind == term and fall.kind is None
    jump.tested = "acme/keys/AccessKeyG5ProjectType"
    interpreter._record(jump, ("term", "ComputeAccessPermissions", "ВычислитьРазрешенияДоступа"))
    assert interpreter.found[0].kind == term


def test_the_managed_path_keeps_the_managers_whose_target_passes_its_tests():
    managers = {"acme/catalog/CatalogG5ProjectType": "acme/catalog/CatalogObjectG5ProjectType",
                "acme/service/HttpServiceG5ProjectType": "acme/service/HttpServiceG5ProjectType"}
    anything = eh.Found("acme/IG5SingletonProjectType", ("term", "A", "А"), None, None,
                        managed=True)
    entity = eh.Found("acme/IG5SingletonProjectType", ("dyn", "source"), None, None,
                      managed=True, target_requires=frozenset({_ENTITY}))
    classes = _Classes()
    assert eh.controls(classes, managers, "acme/catalog/CatalogG5ProjectType", anything)
    assert eh.controls(classes, managers, "acme/service/HttpServiceG5ProjectType", anything)
    assert eh.controls(classes, managers, "acme/catalog/CatalogG5ProjectType", entity)
    assert not eh.controls(classes, managers, "acme/service/HttpServiceG5ProjectType", entity)
    # The control: a module no part names as a manager - a common module - has no target.
    assert not eh.controls(classes, managers, "acme/common/CommonModuleG5ProjectType", anything)


# --- a handler declared once per item of a collection the description fills ------------------

_SOURCE = "Metadata.sources"


def _model_class(stores_call: bool = True):
    """A made-up model whose constructor fills its field `items` - from a getter of its
    metadata, or straight from the parameter when `stores_call` is off."""
    pool = {
        1: (1, "acme/model/Model"), 2: (7, 1),
        3: (1, "acme/meta/Metadata"), 4: (7, 3),
        5: (1, "sources"), 6: (1, "()Ljava/util/List;"), 7: (12, (5, 6)), 8: (11, (4, 7)),
        9: (1, "items"), 10: (1, "Ljava/util/Collection;"), 11: (12, (9, 10)), 12: (9, (2, 11)),
    }
    # aload_0, aload_1, [invokeinterface #8 1 0], putfield #12, return
    call = bytes([0xB9, 0x00, 0x08, 0x01, 0x00]) if stores_call else b""
    code = bytes([0x2A, 0x2B]) + call + bytes([0xB5, 0x00, 0x0C, 0xB1])
    methods = [eh._Method("<init>", "(Lacme/meta/Metadata;)V", False, code)]
    return eh._Class("acme/model/Model", "java/lang/Object", [], pool, methods)


class _OneClass(_Classes):
    def __init__(self, klass):
        self._klass = klass

    def get(self, name):
        return self._klass if name == self._klass.name else None


def test_a_field_of_a_model_is_named_by_the_getter_it_is_filled_from():
    assert eh._filled_from(_OneClass(_model_class()), "acme/model/Model", "items") == _SOURCE
    interpreter = eh.Interpreter(_OneClass(_model_class()))
    assert interpreter._field_source("acme/model/Model", "items") == _SOURCE


def test_control_a_field_filled_from_a_parameter_is_named_by_itself():
    index = _OneClass(_model_class(stores_call=False))
    assert eh._filled_from(index, "acme/model/Model", "items") is None
    assert eh.Interpreter(index)._field_source("acme/model/Model", "items") == "Model.items"


def test_the_body_of_a_loop_over_the_collection_is_per_item():
    interpreter = _interpreter()
    path = _path()
    each = interpreter._call("P", path, 0xB9, "java/util/Collection", "iterator",
                             "()Ljava/util/Iterator;", [], [], ("coll", _SOURCE), 0, True, "P")
    assert each == ("each", _SOURCE)
    test = interpreter._call("P", path, 0xB9, "java/util/Iterator", "hasNext", "()Z", [], [],
                             each, 0, True, "P")
    assert test == ("hasnext", _SOURCE)
    _continue, fall, jump = interpreter._condition(path, 0x99, test, 40, 10)
    assert fall.per == _SOURCE and jump.per is None  # ifeq falls into the body


def test_a_method_added_in_the_loop_carries_the_collection():
    interpreter = _interpreter()
    path = _path()
    path.per = _SOURCE
    meth = ("meth", ("term", "OnCreateOnBasis", "ПриСозданииНаОсновании"))
    interpreter._call("P", path, 0xB9, "java/util/List", "add", "(Ljava/lang/Object;)Z",
                      ["Ljava/lang/Object;"], [meth], ("listref", 7), 0, True, "P")
    assert path.lists[7] == (("meth", meth[1], _SOURCE),)
    interpreter._record(path, meth[1], _SOURCE)
    assert interpreter.found[0].per == _SOURCE


def test_control_a_method_added_outside_a_loop_is_declared_unconditionally():
    interpreter = _interpreter()
    path = _path()
    meth = ("meth", ("term", "OnFill", "ПриЗаполнении"))
    interpreter._call("P", path, 0xB9, "java/util/List", "add", "(Ljava/lang/Object;)Z",
                      ["Ljava/lang/Object;"], [meth], ("listref", 7), 0, True, "P")
    assert path.lists[7] == (meth,)


def test_a_row_is_per_item_only_when_every_path_loops_over_one_collection():
    assert eh._per_of({_SOURCE}) == _SOURCE
    assert eh._per_of({_SOURCE, None}) is None
    assert eh._per_of({_SOURCE, "Other.items"}) is None
    assert eh._per_of({None}) is None
