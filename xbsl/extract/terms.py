#!/usr/bin/env python3
"""Extract the Russian<->English term pairs of 1C:Element from the distribution.

The platform is bilingual: a type is `Запрос` and `Query`, a yaml key is `ОбластьВидимости`
and `VisibilityScope`, an enumeration value is `ВПроекте` and `InProject`. Sources are written
in either language, and so is documentation about them - but the pairing itself is nowhere in
one place, which is why the engine used to carry a few hand-written tuples (and one of them,
"VisibilityArea", matched nothing at all).

Every pair here comes from the distribution, never from a translation:

- types and facets - the documentation page carries the Russian name in <title> and the
  English one in its path segment (`.../Query_ru/index.html`), the same pairing extract_stdlib
  relies on;
- yaml properties - the EMF metamodel annotates them `@PropertyInfo(ru="Имя", en="Name")`;
- enumeration values - the metamodel declares them `InProject as "ВПроекте"`;
- members of every stdlib type - the distribution states them itself. The two
  documentation-and-xcore sources above are thin: a great many names carry no `en` in the
  metamodel at all (`@PropertyInfo(ru="Реквизиты")`), which used to read as "the platform has
  no English name for this" - and that was wrong. Reading what the distribution declares
  yields thousands of pairs the other sources never see (Реквизиты/Attributes,
  ТабличныеЧасти/TabularParts, СоздатьОбъект/CreateObject).

Keywords are NOT duplicated here: language.json already stores every form of each keyword.

The result is xbsl/data/element/<version>/terms.json:
    { "types": {ru: en}, "facets": {ru: en}, "properties": {ru: en}, "enums": {ru: en},
      "members": {en type: {ru: en}}, "common": {ru: en} }

`members` keeps the owner, because a word may be translated differently depending on where it
sits (`Ссылка` is `Reference` on a data-object facet and `Link` on a navigation property);
`common` holds only the names whose English spelling is unambiguous across the distribution.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import struct
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from xbsl.extract import _distro, classcode

STD_BASE = "data/docs/help/ru/stdlib/element/xbsl/Std/"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
# Nested jar plugins that carry the .xcore metamodel (same set as extract_metamodel).
_JAR_RE = re.compile(r"designtime|\.model|mdd|dmf|metamodel", re.I)
_PROP_RE = re.compile(r"@PropertyInfo\d?\(([^)]*)\)")
_RU_RE = re.compile(r"\bru\s*=\s*\"([^\"]+)\"")
_EN_RE = re.compile(r"\ben\s*=\s*\"([^\"]+)\"")
# `InProject as "ВПроекте"` - an enumeration literal with its Russian spelling.
_ENUM_RE = re.compile(r"(\w+)\s+as\s+\"([А-ЯЁ][А-Яа-яЁё0-9_]*)\"")
_NAME_RE = re.compile(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9_]*$")


def _path_name(entry: str) -> str | None:
    """The English name from a `.../<Name>_ru/index.html` documentation path."""
    seg = entry[len(STD_BASE):].split("/")
    if len(seg) < 2:
        return None
    dirname = seg[-2]
    return dirname[:-3] or None if dirname.endswith("_ru") else None


def _add(target: dict[str, str], ru: str, en: str, conflicts: set[str]) -> None:
    """Record a pair; a name that claims two different English spellings is dropped.

    A conflict means the word is used in more than one role (`Ссылка` is a property `Link`
    and a facet `Reference`), and a single mapping would be wrong in one of them.
    """
    if ru == en:
        return
    known = target.get(ru)
    if known is None:
        target[ru] = en
    elif known != en:
        conflicts.add(ru)


#: Classes that describe a type: the file name without this suffix is its English name.
_META_SUFFIX = re.compile(r"(CtMetaObject|MetaObject|BslImpl)$")
#: A class states its members only if it calls one of the builders that take the pair;
#: the test is a substring of the compiled reference, cheap enough to run on every class
#: and far cheaper than walking the bytecode of one that declares nothing.
_DECLARES_MEMBERS_RE = re.compile(rb"CtMeta(Method|Prop)Builder")
#: Jars of the platform itself - the only ones that can hold such classes.
_PLATFORM_JAR_RE = re.compile(r"g5rt|_1c")
_EN_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
#: The Russian side of a pair may be MIXED: the platform spells `HttpService`, `FtpSource`,
#: `SeoDescription` and `AppletTags` with the Latin prefix kept and only the tail in Russian,
#: so such a name STARTS with a Latin letter. What makes it the Russian side is a Cyrillic
#: letter somewhere in it (checked separately), not the first one; demanding a Cyrillic head
#: cost 354 member names their English spelling, every one of this shape. The kind table below
#: always read them this way - the member scan simply never followed.
_RU_NAME_RE = re.compile(r"^[A-Za-zА-ЯЁ][A-Za-zА-Яа-яЁё0-9_]*$")
#: How many times the leading spelling must beat the runner-up to be taken as unambiguous.
_DOMINANCE = 3
#: Names the JVM itself puts in every constant pool. They look exactly like an English name
#: and stand wherever the class file needs them, so a Cyrillic string that happens to follow
#: one used to be "translated" by it - that is how the html document type came out as
#: `BootstrapMethods` and one more name as `Deprecated`. The platform never names anything this
#: way, so the whole set is barred from the English side of a pair.
_CLASS_FILE_NAMES = frozenset({
    "AnnotationDefault", "BootstrapMethods", "Code", "ConstantValue", "Deprecated",
    "EnclosingMethod", "Exceptions", "InnerClasses", "LineNumberTable", "LocalVariableTable",
    "LocalVariableTypeTable", "MethodParameters", "Module", "ModuleMainClass",
    "ModulePackages", "NestHost", "NestMembers", "PermittedSubclasses", "Record",
    "RuntimeInvisibleAnnotations", "RuntimeInvisibleParameterAnnotations",
    "RuntimeInvisibleTypeAnnotations", "RuntimeVisibleAnnotations",
    "RuntimeVisibleParameterAnnotations", "RuntimeVisibleTypeAnnotations", "Signature",
    "SourceDebugExtension", "SourceFile", "StackMapTable", "Synthetic",
})


def _constant_pool(data: bytes) -> list[str]:
    """The UTF8 entries of a class constant pool, in index order.

    Only the strings are needed, so the other entry kinds are skipped by their fixed sizes
    (long and double take two pool slots - the quirk the `num += 1` accounts for).
    """
    count = struct.unpack_from(">H", data, 8)[0]
    out: dict[int, str] = {}
    i, num = 10, 1
    while num < count and i < len(data):
        tag = data[i]
        if tag == 1:
            length = struct.unpack_from(">H", data, i + 1)[0]
            out[num] = data[i + 3:i + 3 + length].decode("utf-8", "replace")
            i += 3 + length
        elif tag in (7, 8, 16, 19, 20):
            i += 3
        elif tag == 15:
            i += 4
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            i += 5
        elif tag in (5, 6):
            i += 9
            num += 1
        else:
            i += 1
        num += 1
    return [out[key] for key in sorted(out)]


def _scan_meta_objects(car: zipfile.ZipFile) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """({owner type: {ru: en}}, {ru: en}) from the compiled classes of the distribution.

    A class without a single Cyrillic byte cannot hold a pair and is skipped before parsing -
    that check alone drops the overwhelming majority of the classes.
    """
    members: dict[str, dict[str, str]] = defaultdict(dict)
    variants: dict[str, Counter] = defaultdict(Counter)
    for entry in car.namelist():
        if not entry.endswith(".jar") or not _PLATFORM_JAR_RE.search(entry):
            continue
        try:
            jar = zipfile.ZipFile(io.BytesIO(car.read(entry)))
        except (zipfile.BadZipFile, KeyError):
            continue
        for inner in jar.namelist():
            if not inner.endswith(".class"):
                continue
            try:
                data = jar.read(inner)
            except (zipfile.BadZipFile, KeyError):
                continue
            if b"\xd0" not in data and b"\xd1" not in data:
                continue
            strings = _constant_pool(data)
            pairs = [
                (en, ru) for en, ru in zip(strings, strings[1:])
                if _EN_NAME_RE.match(en) and en not in _CLASS_FILE_NAMES
                and _RU_NAME_RE.match(ru) and _CYRILLIC_RE.search(ru)
            ]
            if inner == _QUERY_TERMS_CLASS:
                # In the query parser's own class a keyword the platform has NO English
                # spelling for is followed by a transliteration of itself, and adjacency reads
                # that as the next keyword's English. The function names of the same class are
                # paired correctly, so only the keywords named here are dropped.
                names = [
                    s for s in strings if _QUERY_EN_RE.match(s) or _QUERY_RU_RE.match(s)
                ]
                without = _query_untranslated(names)
                pairs = [(en, ru) for en, ru in pairs if ru not in without]
            if not pairs:
                continue
            owner = _META_SUFFIX.sub("", inner.rsplit("/", 1)[-1][:-len(".class")])
            # A class STATES its members, and a statement beats the neighbourhood: adjacency
            # named 2 of 2015 members wrongly, both confidently - the `CharAt` of a `String`
            # came out `Symbol`, which is the fill PARAMETER of `PadFromBegin`. Read only
            # where such declarations are actually made.
            declared = classcode.declared_members(data) if _DECLARES_MEMBERS_RE.search(data) else {}
            resolved = {ru: en for en, ru in pairs}
            resolved.update(declared)
            for ru, en in resolved.items():
                members[owner][ru] = en
                variants[ru][en] += 1
    common: dict[str, str] = {}
    for ru, counter in variants.items():
        ranked = counter.most_common(2)
        best, best_n = ranked[0]
        if len(ranked) == 1 or best_n >= ranked[1][1] * _DOMINANCE:
            common[ru] = best
    return {owner: dict(sorted(names.items())) for owner, names in sorted(members.items())}, common


#: The serializer's own element-kind enum: what an English project writes into ElementKind.
_KIND_ENUM_CLASS = "ProjectElementKindCmptEnum.class"
#: A kind name is Russian or MIXED (`HttpСервис`) - at least one Cyrillic letter tells it
#: from the English neighbour in the constant pool.
_KIND_RU_RE = re.compile(r"^[A-Za-zА-ЯЁ][0-9A-Za-zА-Яа-яЁё]*$")
_KIND_EN_RE = re.compile(r"^[A-Z][0-9A-Za-z]*$")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def scan_kind_table(car: zipfile.ZipFile) -> dict[str, str]:
    """{Russian element kind: English spelling} from the serializer's kind enum, or empty.

    The type dictionary spells the STDLIB TYPE (`Перечисление` -> `Enum`), while the yaml
    of an English project carries the KIND enum's spelling (`ElementKind: Enumeration`) -
    mapping kinds through the dictionary lost such objects from every by-kind view. The
    enum class pairs the spellings the same way the type classes do: the English constant
    right before the Russian one.
    """
    for entry in car.namelist():
        if not entry.endswith(".jar") or not _PLATFORM_JAR_RE.search(entry):
            continue
        try:
            jar = zipfile.ZipFile(io.BytesIO(car.read(entry)))
        except (zipfile.BadZipFile, KeyError):
            continue
        for inner in jar.namelist():
            if not inner.endswith("/" + _KIND_ENUM_CLASS):
                continue
            strings = _constant_pool(jar.read(inner))
            return {
                ru: en for en, ru in zip(strings, strings[1:])
                if _KIND_EN_RE.match(en) and _KIND_RU_RE.match(ru) and _CYRILLIC_RE.search(ru)
            }
    return {}


#: The query language is a separate grammar (TreeSQL); its keyword pairs live in one class.
_QUERY_TERMS_CLASS = "com/e1c/g5/treesql/domain/QueryTerms.class"
_QUERY_JAR_RE = re.compile(r"treesql\.model")
_QUERY_EN_RE = re.compile(r"^[A-Z][A-Z0-9_ ]*$")
_QUERY_RU_RE = re.compile(r"^[А-ЯЁ][А-ЯЁ0-9_ ]*$")


def _scan_query_terms(car: zipfile.ZipFile) -> dict[str, str]:
    """{Russian keyword: English keyword} of the query language, empty when not found.

    The XBSL grammar does not describe queries at all - `Запрос{...}` is a nested language
    with its own parser (TreeSQL), and its vocabulary is nowhere in the documentation either.
    The one place that pairs the spellings is the QueryTerms class of the parser's model, and
    there the English name lies right before the Russian one, exactly as in the type classes.
    """
    for entry in car.namelist():
        if not entry.endswith(".jar") or not _QUERY_JAR_RE.search(entry):
            continue
        try:
            jar = zipfile.ZipFile(io.BytesIO(car.read(entry)))
            data = jar.read(_QUERY_TERMS_CLASS)
        except (zipfile.BadZipFile, KeyError):
            continue
        # Service entries of the pool (method descriptors, class names) sit between a pair
        # and would break the adjacency: `FROM`, the descriptor, then `ИЗ`.
        names = [
            s for s in _constant_pool(data)
            if _QUERY_EN_RE.match(s) or _QUERY_RU_RE.match(s)
        ]
        return _query_pairs(names)
    return {}


def _query_pairs(names: list[str]) -> dict[str, str]:
    """{Russian keyword: English keyword} out of the filtered constant pool.

    Read pair by pair rather than by every adjacency, because the pool holds three shapes and
    only the first is a translation:

    * an English keyword followed by its Russian spelling - a keyword that has both;
    * the same, followed by the ENUM CONSTANT of that pair (`CREATE INDEX` is followed by its
      Russian spelling and then by `CREATE_INDEX`, the English with underscores);
    * a Russian keyword followed by a TRANSLITERATION of itself - the platform has no English
      spelling for that word at all, and what stands next to it is its constant name.

    Taken by adjacency alone, the constant of one entry became the "English" of the next, and
    the dictionary claimed `ОТ` answers `OTLICHAYETSYA` and `ДЛЯ` answers `CREATE_INDEX` - both
    were skipped by hand on the translating side until this read them correctly.
    """
    return _query_scan(names)[0]


def _query_untranslated(names: list[str]) -> set[str]:
    """The query keywords the platform has NO English spelling for (see _query_pairs)."""
    return _query_scan(names)[1]


def _query_scan(names: list[str]) -> tuple[dict[str, str], set[str]]:
    """One pass over the filtered pool: the pairs it holds and the keywords without a pair."""
    pairs: dict[str, str] = {}
    without: set[str] = set()
    previous_english: str | None = None
    index = 0
    while index < len(names) - 1:
        current, following = names[index], names[index + 1]
        english, russian = _QUERY_EN_RE.match(current), _QUERY_RU_RE.match(current)
        if english and previous_english and current == previous_english.replace(" ", "_"):
            index += 1  # the enum constant of the pair just read
            continue
        if english and _QUERY_RU_RE.match(following):
            pairs[following] = current
            previous_english = current
            index += 2
            continue
        if russian and _QUERY_EN_RE.match(following):
            # No English spelling: the platform transliterated the keyword into a constant.
            without.add(current)
            previous_english = None
            index += 2
            continue
        index += 1
    return pairs, without


def extract(dist: Path) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    car = _distro.find_car(dist)
    types: dict[str, str] = {}
    facets: dict[str, str] = {}
    properties: dict[str, str] = {}
    enums: dict[str, str] = {}
    conflicts: dict[str, set[str]] = {k: set() for k in ("types", "facets", "properties", "enums")}

    def scan_xcore(text: str) -> None:
        for match in _PROP_RE.finditer(text):
            body = match.group(1)
            ru, en = _RU_RE.search(body), _EN_RE.search(body)
            if ru and en and _NAME_RE.match(ru.group(1)) and _NAME_RE.match(en.group(1)):
                _add(properties, ru.group(1), en.group(1), conflicts["properties"])
        for match in _ENUM_RE.finditer(text):
            _add(enums, match.group(2), match.group(1), conflicts["enums"])

    with zipfile.ZipFile(car) as z:
        for entry in z.namelist():
            if entry.startswith(STD_BASE) and entry.endswith("/index.html"):
                english = _path_name(entry)
                if not english:
                    continue
                title_match = _TITLE_RE.search(z.read(entry).decode("utf-8", "replace"))
                if not title_match:
                    continue
                russian = title_match.group(1).split("|")[0].strip()
                if not russian or russian.startswith("1С:"):
                    continue
                if "." in english and english.count(".") == 1 and "." in russian:
                    _add(facets, russian, english, conflicts["facets"])
                elif "." not in english and _NAME_RE.match(russian):
                    _add(types, russian, english, conflicts["types"])
            elif entry.endswith(".xcore"):
                scan_xcore(z.read(entry).decode("utf-8", "replace"))
            elif entry.endswith(".jar") and _JAR_RE.search(entry):
                try:
                    with zipfile.ZipFile(io.BytesIO(z.read(entry))) as jar:
                        for inner in jar.namelist():
                            if inner.endswith(".xcore"):
                                scan_xcore(jar.read(inner).decode("utf-8", "replace"))
                except zipfile.BadZipFile:
                    continue

    with zipfile.ZipFile(car) as z:
        members, common = _scan_meta_objects(z)
        query = _scan_query_terms(z)
        kind_table = scan_kind_table(z)

    for section, names in conflicts.items():
        target = {"types": types, "facets": facets, "properties": properties, "enums": enums}[section]
        for name in names:
            target.pop(name, None)
    return {
        "types": types, "facets": facets, "properties": properties, "enums": enums,
        "members": members, "common": common, "query": query, "kinds": kind_table,
    }, conflicts


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        prog=_distro.prog_name("python -m xbsl.extract.terms"), description=__doc__.splitlines()[0]
    )
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--element-version", help="версия данных (по умолчанию определяется по дистрибутиву)")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)

    dist = Path(args.dist)
    version = _distro.detect_version(dist, args.element_version)
    _distro.set_data_root(args.data_dir)
    sections, conflicts = extract(dist)

    meta = {
        "element_version": version,
        "source": "docs/help/ru (title + путь страницы), *.xcore (@PropertyInfo, значения "
                  "перечислений), метаобъекты компилятора в jar дистрибутива",
        "note": "пары русского и английского написания; имена с несколькими ролями "
                "(разное английское написание в разных местах) исключены",
    }
    # Компактный файл читает рантайм на каждом прогоне - в нём только то, чем пользуются
    # правила. Полный словарь (тысячи членов) лежит рядом и грузится по требованию:
    # 1 МБ json в каждом параллельном воркере стоил бы четверти времени прогона.
    small = {"meta": meta, **{name: dict(sorted(sections[name].items()))
                              for name in ("types", "facets", "properties", "enums", "query",
                                           "kinds")}}
    full = {"meta": meta, "members": sections["members"], "common": sections["common"]}

    version_dir = _distro.version_dir(version)
    version_dir.mkdir(parents=True, exist_ok=True)
    out = version_dir / "terms.json"
    out.write_text(json.dumps(small, ensure_ascii=False, indent=1), encoding="utf-8")
    out_full = version_dir / "terms_full.json"
    out_full.write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    _distro.update_index(version)

    print(f"Записано: {out} (версия {version})")
    for name in ("types", "facets", "properties", "enums"):
        dropped = sorted(conflicts[name])
        extra = f", исключено по конфликту: {dropped}" if dropped else ""
        print(f"  {name}: {len(sections[name])}{extra}")
    print(f"  query: {len(sections['query'])} ключевых слов языка запросов")
    print(f"  kinds: {len(sections['kinds'])} видов элементов (написания сериализатора)")
    print(f"Записано: {out_full}")
    print(f"  members: {len(sections['members'])} типов, common: {len(sections['common'])} имён")


if __name__ == "__main__":
    main()
