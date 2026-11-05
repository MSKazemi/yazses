"""Pure, offline checks for the model provenance manifest (issue #694).

This module is the logic behind ``scripts/check_model_manifest.py``. It imports only the
standard library, opens no socket, imports no Hugging Face package and loads no model, and
``tests/test_model_manifest.py`` asserts all three. Every function takes data in and returns
a list of one-line problems (empty means clean); the only I/O is reading the files a caller
names, and hashing a file the caller already has on disk.

What it checks:

* ``check_schema``: the manifest against ``design/hci-huggingface/model-manifest.schema.json``.
  There is no ``jsonschema`` dependency, so this is a small interpreter for the keywords that
  schema uses. It *refuses* any other keyword, so the schema can never silently stop
  constraining something.
* ``check_semantics``: rules a schema cannot say. Ids are unique, ``upstream_id`` resolves, the
  hash-status summary agrees with the artifacts, redistribution requires a stated and
  permissive licence, and every ``code_refs`` path is a real repository file that has that line.
* ``check_traceability``: every immutable revision, hash and Hub id in the manifest also appears
  in the human-readable inventory, so a value cannot be invented here without the inventory.
* ``verify_local_hashes``: recompute the sha256 of artifacts that are already on disk.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

#: Licence identifiers that forbid commercial use. A model under one of these is never
#: marked as redistributed by YazSes (checked in ``check_semantics``).
NON_COMMERCIAL_LICENSES = frozenset({"cc-by-nc-sa-4.0"})

_ANNOTATION_KEYWORDS = frozenset({"$schema", "$id", "title", "description", "$comment", "$defs"})
_SUPPORTED_KEYWORDS = _ANNOTATION_KEYWORDS | {
    "$ref",
    "type",
    "enum",
    "const",
    "pattern",
    "minLength",
    "minimum",
    "minItems",
    "maxItems",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "allOf",
    "if",
    "then",
    "else",
}


class SchemaError(ValueError):
    """The *schema* is wrong or uses a keyword this checker does not implement."""


# --- strict JSON ----------------------------------------------------------------------


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def loads_strict(text: str) -> Any:
    """``json.loads`` that rejects duplicate keys and the non-JSON ``NaN``/``Infinity``."""

    def _reject_constant(name: str) -> Any:
        raise ValueError(f"non-JSON constant {name}")

    return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)


# --- a small JSON Schema interpreter -----------------------------------------------------


def _type_ok(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "null":
        return value is None
    raise SchemaError(f"unknown type {name!r}")


@functools.lru_cache(maxsize=None)
def _compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile a schema ``pattern`` with JSON Schema (ECMA 262) semantics, not Python's.

    Python's ``$`` also matches just before a final newline, so ``^[0-9a-f]{64}$`` would accept
    a hash followed by ``\\n``; ``\\Z`` does not. Python's ``\\d`` and ``\\w`` are Unicode-aware
    (Arabic-Indic digits match ``\\d``); ``re.ASCII`` restores ``[0-9]`` and ``[A-Za-z0-9_]``.
    A pattern that does not compile is a defect in the *schema*, never a crash.
    """
    out: list[str] = []
    in_class = False
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\" and i + 1 < len(pattern):
            out.append(pattern[i : i + 2])
            i += 2
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        out.append("\\Z" if char == "$" and not in_class else char)
        i += 1
    try:
        return re.compile("".join(out), re.ASCII)
    except re.error as exc:
        raise SchemaError(f"invalid pattern {pattern!r}: {exc}") from exc


def _same(a: Any, b: Any) -> bool:
    """Equality that does not let ``True == 1`` through."""
    return type(a) is type(b) and a == b


