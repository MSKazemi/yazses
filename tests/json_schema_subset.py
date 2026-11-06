"""A small, offline JSON Schema (draft-07) checker for the vendored packaging schemas.

Two packaging artifacts are checked against a verbatim copy of the schema their
consumer publishes: the MCP registry's ``server.json`` (#639) and the MCP Bundle's
``manifest.json`` (#638). ``jsonschema`` is a dependency of the optional ``mcp`` SDK
only, not of a base or dev install, so the check is this walk instead.

It implements exactly the keywords those two schemas use. Anything else it meets fails
loudly (``AssertionError``) rather than passing silently, so a newer vendored schema
that brings a new keyword cannot be "validated" by a walk that ignores it.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlsplit

#: Keywords that annotate and never reject.
ANNOTATIONS = frozenset({
    "$comment", "$id", "$schema", "definitions", "description", "example", "examples",
    "default", "title",
})
_JSON_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "null": lambda v: v is None,
}
# Deliberately loose: one "@" with something on each side and a dot in the domain.
# The schemas use `format: email` only on optional author fields.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_uri(value: str) -> bool:
    parts = urlsplit(value)
    return bool(parts.scheme) and bool(parts.netloc or parts.path)


def _resolve(root: dict, ref: str) -> Any:
    """A same-document JSON Pointer ``$ref`` (``#/a/b``), the only kind either uses."""
    assert ref.startswith("#/"), f"only same-document refs are implemented: {ref!r}"
    node: Any = root
    for token in ref[2:].split("/"):
        node = node[unquote(token).replace("~1", "/").replace("~0", "~")]
    return node


def errors(node: dict, value: Any, root: dict, at: str = "$") -> list[str]:
    """Every way ``value`` breaks ``node`` (a schema inside ``root``); ``[]`` if none."""
    found: list[str] = []
    for key, rule in node.items():
        if key in ANNOTATIONS:
            continue
        if key == "$ref":
            found += errors(_resolve(root, rule), value, root, at)
        elif key == "type":
            types = [rule] if isinstance(rule, str) else rule
            if not any(_JSON_TYPES[t](value) for t in types):
                found.append(f"{at}: not of type {rule}")
        elif key == "required":
            if isinstance(value, dict):
                found += [f"{at}: missing {name!r}" for name in rule if name not in value]
        elif key == "properties":
            if isinstance(value, dict):
                for name, sub in rule.items():
                    if name in value:
                        found += errors(sub, value[name], root, f"{at}.{name}")
        elif key == "additionalProperties":
            if isinstance(value, dict):
                for name in (k for k in value if k not in node.get("properties", {})):
                    if rule is False:
                        found.append(f"{at}: unexpected {name!r}")
                    elif isinstance(rule, dict):
                        found += errors(rule, value[name], root, f"{at}.{name}")
        elif key == "items":
            if isinstance(value, list):
                for i, item in enumerate(value):
                    found += errors(rule, item, root, f"{at}[{i}]")
        elif key == "pattern":
            if isinstance(value, str) and not re.search(rule, value):
                found.append(f"{at}: {value!r} does not match {rule}")
        elif key == "minLength":
            if isinstance(value, str) and len(value) < rule:
                found.append(f"{at}: shorter than {rule}")
        elif key == "maxLength":
            if isinstance(value, str) and len(value) > rule:
                found.append(f"{at}: longer than {rule}")
        elif key == "enum":
            if value not in rule:
                found.append(f"{at}: {value!r} not in {rule}")
        elif key == "const":
            if value != rule:
                found.append(f"{at}: {value!r} is not {rule!r}")
        elif key == "not":
            if not errors(rule, value, root, at):
                found.append(f"{at}: matches a forbidden schema {rule}")
        elif key == "anyOf":
            branches = [errors(sub, value, root, at) for sub in rule]
            if all(branches):
                found.append(f"{at}: matches none of anyOf: {branches}")
        elif key == "allOf":
            for sub in rule:
                found += errors(sub, value, root, at)
        elif key == "format":
            if rule == "uri":
                if isinstance(value, str) and not is_uri(value):
                    found.append(f"{at}: {value!r} is not a uri")
            elif rule == "email":
                if isinstance(value, str) and not _EMAIL.match(value):
                    found.append(f"{at}: {value!r} is not an email address")
            else:
                raise AssertionError(f"{at}: format {rule!r} is not implemented here")
        else:
            raise AssertionError(f"{at}: schema keyword {key!r} is not implemented here")
    return found
