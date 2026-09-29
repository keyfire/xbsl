"""Member pairs read from what a class DECLARES (xbsl/extract/classcode.py).

The class here is assembled by the test, byte for byte: a method whose code pushes the two
spellings and makes the call that takes them. No Element data is needed, and no vendor class
is carried in the repository - what is reproduced is the layout of a class file, which is a
public standard.

The case that pays for the module is the last one: the pool ALSO holds `Symbol` next to
`Символ` - the fill parameter of another method - and the neighbourhood reading of the same
pool answers `Symbol`, while the class declares the member `CharAt`.
"""

import struct

from xbsl.extract import classcode
from xbsl.extract.uiterms import enum_pairs


def _utf8(text: str) -> bytes:
    body = text.encode("utf-8")
    return bytes([1]) + struct.pack(">H", len(body)) + body


class _Pool:
    """A constant pool under construction: entries are added and answer with their index."""

    def __init__(self) -> None:
        self.blobs: list[bytes] = []

    def _add(self, blob: bytes) -> int:
        self.blobs.append(blob)
        return len(self.blobs)  # the pool is one-based

    def text(self, value: str) -> int:
        return self._add(_utf8(value))

    def string(self, value: str) -> int:
        return self._add(bytes([8]) + struct.pack(">H", self.text(value)))

    def klass(self, name: str) -> int:
        return self._add(bytes([7]) + struct.pack(">H", self.text(name)))

    def method(self, owner: str, name: str, descriptor: str = "()V") -> int:
        owner_index = self.klass(owner)
        name_index = self.text(name)
        descriptor_index = self.text(descriptor)
        nat = self._add(bytes([12]) + struct.pack(">HH", name_index, descriptor_index))
        return self._add(bytes([10]) + struct.pack(">HH", owner_index, nat))

    def rendered(self) -> bytes:
        return struct.pack(">H", len(self.blobs) + 1) + b"".join(self.blobs)


def _class_of(calls: list[tuple[str, list[str]]], extra_strings: list[str] = [],
              switch_between: bool = False) -> bytes:
    """A class whose single method pushes the strings of each call and makes it.

    `extra_strings` are interned in the pool without being pushed anywhere - the way a name
    that belongs to a parameter or to a neighbouring method sits in a real pool.
    `switch_between` puts a `tableswitch` between the calls: its operand is padded to a
    four-byte boundary and sized by its own table, so a walker that steps over it by a fixed
    length reads the rest of the method as garbage.
    """
    pool = _Pool()
    code_name = pool.text("Code")
    for value in extra_strings:
        pool.string(value)
    def tableswitch() -> bytes:
        out = bytearray([0x03, 0xAA])                      # iconst_0, then the switch
        while (len(body) + len(out)) % 4:
            out += bytes([0x00])                           # padded to a four-byte boundary
        # The offsets are deliberately made of 0xB8 bytes - `invokestatic`. A walker that does
        # not know the shape of a switch reads its table AS CODE, sees calls that are not there
        # and drops the arguments pushed before them.
        out += struct.pack(">iii", -0x47474748, 0, 0)      # default, low, high (0xB8B8B8B8)
        out += struct.pack(">i", -0x47474748)              # the single jump offset
        return bytes(out)

    body = bytearray()
    for index, (owner_and_name, pushed) in enumerate(calls):
        owner, name = owner_and_name.rsplit(".", 1)
        for position, value in enumerate(pushed):
            if switch_between and index and position == 1:
                body += tableswitch()                      # between the two spellings
            body += bytes([0x13]) + struct.pack(">H", pool.string(value))  # ldc_w
        body += bytes([0xB8]) + struct.pack(">H", pool.method(owner, name))  # invokestatic
    body += bytes([0xB1])  # return
    code = struct.pack(">HHI", 8, 1, len(body)) + bytes(body) + struct.pack(">HH", 0, 0)
    this_class = pool.klass("Demo")
    super_class = pool.klass("java/lang/Object")
    name_index = pool.text("build")
    descriptor_index = pool.text("()V")
    method = struct.pack(">HHHH", 0, name_index, descriptor_index, 1)
    method += struct.pack(">HI", code_name, len(code)) + code
    return (
        b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61)
        + pool.rendered()
        + struct.pack(">HHHH", 0, this_class, super_class, 0)  # flags, this, super, interfaces
        + struct.pack(">H", 0)                                  # no fields
        + struct.pack(">H", 1) + method                         # one method
        + struct.pack(">H", 0)                                  # no class attributes
    )


