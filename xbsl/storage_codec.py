"""Immutable JSON definitions and contextual vocabulary facts."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def identity(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def vocabulary(name, path):
    if name == "terms.json" and len(path) == 1:
        roles = {"types": "type", "facets": "facet", "properties": "property", "enums": "enum", "kinds": "kind", "query": "query", "query_reserved": "query-reserved"}
        if path[0] in roles:
            return roles[path[0]], "", False
    if name == "terms_full.json":
        if path == ("common",):
            return "common", "", False
        if len(path) == 2 and path[0] == "members":
            return "member", path[1], False
    if name == "uiterms.json":
        if path in (("types",), ("properties",)):
            return "type" if path[0] == "types" else "property", "", True
        if path == ("packages",):
            return "package", "", False
        if len(path) == 2 and path[0] in ("member_names", "enum_values"):
            return "member" if path[0] == "member_names" else "enum", path[1], False
    return None


class Builder:
    def __init__(self):
        self.nodes = {}
        self.facts = {}
        self.sources = set()
        self.projections = {}

    def encode(self, value, name="", version="", path=()):
        scope = vocabulary(name, path) if isinstance(value, dict) else None
        if scope and all(isinstance(v, str) for v in value.values()):
            role, owner, reverse = scope
            facts = []
            for key, item in value.items():
                ru, en = (item, key) if reverse else (key, item)
                fact = (role, owner, ru, en)
                key_id = identity(fact)
                self.facts[key_id] = fact
                self.sources.add((key_id, version, name))
                facts.append(key_id)
            node = ["t", reverse, facts]
        elif isinstance(value, dict):
            node = ["d", [[k, self.reference(v, name, version, (*path, k))] for k, v in value.items()]]
        elif isinstance(value, list):
            node = ["l", [self.reference(v, name, version, (*path, str(i))) for i, v in enumerate(value)]]
        else:
            node = ["v", value]
        key_id = identity(node)
        self.nodes[key_id] = encoded(node)
        if not path:
            self.projections[key_id] = encoded(value)
        return key_id

    def reference(self, value, name, version, path):
        if isinstance(value, (dict, list)):
            return ["r", self.encode(value, name, version, path)]
        return ["v", value]

    def write(self, connection):
        connection.executescript("""
            CREATE TABLE json_nodes (id TEXT PRIMARY KEY, payload BLOB NOT NULL) WITHOUT ROWID;
            CREATE TABLE term_facts (id TEXT PRIMARY KEY, role TEXT, owner TEXT, ru TEXT, en TEXT) WITHOUT ROWID;
            CREATE TABLE fact_sources (fact TEXT, version TEXT, view TEXT, PRIMARY KEY(fact,version,view)) WITHOUT ROWID;
            CREATE TABLE view_cache (id TEXT PRIMARY KEY, payload BLOB NOT NULL, digest TEXT NOT NULL) WITHOUT ROWID;
        """)
        connection.executemany("INSERT INTO json_nodes VALUES (?,?)", [(key, zlib.compress(value, 9)) for key, value in sorted(self.nodes.items())])
        connection.executemany("INSERT INTO term_facts VALUES (?,?,?,?,?)", [(key, *value) for key, value in sorted(self.facts.items())])
        connection.executemany("INSERT INTO fact_sources VALUES (?,?,?)", sorted(self.sources))
        connection.executemany("INSERT INTO view_cache VALUES (?,?,?)", [(key,zlib.compress(value,9),hashlib.sha256(value).hexdigest()) for key,value in sorted(self.projections.items())])


class Reader:
    def __init__(self, connection):
        self.nodes = dict(connection.execute("SELECT id,payload FROM json_nodes"))
        self.facts = {row[0]: row[1:] for row in connection.execute("SELECT id,role,owner,ru,en FROM term_facts")}
        self.parsed = {}

    def decode(self, key):
        if key not in self.parsed:
            try:
                raw = zlib.decompress(self.nodes[key])
            except KeyError as error:
                raise RuntimeError(f"Missing shared JSON object: {key}") from error
            if hashlib.sha256(raw).hexdigest() != key:
                raise RuntimeError(f"Corrupt shared JSON object: {key}")
            self.parsed[key] = json.loads(raw)
        node = self.parsed[key]
        if node[0] == "d":
            return {k: self.value(v) for k, v in node[1]}
        if node[0] == "l":
            return [self.value(v) for v in node[1]]
        if node[0] == "t":
            result = {}
            for fact_id in node[2]:
                try:
                    role, owner, ru, en = self.facts[fact_id]
                except KeyError as error:
                    raise RuntimeError(f"Missing vocabulary fact: {fact_id}") from error
                if identity((role, owner, ru, en)) != fact_id:
                    raise RuntimeError(f"Corrupt vocabulary fact: {fact_id}")
                result[en if node[1] else ru] = ru if node[1] else en
            return result
        return node[1]

    def value(self, value):
        return self.decode(value[1]) if value[0] == "r" else value[1]
