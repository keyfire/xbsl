"""Versioned data views over an immutable shared catalog and resource pool."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zlib
from functools import lru_cache
from pathlib import Path, PurePosixPath

from xbsl.storage_codec import Builder, Reader, encoded

FORMAT = 1


class StorageError(RuntimeError):
    pass


def within(root, name):
    logical = PurePosixPath(name)
    if not name or "\\" in name or logical.is_absolute() or ".." in logical.parts or ":" in name:
        raise StorageError(f"Invalid storage path: {name}")
    path = root.joinpath(*logical.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise StorageError(f"Storage path escapes its root: {name}")
    return path


def read_json_file(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as error:
        raise StorageError(f"Cannot read storage metadata {path}: {error}") from error


@lru_cache(maxsize=16)
def _metadata(path, size, modified):
    del size, modified
    return read_json_file(Path(path))


def metadata(path):
    stat = path.stat()
    return _metadata(str(path),stat.st_size,stat.st_mtime_ns)


def index(root):
    data = metadata(root / "index.json")
    if not isinstance(data, dict):
        raise StorageError("Invalid data version index")
    versions = data.get("available", ())
    if not isinstance(versions, (list, tuple)):
        raise StorageError("Invalid data version list")
    for version in versions:
        if not isinstance(version, str) or version in (".", "_shared") or len(PurePosixPath(version).parts) != 1:
            raise StorageError(f"Invalid data version: {version}")
        within(root, version)
    info = data.get("storage")
    if info is not None and (not isinstance(info, dict) or type(info.get("format")) is not int or info["format"] != FORMAT):
        raise StorageError(f"Unsupported data storage format in {root / 'index.json'}")
    return data


def manifest(root, version):
    data = index(root)
    if version not in data.get("available", ()):
        raise StorageError(f"Unknown data version: {version}")
    info = data.get("storage")
    if info is None:
        return None
    try:
        path = within(root, info["manifests"][version])
    except KeyError as error:
        raise StorageError(f"Missing manifest for {version}") from error
    result = metadata(path)
    if result.get("version") != version:
        raise StorageError(f"Manifest does not describe version {version}")
    return result


def catalog_path(root, description=None):
    return within(root, description["catalog"] if description is not None else index(root)["storage"]["catalog"])


@lru_cache(maxsize=8)
def _reader(path, size, modified):
    del size, modified
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return Reader(connection)
    finally:
        connection.close()


@lru_cache(maxsize=4)
def _projection_rows(path, size, modified):
    del size, modified
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if not connection.execute("SELECT name FROM sqlite_master WHERE name='view_cache'").fetchone():
            return {}
        return {row[0]: row[1:] for row in connection.execute("SELECT id,payload,digest FROM view_cache")}
    finally:
        connection.close()


@lru_cache(maxsize=16)
def _projection(path, size, modified, key):
    row = _projection_rows(path,size,modified).get(key)
    if row is None:
        return None
    raw = zlib.decompress(row[0])
    if hashlib.sha256(raw).hexdigest() != row[1]:
        raise StorageError(f"Corrupt derived view: {key}")
    return raw


def raw_json(root, version, name):
    root = Path(root)
    description = manifest(root, version)
    if description is None:
        path = within(root, f"{version}/{name}")
        return read_json_file(path) if path.is_file() else None
    key = description.get("files", {}).get(name)
    if key is None:
        return None
    path = catalog_path(root, description)
    try:
        stat = path.stat()
        projection = _projection(str(path), stat.st_size, stat.st_mtime_ns, key)
        return json.loads(projection) if projection is not None else _reader(str(path), stat.st_size, stat.st_mtime_ns).decode(key)
    except (OSError, sqlite3.Error, RuntimeError) as error:
        raise StorageError(f"Cannot read shared data {version}/{name}: {error}") from error


def asset(root, version, name):
    root = Path(root)
    if not name.startswith("assets/") or ".." in name or "\\" in name:
        return None
    description = manifest(root, version)
    if description is None:
        path = within(root, f"{version}/{name}")
        return path.read_bytes() if path.is_file() else None
    key = description.get("assets", {}).get(name)
    if key is None:
        return None
    path = within(root, f"_shared/assets/{key[:2]}/{key}.bin")
    if not path.is_file():
        raise StorageError(f"Missing shared asset: {name} ({key})")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != key:
        raise StorageError(f"Corrupt shared asset: {name} ({key})")
    return content


def logical_files(root, version):
    description = manifest(root, version)
    if description is not None:
        return list(description.get("files", {}))
    return [p.name for p in sorted((root / version).glob("*.json"))]


def logical_assets(root, version):
    description = manifest(root, version)
    if description is not None:
        return list(description.get("assets", {}))
    folder = root / version
    return [p.relative_to(folder).as_posix() for p in sorted((folder / "assets").rglob("*")) if p.is_file()]


def put(root, name, content):
    path = within(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise StorageError(f"Shared object already exists with different contents: {path}")
        return
    handle, temporary = tempfile.mkstemp(prefix=".storage-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def pack(source, target, versions=None):
    source, target = Path(source), Path(target)
    original = index(source)
    selected = list(original["available"] if versions is None else versions)
    if not selected or any(v not in original["available"] for v in selected):
        raise StorageError("Select at least one available data version")
    target.mkdir(parents=True, exist_ok=True)
    from xbsl.storage_docs import DocsBuilder
    inputs = {version: source for version in selected}
    if versions is not None and (target / "index.json").is_file():
        previous = index(target)
        updated = set(selected)
        builds = {key:value for key,value in previous.get("builds",{}).items() if key not in updated}
        builds.update({key:value for key,value in original.get("builds",{}).items() if key in updated})
        original = {**previous, **original}
        if builds or "builds" in original:
            original["builds"] = builds
        for version in previous["available"]:
            if version not in inputs:
                inputs[version] = target
        selected = list(previous["available"]) + [v for v in selected if v not in previous["available"]]
        if previous.get("default") in selected:
            original = {**original, "default": previous["default"]}
    builder = Builder()
    documentation = DocsBuilder()
    descriptions = {}
    for version in selected:
        input_root = inputs[version]
        description = {"version": version, "files": {}, "assets": {}}
        for name in logical_files(input_root, version):
            value = raw_json(input_root, version, name)
            description["files"][name] = builder.encode(value, name, version)
        for name in logical_assets(input_root, version):
            content = asset(input_root, version, name)
            key = hashlib.sha256(content).hexdigest()
            put(target, f"_shared/assets/{key[:2]}/{key}.bin", content)
            description["assets"][name] = key
        connection = open_docs(input_root, version)
        if connection is not None:
            try:
                description["docs"] = documentation.add(version, connection)
            finally:
                connection.close()
        descriptions[version] = description
    with tempfile.TemporaryDirectory(prefix=".storage-stage-", dir=target) as temporary:
        database = Path(temporary) / "catalog.sqlite"
        connection = sqlite3.connect(database)
        try:
            builder.write(connection)
            documentation.write(connection)
            connection.execute(f"PRAGMA user_version={FORMAT}")
            connection.commit()
            connection.execute("VACUUM")
        finally:
            connection.close()
        content = database.read_bytes()
        key = hashlib.sha256(content).hexdigest()
        catalog = f"_shared/catalog/{key}.sqlite"
        put(target, catalog, content)
    manifests = {}
    for version, description in descriptions.items():
        description["catalog"] = catalog
        content = encoded(description) + b"\n"
        key = hashlib.sha256(content).hexdigest()
        name = f"{version}/manifest.{key}.json"
        put(target, name, content)
        manifests[version] = name
    new_index = {k: v for k, v in original.items() if k != "storage"}
    new_index["available"] = selected
    if new_index.get("default") not in selected:
        new_index["default"] = selected[-1]
    new_index["storage"] = {"format": FORMAT, "catalog": catalog, "manifests": manifests}
    handle, temporary = tempfile.mkstemp(prefix=".index-", dir=target)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(encoded(new_index) + b"\n")
        os.replace(temporary, target / "index.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"versions": selected, "objects": len(builder.nodes), "facts": len(builder.facts)}


def dependencies(root, version):
    root = Path(root)
    data = index(root)
    info = data.get("storage")
    if info is None:
        return [root / "index.json"]
    return [root / "index.json", within(root, info["manifests"][version]), within(root, info["catalog"])]


def open_docs(root, version):
    root = Path(root)
    description = manifest(root, version)
    if description is None:
        path = within(root, f"{version}/docs.sqlite")
        if not path.is_file():
            return None
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection
    if not description.get("docs"):
        return None
    from xbsl.storage_docs import open_shared
    try:
        return open_shared(catalog_path(root, description), version, description["docs"])
    except (sqlite3.Error, OSError, RuntimeError) as error:
        raise StorageError(f"Cannot read shared documentation for {version}: {error}") from error

def referenced_files(root):
    root = Path(root)
    data = index(root)
    paths = {root / "index.json"}
    if not data.get("storage"):
        for version in data["available"]:
            paths.update(p for p in (root / version).rglob("*") if p.is_file())
        return sorted(paths)
    paths.add(within(root, data["storage"]["catalog"]))
    for version in data["available"]:
        paths.add(within(root, data["storage"]["manifests"][version]))
        description = manifest(root, version)
        for key in description.get("assets", {}).values():
            paths.add(within(root, f"_shared/assets/{key[:2]}/{key}.bin"))
    return sorted(paths)


def verify(root):
    root = Path(root)
    data = index(root)
    for path in referenced_files(root):
        if not path.is_file():
            raise StorageError(f"Missing storage dependency: {path}")
        if path.name.startswith("manifest."):
            expected = path.name.split(".")[1]
        elif path.parent.name == "catalog" or path.suffix == ".bin":
            expected = path.stem
        else:
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise StorageError(f"Corrupt storage dependency: {path}")
    objects = 0
    for version in data["available"]:
        for name in logical_files(root, version):
            result = raw_json(root, version, name)
            description = manifest(root, version)
            if description is not None:
                catalog = catalog_path(root, description)
                stat = catalog.stat()
                canonical = _reader(str(catalog),stat.st_size,stat.st_mtime_ns).decode(description["files"][name])
                if encoded(result) != encoded(canonical):
                    raise StorageError(f"Derived view differs from canonical objects: {version}/{name}")
            objects += 1
        connection = open_docs(root, version)
        if connection is not None:
            try:
                connection.execute("SELECT COUNT(*) FROM pages").fetchone()
                description = manifest(root, version)
                if description is not None:
                    fts = description["docs"]["fts"]
                    # Integrity checks write a control row and are done during construction;
                    # readers verify the catalog digest without touching its immutable bytes.
                    connection.execute(f"SELECT COUNT(*) FROM {fts}").fetchone()
            finally:
                connection.close()
    return {"valid": True, "versions": data["available"], "files": len(referenced_files(root)), "views": objects}


def export(root, target, versions=None):
    root, target = Path(root), Path(target)
    if root.resolve() == target.resolve():
        raise StorageError("Export requires a separate destination")
    data = index(root)
    selected = list(data["available"] if versions is None else versions)
    if not selected or any(v not in data["available"] for v in selected):
        raise StorageError("Select at least one available data version")
    target.mkdir(parents=True, exist_ok=True)
    for version in selected:
        folder = target / version
        folder.mkdir(parents=True, exist_ok=True)
        for name in logical_files(root, version):
            path = within(folder, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encoded(raw_json(root, version, name)) + b"\n")
        for name in logical_assets(root, version):
            path = within(folder, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(asset(root, version, name))
        source = open_docs(root, version)
        if source is not None:
            from xbsl.storage_docs import export_docs
            try:
                export_docs(source, folder / "docs.sqlite")
            finally:
                source.close()
    output = {key: value for key, value in data.items() if key != "storage"}
    output["available"] = selected
    if output.get("default") not in selected:
        output["default"] = selected[-1]
    (target / "index.json").write_bytes(encoded(output) + b"\n")
    return {"versions": selected, "target": str(target)}


def prune(root, *, apply=False):
    import re
    root = Path(root)
    verify(root)
    reachable = {path.resolve() for path in referenced_files(root)}
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file() or path.resolve() in reachable:
            continue
        relative = path.relative_to(root).as_posix()
        within(root, relative)
        generated = (relative.startswith("_shared/") and re.fullmatch(r"[0-9a-f]{64}\.(bin|sqlite)", path.name)) or re.fullmatch(r"manifest\.[0-9a-f]{64}\.json", path.name)
        if generated:
            candidates.append(path)
    deleted, deferred = [], []
    if apply:
        for path in candidates:
            try:
                path.unlink()
                deleted.append(path.relative_to(root).as_posix())
            except PermissionError:
                deferred.append(path.relative_to(root).as_posix())
            except FileNotFoundError:
                pass
    if apply:
        available = set(index(root)["available"])
        folders = {path.parent for path in candidates if path.name.startswith("manifest.")}
        for folder in sorted(folders):
            if folder.parent != root or folder.name in available:
                continue
            try:
                folder.rmdir()
            except OSError:
                # Keep folders containing unrelated files or held by another process.
                pass
    return {"unused": [p.relative_to(root).as_posix() for p in candidates], "deleted": deleted, "deferred": deferred}