"""Resources addressed by `Ресурс{...}`: the shape of the key and its existence.

Three rules live here:

- code/resource-bare-name (tier C, file) - the key spells out the Resources folder itself;
- code/unknown-resource (tier D, project) - the key resolves to nothing;
- code/package-resources-missing (tier D, project) - `ПакетРесурсов.Текущий()` in a module of
  a package or at the root of a subsystem that keeps no resources of its own (see the docstring
  of the rule).

THE KEY IS A PATH RELATIVE TO A SUBSYSTEM'S `Ресурсы` FOLDER. Probed on the local server,
every form next to the same controls (positions match the compiler's - the first character
inside the braces):

    Ресурс{Проба.svg}                  file at Ресурсы/Проба.svg               applies
    Ресурс{Подкаталог/Вложенная.svg}   file at Ресурсы/Подкаталог/Вложенная.svg applies
    Ресурс{Вложенная.svg}              the same file by its bare name           fails
    Ресурс{НетТакого/Вложенная.svg}    no such subfolder                        fails
    Ресурс{Ресурсы/Проба.svg}          the Ресурсы root spelled out             fails

So subfolders are legal and resolved literally, a bare name reaches only the folder root,
and the ONE provably broken spelling is a key whose first segment is `Ресурсы` - a path
from the subsystem root instead of relative to Ресурсы (it is looked up under
Ресурсы/Ресурсы/...). That single spelling is what code/resource-bare-name reports; the fix
strips the leading segment. An earlier revision read the `Ресурсы/Проба.svg` failure as
"folders are rejected" and told the user to keep the bare name - the subfolder probe
overturned that: for a file inside a subfolder the bare name is exactly what does NOT
compile.

The `inbase/` prefix is NOT a folder: it addresses a resource uploaded into the application
base (the web editor names them by uuid - `Ресурс{inbase/<uuid>.png}` in deployed code).
Probed on the local server next to the same controls: a DANGLING uuid fails with the very
message a missing bare name gets ('Неизвестный ресурс: inbase/...') - a lookup that found
nothing, not a rejected spelling - while the deployed code whose uuid exists in ITS base
applies cleanly. Both rules leave the form alone: the spelling is legal, and whether the
uuid exists is a fact of the application base no static check can see - the compiler
verifies it at apply.

The code/unknown-resource rule. A key that resolves to nothing is rejected at apply
('Неизвестный ресурс' on every failing probe line above), but "exists" means more than
"lies in the project": the platform ships an image library of its own, and code may use it
without any file in the project. That is what would make a project-only check false: names
like Настройки.svg, Время.svg, Скачать.svg, Ссылка2.svg or ГалочкаВКруге.svg resolve to the
library, and such a check would call every one of them
errors. The probe settled it: `Ресурс{Настройки.svg}` compiles in a project with no such
file, while `Ресурс{Настройки3.svg}` right next to it fails.

Project resources keep their namespace instead of collapsing into one known set. For a bare
key the runtime gives every namespace of the current subsystem priority 0 (the root and all
packages), another namespace of the project priority 5, another project priority 10 and `Std`
priority 20. Only namespaces at the best available priority participate: a local resource wins
over an imported namesake, while two local packages holding the key make it ambiguous. Imported
resources then obey the visibility of their resources descriptor. Without a descriptor the
runtime default is global before compatibility mode 8.0 and subsystem-only from 8.0 onward.

The platform image library is the last fallback. The documentation page
`topics/image-library` lists it in Russian - the first source of truth, not a hand-written list.
The same pictures also have English names: the
platform's own sources write `Resource{Std::...}` and bare English names, and the translator
writes them too. Those names come from the pairs the extractor matched by their bytes
(`uiterms.resource_paths`). With the Russian names alone the rule reported such references
in a translated project as errors, though the build accepts them. Data extracted before that
table has no English names, and there the rule still reports them. A qualified key
(`Стд::Грузовик.svg`, the form the docs show) is stripped of its namespace before the lookup.
Without the documentation data the rule stays silent: guessing without the library is exactly
what produces false positives.
A Ресурсы-prefixed key is left to code/resource-bare-name, so one mistake is not reported
twice; a backslash spelling is unproven and skipped rather than judged.

The rule reports the three failure results the shipped resolver distinguishes: unknown,
ambiguous at the winning priority and hidden by visibility. A fully qualified resource in
another loaded project is left alone because subsystem usage across projects is not part of the
facts this rule collects. Keys are matched exactly: the platform's lookup is case-sensitive
while a Windows checkout is not.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, docs, i18n, resources as resource_model, terms
from xbsl.dataset import DatasetError
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import Token
from xbsl.restext import RESOURCE_DIRS
from xbsl.rules._syntax import code_tokens
from xbsl.rules.yaml_imports import _layout_fact, _layout_from, _module_imports
from xbsl.rules.yaml_schema import _HAVE_YAML

MESSAGES = {
    "code/resource-bare-name.title": {
        "ru": "Ключ ресурса включает каталог Ресурсы",
        "en": "The resource key spells out the {n[Ресурсы]} folder",
    },
    "code/unknown-resource.title": {
        "ru": "Неизвестный ресурс",
        "en": "Unknown resource",
    },
    "code/unknown-resource.unknown": {
        "ru": "Неизвестный ресурс '{name}' – его нет ни в каталогах 'Ресурсы' проекта, ни в "
              "библиотеке картинок платформы; применение сборки упадёт 'Неизвестный ресурс'.",
        "en": "Unknown resource '{name}' – neither in the project's '{n[Ресурсы]}' folders nor in "
              "the platform's image library; applying the build will fail with 'Неизвестный "
              "ресурс'.",
    },
    "code/unknown-resource.ambiguous": {
        "ru": "Неоднозначный ресурс '{name}' – его одновременно дают пространства имен: {owners}.",
        "en": "Ambiguous resource '{name}' – it is provided by these namespaces at the same "
              "priority: {owners}.",
    },
    "code/unknown-resource.hidden": {
        "ru": "Ресурс '{name}' принадлежит пространству имен '{owner}' и не виден из-за "
              "области видимости каталога ресурсов.",
        "en": "Resource '{name}' belongs to namespace '{owner}' and is hidden by the resources "
              "folder's visibility scope.",
    },
    "code/resource-bare-name.path": {
        "ru": "Ключ ресурса задаётся ОТНОСИТЕЛЬНО каталога {n[Ресурсы]}: '{name}' начинается с "
              "самого каталога, платформа ищет такой путь внутри {n[Ресурсы]} и применение сборки "
              "падает 'Неизвестный ресурс'. Правильно: '{n[Ресурс]}{{{base}}}'.",
        "en": "A resource key is a path RELATIVE to the {n[Ресурсы]} folder: '{name}' starts with "
              "that folder itself, the platform looks the path up inside {n[Ресурсы]} and applying "
              "the build fails with 'Неизвестный ресурс'. Correct: '{n[Ресурс]}{{{base}}}'.",
    },
    "code/package-resources-missing.title": {
        "ru": "Текущий пакет ресурсов в пакете без ресурсов",
        "en": "The current resources package in a package without resources",
    },
    "code/package-resources-missing.empty": {
        "ru": "{n[ПакетРесурсов]}.{n[Текущий]}() в модуле пакета '{package}' отдаёт ресурсы самого "
              "пакета, а своего каталога {n[Ресурсы]} у пакета нет: ни один файл не найдётся "
              "({n[ИсключениеРесурсНеНайден]}), и файлы из каталога {n[Ресурсы]} подсистемы тоже. "
              "Модуль, который читает ресурсы по вычисленному имени, держат в корне подсистемы. "
              "Другие выходы – положить ресурсы в каталог пакета или обратиться к файлу "
              "литералом {n[Ресурс]}{{...}}: литерал файлы подсистемы находит.",
        "en": "{n[ПакетРесурсов]}.{n[Текущий]}() in a module of package '{package}' returns the "
              "resources of the package itself, and the package has no {n[Ресурсы]} folder of its "
              "own: no file is found ({n[ИсключениеРесурсНеНайден]}), the files of the "
              "{n[Ресурсы]} folder of the subsystem included. A module that reads resources by a "
              "computed name belongs at the root of the subsystem. The other ways out are to put "
              "the resources into the folder of the package or to address the file with a "
              "{n[Ресурс]}{{...}} literal, which does find the files of the subsystem.",
    },
    "code/package-resources-missing.root": {
        "ru": "{n[ПакетРесурсов]}.{n[Текущий]}() в модуле корня подсистемы '{package}' отдаёт "
              "ресурсы самой подсистемы, а своего каталога {n[Ресурсы]} у неё нет: ни один файл "
              "не найдётся ({n[ИсключениеРесурсНеНайден]}) – ни файл её пакетов, ни файл другой "
              "подсистемы, и даже {n[ПолучитьВсе]}() бросает это исключение. Положите файлы в "
              "каталог {n[Ресурсы]} подсистемы или держите модуль, который читает ресурсы по "
              "вычисленному имени, в пакете с этими файлами.",
        "en": "{n[ПакетРесурсов]}.{n[Текущий]}() in a module at the root of subsystem '{package}' "
              "returns the resources of the subsystem itself, and the subsystem has no "
              "{n[Ресурсы]} folder of its own: no file is found ({n[ИсключениеРесурсНеНайден]}) - "
              "neither a file of its packages nor one of another subsystem, and even "
              "{n[ПолучитьВсе]}() throws that exception. Put the files into the {n[Ресурсы]} "
              "folder of the subsystem, or keep the module that reads resources by a computed "
              "name in the package that holds them.",
    },
}
i18n.register(MESSAGES)

#: The folder holding the resource files of a subsystem - BOTH spellings. The platform
#: accepts the English name as readily as the Russian one: probed on the local server with
#: the same form three times - a file under `Resources` resolves (`ok`), the same reference
#: with the file missing fails with "Неизвестный ресурс", and the same file moved into a
#: folder of any other name fails the same way. So the name matters and English is legal;
#: knowing only the Russian one made an English project look as if it had no resources.
#: The pair lives in the engine, which collects the same folders for the typography rules.
_RESOURCE_DIRS = RESOURCE_DIRS

#: The prefix of a resource uploaded into the application base (see the module docstring).
_UPLOADED_PREFIX = "inbase/"


@lru_cache(maxsize=1)
def _resource_words() -> frozenset[str]:
    """Both spellings of the resource literal itself - the platform's own pair, not a guess.

    The literal is written `Ресурс{...}` in a Russian project and `Resource{...}` in a
    translated one; knowing only the Russian word left both rules of this module silent on an
    English tree - found by a parity seed, which the Russian side reported and the English one
    did not.
    """
    return frozenset(terms.key_forms("Ресурс"))


def _resource_refs(toks: list[Token], text: str) -> Iterable[tuple[str, int, int]]:
    """(name inside the braces, line, column) for every `Ресурс{...}` of the module.

    Comments and string literals are already stripped by code_tokens, so a `Ресурс{}`
    mentioned in a comment cannot false-match. The name is taken from the source text
    between the braces, not glued back from tokens: a name may hold characters the lexer
    splits (`adv-auto.svg`) or spaces it drops.
    """
    words = _resource_words()
    for i, t in enumerate(toks):
        if t.kind != "IDENT" or t.value not in words or i + 1 >= len(toks):
            continue
        opener = toks[i + 1]
        if opener.kind != "OP" or opener.value != "{":
            continue
        for closer in toks[i + 2:]:
            if closer.kind == "OP" and closer.value == "}":
                name = text[opener.end:closer.start].strip()
                if name:
                    yield name, opener.end_line, opener.end_col
                break
            if closer.line != opener.line:
                break  # an unclosed brace - leave it to the parser


@rule("code/resource-bare-name", "code/resource-bare-name.title", "C", severity=Severity.ERROR)
def resource_bare_name(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl" or not any(w + "{" in source.text for w in _resource_words()):
        return
    for name, line, col in _resource_refs(code_tokens(source), source.text):
        # Subfolder keys are legal (resolved relative to Ресурсы, see the module
        # docstring); the one provably broken spelling is the Ресурсы root itself
        # as the first segment - the path from the subsystem root.
        first, _sep, rest = name.replace("\\", "/").partition("/")
        if first not in _RESOURCE_DIRS or not rest:
            continue
        yield Diagnostic(
            source.rel, line, col, "code/resource-bare-name", Severity.ERROR,
            i18n.t("code/resource-bare-name.path", name=name, base=rest),
        )


#: The documentation page listing the platform's image library.
_IMAGE_LIBRARY_PAGE = "topics/image-library"
#: A resource file name as the page spells it.
_IMAGE_NAME_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]+\.svg")


@lru_cache(maxsize=1)
def _platform_images() -> frozenset[str]:
    """Keys of the image library in both spellings, or an empty set without the docs data.

    The documentation page gives the Russian names and the table of pairs adds the English
    ones. The table alone does not make a library: without the page nothing is known.
    """
    page = docs.page(_IMAGE_LIBRARY_PAGE)
    if not page:
        return frozenset()
    return frozenset(_IMAGE_NAME_RE.findall(page.get("html") or "")) | _english_library_keys()


dataset.register_reset(_platform_images.cache_clear)


def _english_library_keys() -> frozenset[str]:
    """English keys of the library's pictures from `uiterms.resource_paths`, or an empty set.

    A row pairs a picture by its place in the jar (`Icons/Стд/Ресурсы/Аккаунт.svg` ->
    `Icons/Std/Resources/Account.svg`), while a reference names the picture relative to the
    resources folder. So the key is what follows `Icons/<namespace>/<resources folder>/`,
    including a folder of the library below it. A row that does not lie below a resources
    folder gives no key.
    """
    try:
        table = (dataset.load_json("uiterms.json") or {}).get("resource_paths") or {}
    except DatasetError:
        return frozenset()
    keys: set[str] = set()
    for english in table.values() if isinstance(table, dict) else ():
        parts = english.split("/") if isinstance(english, str) else []
        if len(parts) >= 4 and all(parts) and parts[2] in _RESOURCE_DIRS:
            keys.add("/".join(parts[3:]))
    return frozenset(keys)


def _unknown_resource_mapper(source: SourceFile) -> dict | None:
    """The map phase: descriptors contribute layout, modules their refs and imports."""
    if source.kind == "yaml":
        return _layout_fact(source)
    if source.kind != "xbsl" or not any(w + "{" in source.text for w in _resource_words()):
        return None
    toks = code_tokens(source)
    refs = list(_resource_refs(toks, source.text))
    if not refs:
        return None
    return {
        "k": "refs",
        "path": str(source.path),
        "refs": refs,
        "imports": [name for name, _line, _col in _module_imports(toks)],
    }


@rule(
    "code/unknown-resource", "code/unknown-resource.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_unknown_resource_mapper,
)
def unknown_resource(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    library = _platform_images()
    if not library:
        return  # no documentation data - the library is unknown, guessing would be wrong
    layout = _layout_from(facts)
    if not layout.projects:
        return  # no Проект.yaml in the run - nothing to compare against
    scopes = tuple(
        scope for root in layout.projects
        for scope in resource_model.resource_scopes(root, layout)
    )
    for rel, fact in facts.items():
        if fact.get("k") != "refs":
            continue
        path = Path(fact["path"])
        place = layout.place(path)
        project = layout.project_dir_of(path)
        imports = {layout.local_name(name, project) for name in fact.get("imports", ())}
        project_scopes = tuple(scope for scope in scopes if scope.place.project_dir == project)
        namespaces = {scope.place.key for scope in project_scopes}
        for name, line, col in fact.get("refs", ()):
            if name.startswith(_UPLOADED_PREFIX):
                continue  # uploaded into the base - existence is a base fact
            if "\\" in name:
                continue  # a backslash spelling is unproven - skipped, not judged
            qualifier, separator, tail = name.rpartition("::")
            key = tail.strip()
            if key.partition("/")[0] in _RESOURCE_DIRS:
                continue  # the Ресурсы-prefixed spelling - resource-bare-name reports it
            if key in library and separator and qualifier in {"Стд", "Std"}:
                continue
            target = None
            if separator:
                target = layout.resolve(qualifier.strip().split("::"), project, namespaces)
                if target is None:
                    external = [
                        scope for scope in scopes if key in scope.keys
                        and (identity := layout.identity(scope.place.project_dir)) is not None
                        and qualifier == f"{identity[0]}::{identity[1]}::{scope.place.key}"
                    ]
                    if external:
                        continue  # cross-project namespace usage is not part of these facts
                    resolution = resource_model.ResourceResolution("unknown")
                elif (place is not None and target.split("::", 1)[0] != place.subsystem
                      and target not in imports):
                    continue  # subsystem usage is not part of this rule's facts
            candidates = [
                resource_model.ResourceCandidate(
                    scope.place.key,
                    place is not None and scope.place.subsystem == place.subsystem,
                    scope.public,
                    str(scope.directory),
                )
                for scope in project_scopes if key in scope.keys
                and (target is None or scope.place.key == target)
            ]
            if not separator or target is not None:
                resolution = resource_model.resolve_resource(
                    candidates, imports, target,
                )
            if resolution.kind == "resolved":
                continue
            if resolution.kind == "unproven":
                continue
            if resolution.kind == "unknown" and not separator and key in library:
                continue
            owners = sorted({candidate.namespace for candidate in resolution.candidates})
            message_key = resolution.kind if resolution.kind in {"ambiguous", "hidden"} else "unknown"
            message_args = {"name": name}
            if message_key == "ambiguous":
                message_args["owners"] = ", ".join(owners)
            elif message_key == "hidden":
                message_args["owner"] = owners[0]
            yield Diagnostic(
                rel, line, col, "code/unknown-resource", Severity.ERROR,
                i18n.t(f"code/unknown-resource.{message_key}", **message_args),
                data={"resolution": message_key, "namespaces": owners},
            )


# --- code/package-resources-missing -------------------------------------------------------


@lru_cache(maxsize=1)
def _current_package_words() -> tuple[frozenset[str], frozenset[str]]:
    """Both spellings of the type `ResourcesPackage` and of its static method `Current`."""
    return (frozenset(terms.forms("ПакетРесурсов", "types")),
            frozenset({"Текущий", terms.member_english_of("ПакетРесурсов", "Текущий")} - {None}))


dataset.register_reset(_current_package_words.cache_clear)


def _current_package_mapper(source: SourceFile) -> dict | None:
    """The map phase: a descriptor contributes its place in the layout, a module the positions
    of its `ПакетРесурсов.Текущий()` calls."""
    if source.kind == "yaml":
        return _layout_fact(source) if _HAVE_YAML else None
    if source.kind != "xbsl" or is_query_file(source.path):
        return None
    types, members = _current_package_words()
    if not any(word in source.text for word in types):
        return None
    try:
        toks = code_tokens(source)
    except DatasetError:
        return None  # no language data - the module cannot be tokenized
    calls = [
        (tok.line, tok.col) for i, tok in enumerate(toks[:-3])
        if tok.kind == "IDENT" and tok.value in types
        and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
        and toks[i + 2].kind == "IDENT" and toks[i + 2].value in members
        and toks[i + 3].kind == "OP" and toks[i + 3].value == "("
    ]
    return {"k": "cur", "path": str(source.path), "calls": calls} if calls else None


@rule(
    "code/package-resources-missing", "code/package-resources-missing.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_current_package_mapper,
)
def package_resources_missing(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`ResourcesPackage.Current()` in a module of a package or at the root of a subsystem that
    has no resources folder.

    The documentation ties the resources to the namespace: every subsystem and every package
    may keep a set of its own (the page on resources), and `Current()` returns the package
    "associated with the current namespace" (the page of `ResourcesPackage`) - for a module of a
    package that is the package, not its subsystem. The live case showed the consequence: a
    module that read icons by a computed name was moved from the root of a subsystem into a
    package without a resources folder, `Get` found nothing, and a fresh seeding left seven
    records of seven without their icons, with no error anywhere; the same module back at the
    root found all seven. A `Resource{...}` literal in the module of a package does find a file
    of the subsystem, and the compiler checks it - only the lookup by a computed name is left to
    run time. A package of a shipped library reads its own folder the same way: the module of
    the package and the folder of icons it reads lie in the package, not in the subsystem.

    The root of a subsystem is judged the same way. The documentation leaves it open - one of
    its examples hands `Get` a path that starts at the folder of the subsystem, as if the lookup
    reached the whole project - so the question was put to a run: a setup handler of a probe
    project, executed at its first apply, reported what `Current()` found. From the root of a
    subsystem without a resources folder it found nothing, and `GetAll()` itself threw
    `ResourceNotFoundException`: neither a file of a package of the same subsystem nor a file
    of another subsystem, whether named relative to the folder or by the path of that example,
    while the same reader at the root of a subsystem with the folder found its file. The path of
    the example found nothing there either.

    A `Resource{...}` literal is another matter, and the message of the root does not offer it.
    The IDE server resolves the key of a literal across the resources folders of the whole
    subsystem: in a module at the root of a subsystem without a folder of its own, a file of
    one of its packages compiled clean, the same name in two packages was an ambiguous resource,
    and a file of another subsystem an unknown one - but which file such a literal reads at run
    time was not put to a run, so the way out stays the folder of the subsystem.

    The folder is looked up on disk, both spellings: a module that is not on disk (a buffer, a
    fixture) is not judged. A place that has the folder is not judged either - whether the
    file named at run time lies there is a fact of the data. The project module lies outside the
    subsystems and is not judged.
    """
    layout = _layout_from(facts)
    if not layout.known:
        return  # no descriptor at all - the placement of a module is unknown
    for rel, fact in facts.items():
        if fact["k"] != "cur":
            continue
        place = layout.place(Path(fact["path"]))
        if place is None:
            continue
        folder = place.subsystem_dir
        if place.package is not None:
            folder = folder.joinpath(*place.package.split("::"))
        if not folder.is_dir() or any((folder / name).is_dir() for name in _RESOURCE_DIRS):
            continue
        if place.package is None:
            message = i18n.t("code/package-resources-missing.root", package=place.subsystem)
        else:
            message = i18n.t("code/package-resources-missing.empty",
                             package=f"{place.subsystem}::{place.package}")
        for line, col in fact["calls"]:
            yield Diagnostic(
                rel, line, col, "code/package-resources-missing", Severity.WARNING, message,
                data={"namespace": place.key},
            )
