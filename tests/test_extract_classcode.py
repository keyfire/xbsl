"""Member pairs read from the DECLARATIONS of a meta object (xbsl/extract/classcode.py).

The class here is assembled by the test, byte for byte, in the shape the platform's own meta
objects have: a method whose code pushes the two spellings and calls the builder that takes
them. No Element data is needed, and no vendor class is carried in the repository - what is
reproduced is the layout of the class file, which is a public standard.

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


BUILDER = "com/e1c/g5rt/xbsl/mogen/rtlib/CtMetaMethodBuilder.meth"
PROPERTY = "com/e1c/g5rt/xbsl/mogen/rtlib/CtMetaPropBuilder.prop"
PARAMETER = "com/e1c/g5rt/xbsl/mogen/rtlib/CtMetaMethodBuilder.p"


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
