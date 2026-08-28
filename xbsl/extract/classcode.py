"""Reading what a compiled class DECLARES, not what stands next to what in its constants.

The bilingual pairs of the platform were read by adjacency: a compiled class of the
distribution holds each English name next to its Russian twin, and the reader took every
Cyrillic string together with the identifier beside it. Adjacency is a guess. The pool keeps strings in the
order the code first mentions them, so a name whose twin was already interned ends up beside a
stranger, and the reader then states a pair nobody declared. Measured over the whole
distribution it got 2 of 2015 members wrong, and both were the damaging kind - a CONFIDENT
wrong spelling: the `CharAt` of a `String` came out `Symbol`, which is the fill PARAMETER of
`PadFromBegin` and carries the same Russian name; the `Schedule` of the updating scheduled job
came out `ScheduleWithoutTransaction`. A tree translated with such a pair calls a method the
compiler does not have.

The distribution does not leave the pairs to be guessed: a member is DECLARED by a call that
takes both of its spellings, and the two string constants pushed right before that call are
the pair itself. Reading the calls is what this module does.

Nothing here is specific to the vocabulary - it is a small class-file reader: the constant
pool, the code of every method, and the calls that code makes with string arguments.
"""

from __future__ import annotations

# How many bytes of operand each instruction carries. Only the three opcodes this module reads
# matter by name, but every length has to be right: a walker that mistakes an operand byte for
# an opcode desynchronises and reads garbage from there on.
_OPERAND_BYTES = [0] * 256
for _code, _size in {
    0x10: 1, 0x11: 2, 0x12: 1, 0x13: 2, 0x14: 2,
    0x15: 1, 0x16: 1, 0x17: 1, 0x18: 1, 0x19: 1,
    0x36: 1, 0x37: 1, 0x38: 1, 0x39: 1, 0x3A: 1,
    0x84: 2, 0x99: 2, 0x9A: 2, 0x9B: 2, 0x9C: 2, 0x9D: 2, 0x9E: 2,
    0x9F: 2, 0xA0: 2, 0xA1: 2, 0xA2: 2, 0xA3: 2, 0xA4: 2, 0xA5: 2, 0xA6: 2,
    0xA7: 2, 0xA8: 2, 0xA9: 1,
    0xB2: 2, 0xB3: 2, 0xB4: 2, 0xB5: 2, 0xB6: 2, 0xB7: 2, 0xB8: 2,
    0xB9: 4, 0xBA: 4, 0xBB: 2, 0xBC: 1, 0xBD: 2, 0xC0: 2, 0xC1: 2,
    0xC5: 3, 0xC6: 2, 0xC7: 2, 0xC8: 4, 0xC9: 4,
}.items():
    _OPERAND_BYTES[_code] = _size

_LDC, _LDC_W = 0x12, 0x13
_INVOKE = (0xB6, 0xB7, 0xB8, 0xB9)  # virtual, special, static, interface
_WIDE = 0xC4
_TABLESWITCH, _LOOKUPSWITCH = 0xAA, 0xAB

#: The calls that state the pair of a MEMBER - a method or a property of a type. Parameters
#: and constructors are declared by calls of their own: those carry names too, but not names
#: of members, and mixing them in is exactly what the neighbourhood reading did.
METHOD_FACTORY = "CtMetaMethodBuilder.meth"
PROPERTY_FACTORY = "CtMetaPropBuilder.prop"
MEMBER_FACTORIES = (METHOD_FACTORY, PROPERTY_FACTORY)


def constant_pool(blob: bytes) -> tuple[dict[int, tuple[int, object]], int]:
    """({index: (tag, value)}, the offset just past the pool).

    A long or a double takes TWO pool slots - the standard says the next index is unusable -
    and every index after such a constant shifts by one if that is missed.
    """
    pool: dict[int, tuple[int, object]] = {}
    position = 10
    count = int.from_bytes(blob[8:10], "big")
    index = 1
    while index < count:
        tag = blob[position]
        if tag == 1:  # utf8
            size = int.from_bytes(blob[position + 1:position + 3], "big")
            pool[index] = (1, blob[position + 3:position + 3 + size].decode("utf-8", "replace"))
            position += 3 + size
        elif tag in (7, 8, 16, 19, 20):  # class, string, method type, module, package
            pool[index] = (tag, int.from_bytes(blob[position + 1:position + 3], "big"))
            position += 3
        elif tag == 15:  # method handle
            pool[index] = (tag, None)
            position += 4
        elif tag in (9, 10, 11, 12, 17, 18):  # refs, name-and-type, dynamic
            pool[index] = (tag, (int.from_bytes(blob[position + 1:position + 3], "big"),
                                 int.from_bytes(blob[position + 3:position + 5], "big")))
            position += 5
        elif tag in (5, 6):  # long, double - two slots
            pool[index] = (tag, None)
            position += 9
            index += 1
        else:  # integer, float
            pool[index] = (tag, None)
            position += 5
        index += 1
    return pool, position