# The calls a fixture makes, addressed the way the reader addresses them - by the tail the
# module itself names, with a package of the test's own in front.
BUILDER = "demo/builders/" + classcode.METHOD_FACTORY
PROPERTY = "demo/builders/" + classcode.PROPERTY_FACTORY
PARAMETER = "demo/builders/CtMetaMethodBuilder.p"


def test_a_declared_method_states_its_pair():
    blob = _class_of([(BUILDER, ["CharAt", "Символ"])])

    assert classcode.declared_members(blob) == {"Символ": "CharAt"}


def test_a_property_is_a_member_too_and_a_parameter_is_not():
    blob = _class_of([
        (PROPERTY, ["Presentation", "Представление"]),
        (PARAMETER, ["Filler", "Заполнитель"]),
    ])

    assert classcode.declared_members(blob) == {"Представление": "Presentation"}


def test_the_declaration_is_read_through_a_switch():
    """A switch has a variable-length operand: misreading it desynchronises the whole walk."""
    blob = _class_of([
        (BUILDER, ["GetLines", "ПолучитьСтроки"]),
        (BUILDER, ["CharAt", "Символ"]),
    ], switch_between=True)

    assert classcode.declared_members(blob) == {
        "ПолучитьСтроки": "GetLines", "Символ": "CharAt",
    }


def test_a_name_the_neighbourhood_would_mispair_is_read_from_the_declaration():
    """`Symbol` belongs to the fill PARAMETER; the member is declared `CharAt`."""
    blob = _class_of(
        [(BUILDER, ["CharAt", "Символ"])],
        extra_strings=["PadFromBegin", "ДополнитьСНачала", "Symbol", "Символ"],
    )

    assert enum_pairs(blob).get("Символ") == "Symbol"      # what adjacency answers
    assert classcode.declared_members(blob)["Символ"] == "CharAt"  # what the class states


def test_a_method_wins_over_a_property_of_the_same_name():
    """The binary-object properties declare `Temporary` as a method and `IsTemporary` as a
    property of one Russian name. The table holds one spelling: which one is a decision, not
    the order the calls came in."""
    blob = _class_of([
        (PROPERTY, ["IsTemporary", "Временные"]),
        (BUILDER, ["Temporary", "Временные"]),
    ])
    reversed_order = _class_of([
        (BUILDER, ["Temporary", "Временные"]),
        (PROPERTY, ["IsTemporary", "Временные"]),
    ])

    assert classcode.declared_members(blob) == {"Временные": "Temporary"}
    assert classcode.declared_members(reversed_order) == {"Временные": "Temporary"}


def _field(pool: _Pool, owner: str, name: str) -> int:
    owner_index = pool.klass(owner)
    nat = pool._add(bytes([12]) + struct.pack(">HH", pool.text(name), pool.text("Lterm;")))
    return pool._add(bytes([9]) + struct.pack(">HH", owner_index, nat))


