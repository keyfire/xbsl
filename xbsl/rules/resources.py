"""Resources addressed by `Ресурс{...}`: the shape of the key and its existence.

Two rules live here:

- code/resource-bare-name (tier C, file) – the key spells out the Ресурсы folder itself;
- code/unknown-resource (tier D, project) – the key resolves to nothing.

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

So the known set is the union of two sources: the RELATIVE POSIX PATH of every file under
the project's `Ресурсы` folders (the project root is the folder holding `Проект.yaml`;
a top-level file's path is its bare name) and the 152 names of the platform's image
library, taken from the documentation page `topics/image-library` - the first source of
truth, not a hand-written list. A qualified key (`Стд::Грузовик.svg`, the form the docs
show) is stripped of its namespace before the lookup. Without the documentation data the
rule stays silent: guessing without the library is exactly what produces false positives.
A Ресурсы-prefixed key is left to code/resource-bare-name, so one mistake is not reported
twice; a backslash spelling is unproven and skipped rather than judged.

The union spans the projects of the run - a resource of a foreign subsystem is never
reported, which is deliberate: whether the compiler resolves across subsystems is
untested, and a wider set can only silence the rule, never make it fire. Keys are matched
exactly: the platform's lookup is case-sensitive while a Windows checkout is not.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import docs, i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens

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
    "code/resource-bare-name.path": {
        "ru": "Ключ ресурса задаётся ОТНОСИТЕЛЬНО каталога Ресурсы: '{name}' начинается с "
              "самого каталога, платформа ищет такой путь внутри Ресурсы и применение сборки "
              "падает 'Неизвестный ресурс'. Правильно: 'Ресурс{{{base}}}'.",
        "en": "A resource key is a path RELATIVE to the {n[Ресурсы]} folder: '{name}' starts with "
              "that folder itself, the platform looks the path up inside {n[Ресурсы]} and applying "
              "the build fails with 'Неизвестный ресурс'. Correct: 'Ресурс{{{base}}}'.",
    },
}
i18n.register(MESSAGES)

#: The folder holding the resource files of a subsystem - BOTH spellings. The platform
#: accepts the English name as readily as the Russian one: probed on the local server with
#: the same form three times - a file under `Resources` resolves (`ok`), the same reference
#: with the file missing fails with "Неизвестный ресурс", and the same file moved into a
#: folder of any other name fails the same way. So the name matters and English is legal;
#: knowing only the Russian one made an English project look as if it had no resources.
_RESOURCE_DIRS = ("Ресурсы", "Resources")

#: The prefix of a resource uploaded into the application base (see the module docstring).
_UPLOADED_PREFIX = "inbase/"


def _resource_refs(toks: list[Token], text: str) -> Iterable[tuple[str, int, int]]:
    """(name inside the braces, line, column) for every `Ресурс{...}` of the module.

    Comments and string literals are already stripped by code_tokens, so a `Ресурс{}`
    mentioned in a comment cannot false-match. The name is taken from the source text
    between the braces, not glued back from tokens: a name may hold characters the lexer
    splits (`adv-auto.svg`) or spaces it drops.
    """
    for i, t in enumerate(toks):
        if t.kind != "IDENT" or t.value != "Ресурс" or i + 1 >= len(toks):
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
    if source.kind != "xbsl" or "Ресурс{" not in source.text:
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
    """Names of the platform's image library, or an empty set without the docs data."""
    page = docs.page(_IMAGE_LIBRARY_PAGE)
    if not page:
        return frozenset()
    return frozenset(_IMAGE_NAME_RE.findall(page.get("html") or ""))


def _unknown_resource_mapper(source: SourceFile) -> dict | None:
    """The map phase: a Проект.yaml contributes its folder, a module its resource refs."""
    if source.kind == "yaml":
        if source.path.name in ("Проект.yaml", "Project.yaml"):
            return {"root": str(source.path.parent)}
        return None
    if source.kind != "xbsl" or "Ресурс{" not in source.text:
        return None
    refs = list(_resource_refs(code_tokens(source), source.text))
    return {"refs": refs} if refs else None


def _project_resources(roots: Iterable[str]) -> set[str]:
    """Relative POSIX keys of every file under a resources folder of the given roots.

    The key of a resource is its path relative to the subsystem's Ресурсы folder
    (subfolders included); a top-level file's key is its bare name.
    """
    keys: set[str] = set()
    for root in roots:
        for res_dir in [d for name in _RESOURCE_DIRS for d in Path(root).rglob(name)]:
            if not res_dir.is_dir():
                continue
            for path in res_dir.rglob("*"):
                if path.is_file():
                    keys.add(path.relative_to(res_dir).as_posix())
    return keys


@rule(
    "code/unknown-resource", "code/unknown-resource.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_unknown_resource_mapper,
)
def unknown_resource(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    library = _platform_images()
    if not library:
        return  # no documentation data - the library is unknown, guessing would be wrong
    roots = {fact["root"] for fact in facts.values() if "root" in fact}
    if not roots:
        return  # no Проект.yaml in the run - nothing to compare against
    known = _project_resources(roots) | library
    for rel, fact in facts.items():
        for name, line, col in fact.get("refs", ()):
            if name.startswith(_UPLOADED_PREFIX):
                continue  # uploaded into the base - existence is a base fact
            if "\\" in name:
                continue  # a backslash spelling is unproven - skipped, not judged
            key = name.rsplit("::", 1)[-1].strip()  # Стд::Грузовик.svg -> Грузовик.svg
            if key.partition("/")[0] in _RESOURCE_DIRS:
                continue  # the Ресурсы-prefixed spelling - resource-bare-name reports it
            if key in known:
                continue
            yield Diagnostic(
                rel, line, col, "code/unknown-resource", Severity.ERROR,
                i18n.t("code/unknown-resource.unknown", name=name),
            )