def _resolve(ref: str, root: dict[str, Any]) -> Any:
    if not ref.startswith("#/"):
        raise SchemaError(f"only local $ref is supported, got {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise SchemaError(f"unresolvable $ref {ref!r}")
        node = node[part]
    return node


def validate(instance: Any, schema: Any, root: dict[str, Any], path: str = "$") -> list[str]:
    """Return one line per violation of ``schema`` by ``instance`` (empty list: valid)."""
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: not allowed here"]
    if not isinstance(schema, dict):
        raise SchemaError(f"schema at {path} is neither an object nor a boolean")
    unknown = set(schema) - _SUPPORTED_KEYWORDS
    if unknown:
        raise SchemaError(f"unsupported schema keyword(s) {sorted(unknown)} at {path}")

    errors: list[str] = []
    if "$ref" in schema:
        errors += validate(instance, _resolve(schema["$ref"], root), root, path)
    if "type" in schema and not _type_ok(instance, schema["type"]):
        # A wrong type makes every other keyword meaningless; report once and stop.
        return errors + [f"{path}: expected {schema['type']}, got {type(instance).__name__}"]
    if "const" in schema and not _same(instance, schema["const"]):
        errors.append(f"{path}: must be {schema['const']!r}, got {instance!r}")
    if "enum" in schema and not any(_same(instance, option) for option in schema["enum"]):
        errors.append(f"{path}: {instance!r} is not one of {schema['enum']!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']} character(s)")
        if "pattern" in schema and _compile_pattern(schema["pattern"]).search(instance) is None:
            errors.append(f"{path}: {instance!r} does not match {schema['pattern']!r}")
    if (
        "minimum" in schema
        and isinstance(instance, (int, float))
        and not isinstance(instance, bool)
        and instance < schema["minimum"]
    ):
        errors.append(f"{path}: {instance!r} is below the minimum {schema['minimum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} item(s), has {len(instance)}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} item(s), has {len(instance)}")
        if "items" in schema:
            for index, item in enumerate(instance):
                errors += validate(item, schema["items"], root, f"{path}[{index}]")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required field {key!r}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in instance:
                errors += validate(instance[key], sub, root, f"{path}.{key}")
        extra = schema.get("additionalProperties", True)
        if extra is not True:
            for key in instance:
                if key not in props:
                    errors += (
                        [f"{path}: unexpected field {key!r}"]
                        if extra is False
                        else validate(instance[key], extra, root, f"{path}.{key}")
                    )

    for sub in schema.get("allOf", []):
        errors += validate(instance, sub, root, path)
    if "if" in schema:
        condition_holds = not validate(instance, schema["if"], root, path)
        branch = schema.get("then") if condition_holds else schema.get("else")
        if branch is not None:
            errors += validate(instance, branch, root, path)
    return errors


def check_schema(manifest: Any, schema: dict[str, Any]) -> list[str]:
    """Violations of the JSON Schema. Raises ``SchemaError`` if the schema itself is unusable."""
    return validate(manifest, schema, schema)


# --- rules a schema cannot express --------------------------------------------------------


def _models(manifest: Any) -> list[tuple[int, dict[str, Any]]]:
    raw = manifest.get("models") if isinstance(manifest, dict) else None
    if not isinstance(raw, list):
        return []
    return [(i, m) for i, m in enumerate(raw) if isinstance(m, dict)]


def _is_plain_relative(rel: str) -> bool:
    """True if ``rel`` is a non-empty relative path made of ordinary names on every platform.

    Judged with both the POSIX and the Windows rules, whatever OS this runs on, so a manifest
    that is clean on Linux cannot hide a path that leaves the root on Windows: a drive
    (``C:x`` is drive-*relative*: it joins to ``C:`` plus that drive's current directory),
    a UNC or rooted path, a backslash, a ``..`` component, or a NUL byte.
    """
    if not rel or "\x00" in rel or "\\" in rel:
        return False
    posix, windows = PurePosixPath(rel), PureWindowsPath(rel)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root:
        return False
    return bool(posix.parts) and ".." not in posix.parts and ".." not in windows.parts


def _safe_repo_file(repo_root: Path, rel: str) -> Path | None:
    """Resolve ``rel`` under ``repo_root`` or return None if it is absolute, escapes, or is no file."""
    if not _is_plain_relative(rel):
        return None
    target = (repo_root / Path(*PurePosixPath(rel).parts)).resolve()
    if repo_root.resolve() not in target.parents or not target.is_file():
        return None
    return target


def check_semantics(manifest: Any, repo_root: Path | None = None) -> list[str]:
    """Cross-field and cross-entry rules. Pass ``repo_root`` to also resolve ``code_refs``."""
    errors: list[str] = []
    models = _models(manifest)
    line_counts: dict[Path, int] = {}  # one read per file per call

    source_document = manifest.get("source_document") if isinstance(manifest, dict) else None
    if (
        repo_root is not None
        and isinstance(source_document, str)
        and _safe_repo_file(repo_root, source_document) is None
    ):
        errors.append(f"source_document: {source_document!r} is not a file inside the repository")

    seen: dict[str, int] = {}
    for index, model in models:
        ident = model.get("id")
        if isinstance(ident, str):
            if ident in seen:
                errors.append(f"models[{index}].id: duplicate id {ident!r} (first at models[{seen[ident]}])")
            else:
                seen[ident] = index

    for index, model in models:
        where = f"models[{index}]"
        upstream = model.get("upstream_id")
        if isinstance(upstream, str):
            if upstream == model.get("id"):
                errors.append(f"{where}.upstream_id: an entry cannot be its own upstream")
            elif upstream not in seen:
                errors.append(f"{where}.upstream_id: {upstream!r} is not the id of any entry")

        if model.get("redistributed_by_yazses") is True:
            lic = model.get("license")
            lic = lic if isinstance(lic, dict) else {}
            if lic.get("status") != "stated":
                errors.append(f"{where}: redistributed_by_yazses needs a stated licence")
            elif lic.get("id") in NON_COMMERCIAL_LICENSES:
                errors.append(f"{where}: redistributed_by_yazses with non-commercial licence {lic.get('id')!r}")
            if model.get("status") in ("candidate-not-used", "benchmarked-only"):
                errors.append(f"{where}: a {model.get('status')} model must not be redistributed")

        artifacts = model.get("artifacts")
        summary = model.get("artifact_hashes_status")
        if isinstance(artifacts, list) and artifacts:
            unknown = [
                a for a in artifacts if isinstance(a, dict) and a.get("sha256_status") == "unknown"
            ]
            if summary == "recorded" and unknown:
                errors.append(f"{where}.artifact_hashes_status: 'recorded' but an artifact has no sha256")
            if summary == "partial" and not unknown:
                errors.append(f"{where}.artifact_hashes_status: 'partial' but every artifact has a sha256")

        refs = model.get("code_refs")
        if repo_root is not None and isinstance(refs, list):
            for r_index, ref in enumerate(refs):
                if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                    continue
                target = _safe_repo_file(repo_root, ref["path"])
                ref_where = f"{where}.code_refs[{r_index}]"
                if target is None:
                    errors.append(f"{ref_where}: {ref['path']!r} is not a file inside the repository")
                    continue
                line = ref.get("line")
                if isinstance(line, int) and not isinstance(line, bool):
                    if target not in line_counts:
                        with target.open("rb") as handle:
                            line_counts[target] = sum(1 for _ in handle)
                    count = line_counts[target]
                    if line > count:
                        errors.append(f"{ref_where}: line {line} is past the end of {ref['path']} ({count} lines)")
    return errors


# --- traceability to the human-readable inventory ------------------------------------------


def _traceable_values(manifest: Any) -> Iterable[tuple[str, str]]:
    for index, model in _models(manifest):
        where = f"models[{index}]"
        source = model.get("source")
        if isinstance(source, dict):
            if source.get("kind") == "huggingface" and isinstance(source.get("location"), str):
                yield f"{where}.source.location", source["location"]
            if isinstance(source.get("requested_as"), str):
                yield f"{where}.source.requested_as", source["requested_as"]
        revision = model.get("revision")
        # Every known revision, not only a git commit: a tag, a versioned path or a package
        # version is a claim about what the inventory read, and is as inventable as a commit.
        if isinstance(revision, dict) and revision.get("kind") != "unknown":
            if isinstance(revision.get("value"), str):
                yield f"{where}.revision.value", revision["value"]
        artifacts = model.get("artifacts")
        for a_index, artifact in enumerate(artifacts if isinstance(artifacts, list) else []):
            if not isinstance(artifact, dict):
                continue
            for key in ("sha256", "md5_etag"):
                if isinstance(artifact.get(key), str):
                    yield f"{where}.artifacts[{a_index}].{key}", artifact[key]


def check_traceability(manifest: Any, inventory_text: str) -> list[str]:
    """Every Hub id, commit sha and hash in the manifest must be quoted in the inventory."""
    haystack = inventory_text.lower()
    return [
        f"{where}: {value!r} does not appear in the inventory document"
        for where, value in _traceable_values(manifest)
        if not _quoted(value.lower(), haystack, hub_id=".source." in where)
    ]


def _quoted(value: str, haystack: str, *, hub_id: bool) -> bool:
    """Is ``value`` in ``haystack`` as a whole token, not merely as a prefix or tail of another?

    A bare substring test accepts ``Systran/faster-whisper-tiny`` because the inventory quotes
    ``Systran/faster-whisper-tiny.en``. A Hub id may not continue into a longer id or path
    (``-x``, ``.en``, ``/x``) nor sit at the end of one; any other value (hash, tag, versioned
    path, which may sit inside a URL) only may not be glued to word characters or ``-``.
    """
    if hub_id:
        pattern = r"(?<![\w./-])" + re.escape(value) + r"(?![\w-]|\.\w|/\w)"
    else:
        pattern = r"(?<![\w-])" + re.escape(value) + r"(?![\w-])"
    return re.search(pattern, haystack, re.ASCII) is not None


# --- local hashes -------------------------------------------------------------------------


@dataclass
class HashReport:
    """Outcome of ``verify_local_hashes``: ``errors`` are failures, ``skipped`` are not on disk."""

    errors: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def verify_local_hashes(manifest: Any, artifact_root: Path) -> HashReport:
    """Recompute sha256 (and size) for each artifact that names a ``relative_path`` and a hash.

    A file that is not under ``artifact_root`` is reported in ``skipped``, never as an error:
    most models are not on the machine running the check, and nothing is downloaded to fix that.
    """
    report = HashReport()
    for index, model in _models(manifest):
        artifacts = model.get("artifacts")
        for a_index, artifact in enumerate(artifacts if isinstance(artifacts, list) else []):
            if not isinstance(artifact, dict):
                continue
            rel, expected = artifact.get("relative_path"), artifact.get("sha256")
            if not isinstance(rel, str) or not isinstance(expected, str):
                continue
            where = f"models[{index}].artifacts[{a_index}]"
            if not _is_plain_relative(rel):
                report.errors.append(f"{where}.relative_path: {rel!r} escapes the artifact root")
                continue
            target = artifact_root / Path(*PurePosixPath(rel).parts)
            if not target.is_file():
                report.skipped.append(f"{where}: {rel} is not under the artifact root")
                continue
            # Symlinks are followed on purpose: a Hugging Face snapshot directory is made of
            # links into ../../blobs, so containment of the *resolved* path would reject the
            # documented use. The path named by the manifest is what is confined (above).
            try:
                actual, size = _sha256_file(target)
            except OSError as exc:
                report.errors.append(f"{where}: cannot read {rel}: {exc.strerror or exc}")
                continue
            if actual != expected:
                report.errors.append(f"{where}: sha256 of {rel} is {actual}, manifest says {expected}")
            elif isinstance(artifact.get("size_bytes"), int) and artifact["size_bytes"] != size:
                report.errors.append(f"{where}: {rel} is {size} bytes, manifest says {artifact['size_bytes']}")
            else:
                report.checked.append(f"{where}: {rel}")
    return report


def check_all(
    manifest: Any,
    schema: dict[str, Any],
    *,
    repo_root: Path | None = None,
    inventory_text: str | None = None,
) -> list[str]:
    """Schema, then semantics, then traceability. Semantics are skipped if the schema fails
    (their messages would be noise about a document that is not the right shape)."""
    errors = check_schema(manifest, schema)
    if errors:
        return errors
    errors += check_semantics(manifest, repo_root)
    if inventory_text is not None:
        errors += check_traceability(manifest, inventory_text)
    return errors