def _class_of_terms(entries: list[tuple[str, str, list[str]]], this: str = "Demo",
                    classes: tuple[str, ...] = ()) -> bytes:
    """A class whose initializer builds each term and stores it into its named field.

    This is the shape of a `<Type>Constants` class of the distribution: the two spellings are
    pushed, a term is built from them, and the term goes into a static field whose name says
    what the pair stands for. `this` names the class itself, `classes` are the classes its
    code refers to - the way a type class refers to the enumeration it lists.
    """
    pool = _Pool()
    code_name = pool.text("Code")
    for name in classes:
        pool.klass(name)
    body = bytearray()
    for field, owner_and_name, pushed in entries:
        owner, name = owner_and_name.rsplit(".", 1)
        for value in pushed:
            body += bytes([0x13]) + struct.pack(">H", pool.string(value))  # ldc_w
        body += bytes([0xB8]) + struct.pack(">H", pool.method(owner, name))  # invokestatic
        body += bytes([0xB3]) + struct.pack(">H", _field(pool, "Demo", field))  # putstatic
    body += bytes([0xB1])  # return
    code = struct.pack(">HHI", 8, 1, len(body)) + bytes(body) + struct.pack(">HH", 0, 0)
    this_class = pool.klass(this)
    super_class = pool.klass("java/lang/Object")
    method = struct.pack(">HHHH", 0, pool.text("<clinit>"), pool.text("()V"), 1)
    method += struct.pack(">HI", code_name, len(code)) + code
    return (
        b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61)
        + pool.rendered()
        + struct.pack(">HHHH", 0, this_class, super_class, 0)
        + struct.pack(">H", 0)
        + struct.pack(">H", 1) + method
        + struct.pack(">H", 0)
    )


TERM = "demo/utils/Term.term"
NAMESPACE = "demo/utils/NamespaceTerm.create"


def test_a_stored_term_is_read_with_the_field_it_names():
    blob = _class_of_terms([
        ("NS_TERM", NAMESPACE, ["Std::Interface::Favorites", "Стд::Интерфейс::Избранное"]),
        ("USER_FAVORITES_ITEM_TERM", TERM, ["UserFavoritesItem", "ЭлементИзбранногоПользователя"]),
        ("LINK_PROPERTY_TERM", TERM, ["Link", "Ссылка"]),
    ])

    assert classcode.declared_terms(blob) == [
        ("NS_TERM", "Std::Interface::Favorites", "Стд::Интерфейс::Избранное"),
        ("USER_FAVORITES_ITEM_TERM", "UserFavoritesItem", "ЭлементИзбранногоПользователя"),
        ("LINK_PROPERTY_TERM", "Link", "Ссылка"),
    ]


def test_a_term_that_is_never_stored_claims_no_field():
    # The pair is built and passed on: attributing it to the field stored NEXT would put a
    # member's spelling under a neighbour's name.
    blob = _class_of_terms([("PINNED_PROPERTY_TERM", TERM, ["Pinned", "Закреплено"])])
    passed_on = _class_of([(TERM, ["Presentation", "Представление"])])

    assert classcode.declared_terms(blob) == [("PINNED_PROPERTY_TERM", "Pinned", "Закреплено")]
    assert classcode.declared_terms(passed_on) == []


def test_reading_terms_leaves_the_member_pairs_alone():
    # The two readings answer about different calls of the same class - a class that declares
    # members states no terms, and the member reading must not start seeing terms as members.
    blob = _class_of([(BUILDER, ["Write", "Записать"])])

    assert classcode.declared_members(blob) == {"Записать": "Write"}
    assert classcode.declared_terms(blob) == []


# --- what a class constructs and which classes it names --------------------------------------


def _class_constructing(steps: list[tuple[str, ...]], this: str = "Demo") -> bytes:
    """A class whose single method runs `steps` in order: ("new", class) reserves an object of
    the class, ("init", class, descriptor) calls its constructor on what is on the stack. An
    "init" with no "new" of its class before it is the call a subclass makes to its base."""
    pool = _Pool()
    code_name = pool.text("Code")
    body = bytearray()
    for step in steps:
        if step[0] == "new":
            body += bytes([0xBB]) + struct.pack(">H", pool.klass(step[1]))  # new
            body += bytes([0x59])                                            # dup
        else:
            body += bytes([0x2A, 0x01])                                      # aload_0, aconst_null
            body += bytes([0xB7]) + struct.pack(">H", pool.method(step[1], "<init>", step[2]))
    body += bytes([0xB1])  # return
    code = struct.pack(">HHI", 8, 2, len(body)) + bytes(body) + struct.pack(">HH", 0, 0)
    this_class = pool.klass(this)
    super_class = pool.klass("java/lang/Object")
    method = struct.pack(">HHHH", 0, pool.text("build"), pool.text("()V"), 1)
    method += struct.pack(">HI", code_name, len(code)) + code
    return (
        b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61)
        + pool.rendered()
        + struct.pack(">HHHH", 0, this_class, super_class, 0)
        + struct.pack(">H", 0)
        + struct.pack(">H", 1) + method
        + struct.pack(">H", 0)
    )


