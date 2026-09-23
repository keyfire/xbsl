"""One-pass reachability audit for files under project Resources folders.

The result is a candidate report, never a deletion plan. Static resolution, bounded computed
paths and resource-to-resource edges can prove reachability. Arbitrary strings, reflection and
external data cannot prove that a file is dead, so uncertain files stay separate from unused
candidates and every candidate carries an explicit confidence label.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, engine
from xbsl import parser as P
from xbsl import resources as resource_model
from xbsl import terms, typeinfer
from xbsl.layout import Layout
from xbsl.restext import RESOURCE_DIRS


_PLACEHOLDER = re.compile(r"[%$]\{?[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*\}?")
_RESOURCE_LINKS = (
    re.compile(r"url\(\s*['\"]?([^'\")]+)", re.I),
    re.compile(r"(?:src|href|xlink:href)\s*=\s*['\"]([^'\"]+)", re.I),
    re.compile(r"@import\s+(?:url\(\s*)?['\"]([^'\"]+)", re.I),
    re.compile(r"(?:from\s+|import\s*)['\"]([^'\"]+)['\"]", re.I),
)
_LINKABLE_SUFFIXES = frozenset({".css", ".html", ".htm", ".svg", ".js"})


@lru_cache(maxsize=1)
def _platform_words() -> tuple[
    frozenset[str], frozenset[str], frozenset[str], frozenset[str],
]:
    """Resource literal, package type, Current and Get spellings from platform data."""
    owner = "ПакетРесурсов"
    current = terms.member_english_of(owner, "Текущий")
    get = terms.member_english_of(owner, "Получить")
    return (
        frozenset(terms.key_forms("Ресурс")),
        frozenset(terms.forms(owner, "types")),
        frozenset(name for name in ("Текущий", current) if name is not None),
        frozenset(name for name in ("Получить", get) if name is not None),
    )


dataset.register_reset(_platform_words.cache_clear)


def _read(path: Path, reader: Callable[[Path], str] | None) -> str:
    return reader(path) if reader is not None else path.read_text(encoding="utf-8-sig")


def _lexical(path: Path) -> Path:
    """Absolute path without following a symlink in the path or its parents."""
    return Path(os.path.abspath(path))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _position(text: str, offset: int) -> dict[str, int]:
    line_start = text.rfind("\n", 0, offset) + 1
    return {
        "line": text.count("\n", 0, offset),
        "character": len(text[line_start:offset].encode("utf-16-le")) // 2,
    }


def _range(text: str, start: int, end: int) -> dict[str, dict[str, int]]:
    return {"start": _position(text, start), "end": _position(text, end)}


def _literal_text(node: P.Literal) -> str | None:
    text = node.text.strip()
    if node.kind != "STRING" or len(text) < 2 or text[0] not in "\"'" or text[-1] != text[0]:
        return None
    value = text[1:-1]
    return None if "%{" in value or "${" in value else value


def _walk_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)


def _current_get(call: P.Call) -> bool:
    _resources, package_names, current_names, get_names = _platform_words()
    if not isinstance(call.callee, P.Member) or call.callee.name not in get_names:
        return False
    current = call.callee.obj
    if not isinstance(current, P.Call) or not isinstance(current.callee, P.Member):
        return False
    return (current.callee.name in current_names
            and isinstance(current.callee.obj, P.Name)
            and current.callee.obj.name in package_names)


def _call_target(call: P.Call) -> tuple[str | None, str] | None:
    if isinstance(call.callee, P.Name):
        return None, call.callee.name
    if isinstance(call.callee, P.Member) and isinstance(call.callee.obj, P.Name):
        return call.callee.obj.name, call.callee.name
    return None


@dataclass
class _Resource:
    path: Path
    directory: Path
    key: str
    namespace: str
    project: Path | None
    external: bool = False
    evidence: list[dict] = field(default_factory=list)

    @property
    def stem(self) -> str:
        return self.key[:-len(self.path.suffix)] if self.path.suffix else ""

    @property
    def status(self) -> str:
        strengths = {item["strength"] for item in self.evidence}
        for strength in ("referenced", "dynamic", "uncertain"):
            if strength in strengths:
                return strength
        return "unused"


@dataclass(frozen=True)
class _Edge:
    source: _Resource
    target: _Resource
    kind: str
    detail: str
    uncertain: bool = False


@dataclass(frozen=True)
class _Wrapper:
    index: int
    parameter: str


class _Analyzer:
    def __init__(self, root: Path, reader: Callable[[Path], str] | None) -> None:
        from xbsl import scaffold

        self.scaffold = scaffold
        self.root = root.resolve()
        self.reader = reader
        self.layout = scaffold._root_layout(self.root) if self.root.is_dir() else Layout()
        self.scopes = (
            resource_model.resource_scopes(self.root, self.layout)
            if self.root.is_dir() else ()
        )
        self.resources: dict[str, _Resource] = {}
        self.by_scope_key: dict[tuple[str, str], list[_Resource]] = defaultdict(list)
        self.by_scope_stem: dict[tuple[str, str], list[_Resource]] = defaultdict(list)
        for scope in self.scopes:
            directory = _lexical(scope.directory)
            for key in scope.keys:
                path = _lexical(directory / Path(key))
                external = not _inside(path.resolve(), self.root)
                item = _Resource(
                    path, directory, key, scope.place.key,
                    (_lexical(scope.place.project_dir)
                     if scope.place.project_dir else None),
                    external,
                )
                if external:
                    item.evidence.append({
                        "path": str(path), "kind": "external-symlink",
                        "strength": "uncertain", "detail": "resolved target outside root",
                    })
                self.resources[str(path)] = item
                self.by_scope_key[(str(item.directory), key)].append(item)
                if item.stem:
                    self.by_scope_stem[(str(item.directory), item.stem)].append(item)
        self.modules: dict[
            tuple[Path | None, str], list[tuple[Path, P.Module, str]]
        ] = defaultdict(list)
        self.wrappers: dict[tuple[Path | None, str, str], _Wrapper] = {}
        self.edges: list[_Edge] = []

    def _evidence(
        self, items: Iterable[_Resource], source: Path, text: str, start: int, end: int,
        kind: str, strength: str, detail: str = "",
    ) -> None:
        evidence = {
            "path": str(source), "range": _range(text, start, end),
            "kind": kind, "strength": strength,
        }
        if detail:
            evidence["detail"] = detail
        for item in items:
            if evidence not in item.evidence:
                item.evidence.append(evidence)

    def _edge(self, source: Path, targets: Iterable[_Resource], kind: str, detail: str,
              uncertain: bool = False) -> None:
        origin = self.resources.get(str(_lexical(source)))
        if origin is None:
            return
        self.edges.extend(_Edge(origin, target, kind, detail, uncertain) for target in targets)

    def _exact(self, directory: Path, key: str) -> tuple[_Resource, ...]:
        return tuple(self.by_scope_key.get((str(_lexical(directory)), key), ()))

    def _stem(self, directory: Path, stem: str) -> tuple[_Resource, ...]:
        return tuple(self.by_scope_stem.get((str(_lexical(directory)), stem), ()))

    def _protect_project(self, path: Path, kind: str, detail: str) -> None:
        """Keep candidates conservative when one project source cannot be analyzed."""
        project = self.layout.project_dir_of(path)
        evidence = {
            "path": str(path), "kind": kind,
            "strength": "uncertain", "detail": detail,
        }
        for scope in self.scopes:
            if scope.place.project_dir != project:
                continue
            for key in scope.keys:
                for item in self._exact(scope.directory, key):
                    if evidence not in item.evidence:
                        item.evidence.append(evidence)

    def _scopes_for(self, path: Path):
        project = self.layout.project_dir_of(path)
        return tuple(scope for scope in self.scopes if scope.place.project_dir == project)

    def _namespace(self, scope, project: Path | None) -> str:
        if scope.place.project_dir == project:
            return scope.place.key
        identity = self.layout.identity(scope.place.project_dir)
        prefix = f"{identity[0]}::{identity[1]}" if identity else None
        return self.scaffold._full_namespace(prefix, scope.place.key)

    def _resolve_static(
        self, path: Path, text: str, written: str, start: int, end: int, kind: str,
    ) -> None:
        qualifier, separator, tail = written.rpartition("::")
        key = tail.strip()
        place = self.layout.place(path)
        project = self.layout.project_dir_of(path)
        local_scopes = self._scopes_for(path)
        namespaces = {scope.place.key for scope in local_scopes}
        imports = (
            self.scaffold._yaml_import_names(text) if path.suffix == ".yaml"
            else self.scaffold._module_import_names(text)
        )
        imported = {self.layout.local_name(name, project) for name in imports}
        target = None
        if separator:
            target = self.layout.resolve(qualifier.split("::"), project, namespaces)
            if target is None:
                full_names = {self._namespace(scope, project) for scope in self.scopes}
                target = qualifier if qualifier in full_names else None
            if target is None:
                return
        candidates: list[resource_model.ResourceCandidate] = []
        by_token: dict[str, _Resource] = {}
        scopes = self.scopes if target is not None else local_scopes
        for scope in scopes:
            namespace = self._namespace(scope, project)
            if (key not in scope.keys
                    or (target is not None and namespace != target)
                    or (target is None and scope.place.project_dir != project)):
                continue
            token = str(scope.directory.resolve())
            candidates.append(resource_model.ResourceCandidate(
                namespace,
                (scope.place.project_dir == project and place is not None
                 and scope.place.subsystem == place.subsystem),
                scope.public,
                token,
            ))
            for item in self._exact(scope.directory, key):
                by_token[token] = item
        resolution = resource_model.resolve_resource(candidates, imported, target)
        selected = [by_token[candidate.token] for candidate in resolution.candidates
                    if candidate.token in by_token]
        if resolution.kind == "resolved":
            self._evidence(selected, path, text, start, end, kind, "referenced", written)
        elif resolution.kind in {"ambiguous", "unproven"}:
            self._evidence(selected, path, text, start, end, kind, "uncertain", resolution.kind)

    def _collect_modules(self, paths: list[Path]) -> None:
        for path in paths:
            try:
                text = _read(path, self.reader)
            except (OSError, UnicodeError):
                self._protect_project(path, "read-error", "source could not be read")
                continue
            tree, errors = P.parse_text(text)
            if errors or not isinstance(tree, P.Module):
                self._protect_project(
                    path, "parse-error",
                    f"source has {len(errors)} parse error(s)",
                )
                continue
            project = self.layout.project_dir_of(path)
            self.modules[(project, path.stem)].append((path, tree, text))
        for (project, module), copies in self.modules.items():
            if len(copies) != 1:
                continue
            _path, tree, _text = copies[0]
            for method in (member for member in tree.members if isinstance(member, P.Method)):
                params = {param.name: index for index, param in enumerate(method.params)}
                indices = {
                    params[arg.value.name]
                    for call in typeinfer.walk_nodes(method)
                    if isinstance(call, P.Call) and _current_get(call) and call.args
                    for arg in call.args[:1]
                    if isinstance(arg.value, P.Name) and arg.value.name in params
                }
                if len(indices) == 1:
                    index = next(iter(indices))
                    self.wrappers[(project, module, method.name)] = _Wrapper(
                        index, method.params[index].name,
                    )

    def _scope_of_module(self, module: str | None, source: Path):
        if module is None:
            place = self.layout.place(source)
        else:
            project = self.layout.project_dir_of(source)
            copies = self.modules.get((project, module)) or ()
            place = self.layout.place(copies[0][0]) if len(copies) == 1 else None
        if place is None:
            return None
        return next((scope for scope in self.scopes
                     if scope.place.project_dir == place.project_dir
                     and scope.place.key == place.key), None)

    def _runtime_path(
        self, scope, value: str, source: Path, text: str, start: int, end: int, kind: str,
    ) -> None:
        if scope is None:
            return
        placeholder = _PLACEHOLDER.search(value)
        if placeholder:
            prefix = value[:placeholder.start()]
            folder = prefix[:prefix.rfind("/") + 1] if "/" in prefix else ""
            matched = [item for key in scope.keys if key.startswith(folder)
                       for item in self._exact(scope.directory, key)]
            self._evidence(matched, source, text, start, end, kind, "dynamic", value)
            return
        self._evidence(
            self._exact(scope.directory, value), source, text, start, end,
            kind, "referenced", value,
        )

    @staticmethod
    def _call_argument(call: P.Call, wrapper: _Wrapper) -> P.Expr | None:
        named = next((arg.value for arg in call.args if arg.name == wrapper.parameter), None)
        if named is not None:
            return named
        positional = [arg.value for arg in call.args if arg.name is None]
        return positional[wrapper.index] if wrapper.index < len(positional) else None

    def _scan_module(self, path: Path, tree: P.Module, text: str) -> None:
        resource_words = _platform_words()[0]
        for node in typeinfer.walk_nodes(tree):
            if not isinstance(node, P.Literal):
                continue
            if node.kind == "RESOLVABLE" and node.text in resource_words:
                raw = text[node.start:node.end]
                if "{" in raw and "}" in raw:
                    body_start = node.start + raw.find("{") + 1
                    body_end = node.start + raw.rfind("}")
                    written = text[body_start:body_end].strip()
                    trim = len(text[body_start:body_end]) - len(text[body_start:body_end].lstrip())
                    self._resolve_static(
                        path, text, written, body_start + trim,
                        body_start + trim + len(written), "literal",
                    )
            elif node.kind == "STRING" and (value := _literal_text(node)) is not None:
                scopes = self._scopes_for(path)
                for scope in scopes:
                    exact = self._exact(scope.directory, value)
                    stem = self._stem(scope.directory, value)
                    if exact:
                        self._evidence(exact, path, text, node.start, node.end,
                                       "string", "uncertain", value)
                    if stem:
                        self._evidence(stem, path, text, node.start, node.end,
                                       "stem", "uncertain", value)
        own_scope = self._scope_of_module(None, path)
        for method in (member for member in tree.members if isinstance(member, P.Method)):
            project = self.layout.project_dir_of(path)
            direct_wrapper = (project, path.stem, method.name) in self.wrappers
            for call in typeinfer.walk_nodes(method):
                if not isinstance(call, P.Call):
                    continue
                if _current_get(call):
                    if direct_wrapper:
                        continue
                    argument = call.args[0].value if call.args else None
                    if (isinstance(argument, P.Literal)
                            and (value := _literal_text(argument)) is not None):
                        self._runtime_path(
                            own_scope, value, path, text, argument.start, argument.end,
                            "current-get",
                        )
                    elif own_scope is not None:
                        matched = [item for key in own_scope.keys
                                   for item in self._exact(own_scope.directory, key)]
                        self._evidence(
                            matched, path, text, call.start, call.end,
                            "current-get", "uncertain", "unknown key",
                        )
                    continue
                target = _call_target(call)
                if target is None:
                    continue
                receiver, method_name = target
                owner = receiver or path.stem
                wrapper = self.wrappers.get((project, owner, method_name))
                if wrapper is None:
                    continue
                argument = self._call_argument(call, wrapper)
                scope = self._scope_of_module(owner, path)
                if (isinstance(argument, P.Literal)
                        and (value := _literal_text(argument)) is not None):
                    self._runtime_path(
                        scope, value, path, text,
                        argument.start, argument.end, "wrapper",
                    )
                elif scope is not None:
                    matched = [item for key in scope.keys
                               for item in self._exact(scope.directory, key)]
                    self._evidence(
                        matched, path, text, call.start, call.end,
                        "wrapper", "uncertain", "unknown key",
                    )

    def _scan_yaml(self, path: Path, text: str) -> None:
        literal = self.scaffold._resource_literal_re()
        offset = 0
        for line in text.split("\n"):
            if not line.lstrip().startswith("#"):
                for match in literal.finditer(line):
                    self._resolve_static(
                        path, text, match.group("body"), offset + match.start("body"),
                        offset + match.end("body"), "yaml-literal",
                    )
                bare = self.scaffold._YAML_BARE_VALUE.match(line)
                if bare is not None:
                    value = bare.group("value")
                    if "." in value.rpartition("/")[2]:
                        self._resolve_static(
                            path, text, value, offset + bare.start("value"),
                            offset + bare.end("value"), "yaml-value",
                        )
                for quoted in self.scaffold._YAML_QUOTED.finditer(line):
                    value = quoted.group(0)[1:-1]
                    if not value or "%{" in value or "${" in value:
                        continue
                    for scope in self._scopes_for(path):
                        exact = self._exact(scope.directory, value)
                        stem = self._stem(scope.directory, value)
                        if exact:
                            self._evidence(exact, path, text, offset + quoted.start(),
                                           offset + quoted.end(), "string", "uncertain", value)
                        if stem:
                            self._evidence(stem, path, text, offset + quoted.start(),
                                           offset + quoted.end(), "stem", "uncertain", value)
            offset += len(line) + 1

    def _scan_json(self) -> None:
        for origin in self.resources.values():
            if origin.external or origin.path.suffix.lower() != ".json":
                continue
            try:
                text = _read(origin.path, self.reader)
                data = json.loads(text)
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            for value in _walk_values(data):
                exact = self._exact(origin.directory, value)
                stem = self._stem(origin.directory, value)
                matched = tuple(exact or stem)
                for target in matched:
                    self.edges.append(_Edge(
                        origin, target, "json", value,
                        uncertain=not exact and len(matched) != 1,
                    ))

    def _scan_resource_links(self) -> None:
        for origin in self.resources.values():
            if origin.external or origin.path.suffix.lower() not in _LINKABLE_SUFFIXES:
                continue
            try:
                text = _read(origin.path, self.reader)
            except (OSError, UnicodeError):
                continue
            for pattern in _RESOURCE_LINKS:
                for match in pattern.finditer(text):
                    written = match.group(1).strip().split("?", 1)[0].split("#", 1)[0]
                    if (not written or "://" in written
                            or written.startswith(("data:", "/", "#"))):
                        continue
                    key = posixpath.normpath(
                        posixpath.join(posixpath.dirname(origin.key), written)
                    )
                    if key == ".." or key.startswith("../"):
                        continue
                    self.edges.extend(
                        _Edge(origin, target, "resource-link", written)
                        for target in self._exact(origin.directory, key)
                    )

    def _propagate(self) -> None:
        outgoing: dict[str, list[_Edge]] = defaultdict(list)
        for edge in self.edges:
            outgoing[str(edge.source.path)].append(edge)
        queue = deque(item for item in self.resources.values() if item.status != "unused")
        applied: set[tuple[str, str, str, str]] = set()
        while queue:
            source = queue.popleft()
            for edge in outgoing.get(str(source.path), ()):
                strength = "uncertain" if edge.uncertain else source.status
                marker = (str(source.path), str(edge.target.path), edge.kind, strength)
                if marker in applied:
                    continue
                applied.add(marker)
                before = edge.target.status
                edge.target.evidence.append({
                    "path": str(source.path), "kind": edge.kind,
                    "strength": strength, "detail": edge.detail,
                })
                if edge.target.status != before:
                    queue.append(edge.target)

    @staticmethod
    def _item(item: _Resource) -> dict:
        return {
            "path": str(item.path), "resourcesDir": str(item.directory),
            "key": item.key, "namespace": item.namespace,
            "project": str(item.project) if item.project is not None else None,
            "status": item.status,
            "confidence": "candidate" if item.status == "unused" else item.status,
            "evidence": item.evidence[:20],
        }

    def run(self) -> dict:
        if not self.root.is_dir():
            return _empty(self.root)
        modules = [
            path for path in engine.find_sources(self.root, "*.xbsl")
            if str(_lexical(path)) not in self.resources
        ]
        self._collect_modules(modules)
        for copies in self.modules.values():
            for path, tree, text in copies:
                self._scan_module(path, tree, text)
        for path in engine.find_sources(self.root, "*.yaml"):
            if any(part in RESOURCE_DIRS
                   for part in path.relative_to(self.root).parts[:-1]):
                continue
            try:
                self._scan_yaml(path, _read(path, self.reader))
            except (OSError, UnicodeError):
                self._protect_project(path, "read-error", "source could not be read")
                continue
        self._scan_json()
        self._scan_resource_links()
        self._propagate()
        items = sorted(self.resources.values(), key=lambda item: str(item.path))
        counts = Counter(item.status for item in items)
        return {
            "root": str(self.root),
            "summary": {
                "resources": len(items),
                "referenced": counts["referenced"],
                "dynamic": counts["dynamic"],
                "uncertain": counts["uncertain"],
                "unused": counts["unused"],
            },
            "unused": [self._item(item) for item in items if item.status == "unused"],
            "dynamic": [self._item(item) for item in items if item.status == "dynamic"],
            "uncertain": [self._item(item) for item in items if item.status == "uncertain"],
            "referenced": [self._item(item) for item in items if item.status == "referenced"],
        }


def _empty(root: Path) -> dict:
    return {
        "root": str(root.resolve()),
        "summary": {
            "resources": 0, "referenced": 0, "dynamic": 0, "uncertain": 0, "unused": 0,
        },
        "unused": [], "dynamic": [], "uncertain": [], "referenced": [],
    }


def analyze(root: Path, *, reader: Callable[[Path], str] | None = None) -> dict:
    """Audit resource reachability once; returned unused files are candidates, not proof."""
    return _Analyzer(Path(root), reader).run()


def compact(answer: dict, *, include_protected: bool = False, limit: int = 100) -> dict:
    """Compact API response: complete totals, limited candidate/protected lists."""
    limit = max(0, int(limit))
    sections = ["unused", *(("dynamic", "uncertain") if include_protected else ())]
    out = {"root": answer["root"], "summary": dict(answer["summary"])}
    out["hasMore"] = any(len(answer.get(section, ())) > limit for section in sections)
    for section in sections:
        out[section] = list(answer.get(section, ()))[:limit]
    return out