def text(pool: dict[int, tuple[int, object]], index: int) -> str | None:
    """The string a pool entry says, following a class or string constant to its utf8."""
    entry = pool.get(index)
    if not entry:
        return None
    if entry[0] == 1:
        return entry[1]  # type: ignore[return-value]
    if entry[0] in (7, 8):
        return text(pool, entry[1])  # type: ignore[arg-type]
    return None


def called_method(pool: dict[int, tuple[int, object]], index: int) -> str | None:
    """'owner/class.name' of a method reference, or None when the entry is not one."""
    entry = pool.get(index)
    if not entry or entry[0] not in (10, 11):  # methodref, interface methodref
        return None
    class_index, name_and_type = entry[1]  # type: ignore[misc]
    described = pool.get(name_and_type)
    if not described or described[0] != 12:
        return None
    return f"{text(pool, class_index)}.{text(pool, described[1][0])}"  # type: ignore[index]


def _method_code(blob: bytes, pool: dict[int, tuple[int, object]], position: int) -> list[bytes]:
    """The bytecode of every method of the class, in declaration order."""

    def attributes(at: int, out: list[bytes]) -> int:
        count = int.from_bytes(blob[at:at + 2], "big")
        at += 2
        for _ in range(count):
            name = text(pool, int.from_bytes(blob[at:at + 2], "big"))
            length = int.from_bytes(blob[at + 2:at + 6], "big")
            body = blob[at + 6:at + 6 + length]
            if name == "Code":
                # max_stack, max_locals, then the code length and the code itself
                size = int.from_bytes(body[4:8], "big")
                out.append(body[8:8 + size])
            at += 6 + length
        return at

    position += 6  # access flags, this class, super class
    position += 2 + int.from_bytes(blob[position:position + 2], "big") * 2  # interfaces
    code: list[bytes] = []
    for _fields_then_methods in range(2):
        count = int.from_bytes(blob[position:position + 2], "big")
        position += 2
        for _member in range(count):
            position += 6  # access flags, name, descriptor
            position = attributes(position, code)
    return code


def builder_calls(blob: bytes) -> list[tuple[str, list[str]]]:
    """[(the called method, the string constants pushed since the previous call)].

    The arguments of a call are whatever the code pushed before it, and a string argument is
    pushed by `ldc`. Everything else on the stack - the owner, the numbers, the type sets - is
    of no interest here, so the walker keeps only the strings and hands them over on the call.
    """
    pool, position = constant_pool(blob)
    calls: list[tuple[str, list[str]]] = []
    for code in _method_code(blob, pool, position):
        pushed: list[str] = []
        at = 0
        while at < len(code):
            opcode = code[at]
            if opcode == _LDC:
                value = text(pool, code[at + 1])
                if value is not None:
                    pushed.append(value)
            elif opcode == _LDC_W:
                value = text(pool, int.from_bytes(code[at + 1:at + 3], "big"))
                if value is not None:
                    pushed.append(value)
            elif opcode in _INVOKE:
                name = called_method(pool, int.from_bytes(code[at + 1:at + 3], "big"))
                if name:
                    calls.append((name, pushed))
                pushed = []
            elif opcode == _WIDE:
                # `wide iinc` carries two operands, every other widened instruction one
                at += 6 if code[at + 1] == 0x84 else 4
                continue
            elif opcode in (_TABLESWITCH, _LOOKUPSWITCH):
                at += 1
                while at % 4:  # the table is aligned on a four-byte boundary
                    at += 1
                if opcode == _TABLESWITCH:
                    low = int.from_bytes(code[at + 4:at + 8], "big", signed=True)
                    high = int.from_bytes(code[at + 8:at + 12], "big", signed=True)
                    at += 12 + (high - low + 1) * 4
                else:
                    at += 8 + int.from_bytes(code[at + 4:at + 8], "big") * 8
                continue
            at += 1 + _OPERAND_BYTES[opcode]
    return calls


def declared_members(blob: bytes) -> dict[str, str]:
    """{Russian member name: its English spelling} as the class DECLARES them.

    The two spellings are the last two strings before the builder call - the builder takes the
    English one first. A call that pushed fewer than two strings states no pair (a member named
    by constants the compiler folded elsewhere), and is skipped rather than guessed at.

    One Russian name may be declared BOTH ways with different English spellings, and the table
    holds one: over the whole distribution that happens twice, both on
    `BinaryObjectProperties` - the method `Temporary` shares its Russian name with the property
    `IsTemporary`, and `PersonalData` with `IsPersonalData`. The method wins, because that is
    the half a fluent API of this shape is written with; the choice is stated here rather than
    left to the order the calls happen to come in.
    """
    by_kind: dict[str, dict[str, str]] = {factory: {} for factory in MEMBER_FACTORIES}
    for name, pushed in builder_calls(blob):
        factory = next((f for f in MEMBER_FACTORIES if name.endswith(f)), None)
        if factory is None or len(pushed) < 2:
            continue
        english, russian = pushed[-2], pushed[-1]
        if english.isascii() and not russian.isascii():
            by_kind[factory][russian] = english
    pairs = dict(by_kind[PROPERTY_FACTORY])
    pairs.update(by_kind[METHOD_FACTORY])
    return pairs