_MANAGER = "demo/acme/AcmeRightManagerCtMetaObject"
_PROJECT_TYPE = "(Ldemo/acme/AcmeRightG5ProjectType;)V"


def test_a_construction_pairs_the_new_with_the_constructor_it_calls():
    blob = _class_constructing([("new", _MANAGER), ("init", _MANAGER, _PROJECT_TYPE)])

    assert classcode.constructions(blob) == [(_MANAGER, _PROJECT_TYPE)]


def test_a_constructor_called_without_new_constructs_nothing():
    """A subclass runs the constructor of its base on itself: nothing new comes out of it."""
    blob = _class_constructing([("init", _MANAGER, _PROJECT_TYPE)])

    assert classcode.constructions(blob) == []


def test_nested_constructions_are_paired_by_the_class_they_name():
    inner = "demo/acme/Layout"
    blob = _class_constructing([
        ("new", _MANAGER), ("new", inner), ("init", inner, "()V"),
        ("init", _MANAGER, _PROJECT_TYPE),
    ])

    assert classcode.constructions(blob) == [(inner, "()V"), (_MANAGER, _PROJECT_TYPE)]


def test_the_class_names_itself_and_the_classes_it_refers_to():
    blob = _class_of_terms([], this="demo/acme/AcmeRightG5Type",
                           classes=("demo/acme/AcmeRightG5Enum",))

    assert classcode.own_class(blob) == "demo/acme/AcmeRightG5Type"
    assert "demo/acme/AcmeRightG5Enum" in classcode.referenced_classes(blob)
    assert classcode.own_class(b"\xca\xfe") is None


# --- the annotations of a generated EMF package ---------------------------------------------


EMF_OWNER = "demo/model/impl/DemoPackageImpl"
_ANNOTATE = "(Lorg/eclipse/emf/ecore/ENamedElement;Ljava/lang/String;[Ljava/lang/String;)V"
_URI = "demo/emf/URI"


class _InternedPool(_Pool):
    """The pool a compiler writes: one entry per distinct string, in the order of first use."""

    def __init__(self) -> None:
        super().__init__()
        self.interned: dict[str, int] = {}

    def string(self, value: str) -> int:
        if value not in self.interned:
            self.interned[value] = super().string(value)
        return self.interned[value]


def _index(position: int) -> bytes:
    """The instruction that pushes an array index: `iconst_<n>` up to five, `bipush` beyond."""
    return bytes([0x03 + position]) if position <= 5 else bytes([0x10, position])


