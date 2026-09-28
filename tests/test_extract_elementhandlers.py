"""xbsl/extract/elementhandlers.py: the handlers the compiler declares for element modules.

The interpreter itself runs over the classes of a distribution, which a checkout does not
carry; these tests hold the parts that decide the shape of the data on their own - how a
project type class names its element and module, how the modes of several paths join, and
what one value stands for when the paths disagree.
"""

from xbsl.extract import elementhandlers as eh

_KINDS = {"Справочник": "Catalog", "РегистрСведений": "InformationRegister",
          "ПланОбмена": "ExchangePlan", "ЗапланированноеЗадание": "ScheduledJob",
          "КлючДоступа": "AccessKey"}
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