def _package_of(annotations: list[list], base: str = classcode.EMF_PACKAGE,
                source: str = "", references: bool = False) -> bytes:
    """A package class whose single method adds each annotation, the way EMF generates it.

    An annotation is the list of its details, keys and values in turn; an item is a string the
    code pushes by `ldc`, None for `aconst_null`, or ("static", name) for a value read from a
    static field. `source`, when given, is pushed before the first array, as the first
    annotation of a source pushes it. `references` adds an array of another type after each
    details array, the way an annotation with references is built. The pool is interned: every
    string stands once, where the code first mentions it - the layout that misleads the
    neighbourhood reading.
    """
    pool = _InternedPool()
    code_name = pool.text("Code")
    string_class = pool.klass("java/lang/String")
    uri_class = pool.klass(_URI)
    annotate = pool.method(EMF_OWNER, classcode.ANNOTATION_CALL, _ANNOTATE)
    create_uri = pool.method(_URI, "createURI", "(Ljava/lang/String;)L" + _URI + ";")
    body = bytearray()
    for number, details in enumerate(annotations):
        body += bytes([0x2A, 0x01])                                   # aload_0, aconst_null
        if source and not number:
            body += bytes([0x13]) + struct.pack(">H", pool.string(source))
        body += _index(len(details))
        body += bytes([0xBD]) + struct.pack(">H", string_class)        # anewarray String
        for position, item in enumerate(details):
            body += bytes([0x59]) + _index(position)                  # dup, the index
            if item is None:
                body += bytes([0x01])                                 # aconst_null
            elif isinstance(item, tuple):
                body += bytes([0xB2]) + struct.pack(">H", _field(pool, EMF_OWNER, item[1]))
            else:
                body += bytes([0x13]) + struct.pack(">H", pool.string(item))
            body += bytes([0x53])                                     # aastore
        if references:
            body += _index(1) + bytes([0xBD]) + struct.pack(">H", uri_class)
            body += bytes([0x59]) + _index(0)
            body += bytes([0x13]) + struct.pack(">H", pool.string("demo://model"))
            body += bytes([0xB8]) + struct.pack(">H", create_uri)     # invokestatic
            body += bytes([0x53])
        body += bytes([0xB6]) + struct.pack(">H", annotate)           # invokevirtual
    body += bytes([0xB1])  # return
    code = struct.pack(">HHI", 8, 1, len(body)) + bytes(body) + struct.pack(">HH", 0, 0)
    this_class = pool.klass(EMF_OWNER)
    super_class = pool.klass(base)
    method = struct.pack(">HHHH", 0, pool.text("createAnnotations"), pool.text("()V"), 1)
    method += struct.pack(">HI", code_name, len(code)) + code
    return (
        b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61)
        + pool.rendered()
        + struct.pack(">HHHH", 0, this_class, super_class, 0)
        + struct.pack(">H", 0)
        + struct.pack(">H", 1) + method
        + struct.pack(">H", 0)
    )


#: The standard attributes of an exchange plan node as its package annotates them - the Russian
#: spelling first, as most annotations of the distribution are written.
NODE_ANNOTATIONS = [
    ["ru", "НомерОтправленного", "en", "SentNumber"],
    ["ru", "НомерПринятого", "en", "ReceivedNumber"],
    ["ru", "ЭтотУзел", "en", "ThisNode"],
]


def test_the_details_of_an_annotation_are_read_by_their_keys():
    blob = _package_of(NODE_ANNOTATIONS + [["en", "Attribute", "ru", "Реквизит"]],
                       source="demo://presentation")

    assert classcode.annotation_details(blob) == [
        {"ru": "НомерОтправленного", "en": "SentNumber"},
        {"ru": "НомерПринятого", "en": "ReceivedNumber"},
        {"ru": "ЭтотУзел", "en": "ThisNode"},
        {"en": "Attribute", "ru": "Реквизит"},
    ]


def test_a_value_the_code_does_not_push_as_a_constant_drops_its_key_alone():
    """A null value, or one read from a field, has no constant to read: the key goes with it,
    and the keys after it keep their values."""
    blob = _package_of([
        ["ru", "Файлы", "en", None, "from", "8.0"],
        ["ru", ("static", "NAME_RU"), "en", "Files"],
    ])

    assert classcode.annotation_details(blob) == [
        {"ru": "Файлы", "from": "8.0"},
        {"en": "Files"},
    ]


def test_an_array_of_references_is_not_the_details():
    blob = _package_of([["ru", "Код", "en", "Code"]], references=True)

    assert classcode.annotation_details(blob) == [{"ru": "Код", "en": "Code"}]


def test_the_package_names_the_class_it_extends():
    assert classcode.super_class(_package_of(NODE_ANNOTATIONS)) == classcode.EMF_PACKAGE
    assert classcode.super_class(_class_of([])) == "java/lang/Object"
    assert classcode.super_class(b"\xca\xfe") is None


# --- the string values of annotations --------------------------------------------------------


JSON_ALIAS = "Lcom/fasterxml/jackson/annotation/JsonAlias;"
JSON_PROPERTY = "Lcom/fasterxml/jackson/annotation/JsonProperty;"


def _element(pool: _Pool, value) -> bytes:
    """One element value: a string, a list of strings (an array), an int, or ("@", type) - a
    nested annotation without elements."""
    if isinstance(value, str):
        return b"s" + struct.pack(">H", pool.string_utf8(value))
    if isinstance(value, list):
        return b"[" + struct.pack(">H", len(value)) + b"".join(_element(pool, v) for v in value)
    if isinstance(value, tuple):
        return b"@" + struct.pack(">HH", pool.string_utf8(value[1]), 0)
    return b"I" + struct.pack(">H", 1)


def _annotation(pool: _Pool, kind: str, elements: dict) -> bytes:
    out = struct.pack(">HH", pool.string_utf8(kind), len(elements))
    for name, value in elements.items():
        out += struct.pack(">H", pool.string_utf8(name)) + _element(pool, value)
    return out


class _DataPool(_InternedPool):
    """An interned pool whose element values point at utf8 entries, as annotations do."""

    def string_utf8(self, value: str) -> int:
        key = "utf8:" + value
        if key not in self.interned:
            self.interned[key] = self.text(value)
        return self.interned[key]


def _data_class_of(parameters: list[list[tuple[str, dict]]], this: str = "demo/dto/DemoDto",
                   field_annotations: list[tuple[str, dict]] = ()) -> bytes:
    """A class whose constructor annotates each parameter, the way a JSON data class does.

    A parameter is a list of (annotation type, {element: value}); `field_annotations`, when
    given, annotate a single field. The pool is interned in the order the annotations mention
    the strings - the layout the neighbourhood reads.
    """
    pool = _DataPool()
    body = bytearray([len(parameters)])
    for annotations in parameters:
        body += struct.pack(">H", len(annotations))
        for kind, elements in annotations:
            body += _annotation(pool, kind, elements)
    attribute = struct.pack(">HI", pool.string_utf8("RuntimeVisibleParameterAnnotations"),
                            len(body)) + bytes(body)
    fields = b""
    if field_annotations:
        field_body = struct.pack(">H", len(field_annotations)) + b"".join(
            _annotation(pool, kind, elements) for kind, elements in field_annotations)
        fields = struct.pack(">HHHH", 0, pool.string_utf8("value"), pool.string_utf8("I"), 1)
        fields += struct.pack(">HI", pool.string_utf8("RuntimeVisibleAnnotations"),
                              len(field_body)) + field_body
    method = struct.pack(">HHHH", 0, pool.string_utf8("<init>"), pool.string_utf8("()V"), 1)
    method += attribute
    this_class = pool.klass(this)
    super_class = pool.klass("java/lang/Object")
    return (
        b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61)
        + pool.rendered()
        + struct.pack(">HHHH", 0, this_class, super_class, 0)
        + struct.pack(">H", 1 if field_annotations else 0) + fields
        + struct.pack(">H", 1) + method
        + struct.pack(">H", 0)
    )


#: The properties of a data class of the platform: named in English, aliased in Russian.
DTO_PARAMETERS = [
    [(JSON_ALIAS, {"value": ["Имя"]}), (JSON_PROPERTY, {"value": "Name"})],
    [(JSON_ALIAS, {"value": ["Разработчик"]}), (JSON_PROPERTY, {"value": "Developer"})],
    [(JSON_ALIAS, {"value": ["Поставщик"]}), (JSON_PROPERTY, {"value": "Vendor"})],
]


def test_the_annotations_of_each_parameter_give_their_string_values():
    blob = _data_class_of(DTO_PARAMETERS)

    assert classcode.annotation_values(blob) == [
        {JSON_ALIAS: ["Имя"], JSON_PROPERTY: ["Name"]},
        {JSON_ALIAS: ["Разработчик"], JSON_PROPERTY: ["Developer"]},
        {JSON_ALIAS: ["Поставщик"], JSON_PROPERTY: ["Vendor"]},
    ]


def test_values_of_other_kinds_and_other_elements_are_stepped_over():
    """A number, a nested annotation and an element other than `value` do not stop the reading,
    and an annotated field is read like a parameter."""
    blob = _data_class_of(
        [[("Ldemo/Mark;", {"order": 3, "inner": ("@", "Ldemo/Inner;"), "value": "Name"})]],
        field_annotations=[(JSON_PROPERTY, {"value": "Version"})],
    )

    assert classcode.annotation_values(blob) == [
        {JSON_PROPERTY: ["Version"]},
        {"Ldemo/Mark;": ["Name"]},
    ]
