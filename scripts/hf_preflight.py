#!/usr/bin/env python3
"""Offline, read-only validator for everything YazSes would put on the Hugging Face Hub.

``huggingface/manifest.json`` lists, per destination, the exact files that may ever be
uploaded. This script proves that list is safe and self-consistent *before* the one
workflow that can publish (``.github/workflows/huggingface-publish.yml``) is allowed to
use it. It never talks to the network and it cannot publish: it does not import
``huggingface_hub`` at all, and ``tests/test_hf_preflight.py`` asserts that.

    uv run python scripts/hf_preflight.py                       # validate everything
    uv run python scripts/hf_preflight.py --print-plan          # also list file -> repo
    uv run python scripts/hf_preflight.py --select showcase --require-approved
    uv run python scripts/hf_preflight.py --select showcase --require-approved \\
        --stage-dir "$RUNNER_TEMP/hf-stage"                     # copy ONLY the allowlist

What it checks, per selected destination (every failure is one precise line, and the
exit status is 1 if there is any):

* manifest schema, unknown keys, duplicate keys, unique repo ids and publisher names;
* every allowlist entry matches a real file, nothing is a symlink;
* no forbidden path segment (the private manuscript, design and strategy trees, agent
  config, VCS and CI directories), no dotfile, no PDF, no audio or video unless it is a
  tiny synthetic fixture the manifest names explicitly, no key or database file, and no
  suffix outside a default-deny list;
* per-file and per-destination size limits;
* no secret, token, private key, or home-directory path inside any file (the match is
  never printed);
* Space and Dataset card front matter (valid YAML, required keys, ``app_file`` and
  ``configs`` pointing at files that will be uploaded);
* every local reference in ``index.html``/CSS/Markdown resolves to a file that is in the
  upload set (not merely on disk), no root-absolute, ``file:``, ``http:`` or
  localhost links, and in-page ``#anchors`` exist;
* the benchmark exporter's ``--check`` is current (a read-only subprocess);
* with ``--require-approved``: every selected destination is ``owner_approved`` and
  ``status == "live"``.

Exit status: 0 clean, 1 validation failures, 2 the manifest could not be read or the
command line was wrong.
"""

from __future__ import annotations

import argparse
import html.parser
import ipaddress
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "huggingface" / "manifest.json"

# --- policy constants -------------------------------------------------------------
# These live in code, not in the manifest, so editing the manifest can never widen them.

#: Every uploadable directory lives under this prefix of the repository.
UPLOAD_ROOT = "huggingface"
#: Under UPLOAD_ROOT, these are reference copy and are never uploaded.
NEVER_UPLOAD = ("huggingface/profile",)
#: A path segment that can never appear in an uploaded path, or in a source directory.
FORBIDDEN_SEGMENTS = frozenset(
    {
        "paper",
        "design",
        "strategy",
        ".claude",
        ".git",
        ".github",
        ".venv",
        "node_modules",
        "__pycache__",
        "secrets",
        "credentials",
    }
)
AUDIO_SUFFIXES = frozenset({".wav", ".flac", ".mp3", ".ogg", ".m4a", ".opus", ".aac", ".aiff"})
#: Video containers can carry speech too, so they are held to the audio rule.
VIDEO_SUFFIXES = frozenset({".mp4", ".webm", ".mkv", ".mov", ".avi"})
FORBIDDEN_SUFFIXES = frozenset(
    {
        ".pdf",
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".crt",
        ".db",
        ".sqlite",
        ".pyc",
        ".env",
    }
)
#: Default-deny: a suffix not listed here cannot be uploaded.
ALLOWED_SUFFIXES = frozenset(
    {
        ".md", ".html", ".css", ".js", ".json", ".csv", ".txt", ".py", ".yml", ".yaml",
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".avif",
        ".woff", ".woff2", ".ttf",
    }
)  # fmt: skip
#: Exact file names that are allowed although they have no suffix. Deliberately a single
#: name: the benchmark dataset card tells users to run ``sha256sum -c SHA256SUMS``.
ALLOWED_BASENAMES = frozenset({"SHA256SUMS"})
TEXT_SUFFIXES = frozenset(
    {".md", ".html", ".css", ".js", ".json", ".csv", ".txt", ".py", ".yml", ".yaml", ".svg"}
)
#: The Hub validates a card's ``short_description`` at 60 characters and refuses the push.
MAX_SHORT_DESCRIPTION = 60
#: A manifest may lower a per-file limit but never raise it past this.
HARD_MAX_FILE_BYTES = 25 * 1024 * 1024
HARD_MAX_TOTAL_BYTES = 100 * 1024 * 1024
#: A synthetic audio fixture must be tiny.
MAX_AUDIO_FIXTURE_BYTES = 256 * 1024
#: Hub limit stated by huggingface_hub for a collection item note.
MAX_NOTE_CHARS = 500
#: Conservative: the Hub web form caps a collection description at 150 characters. This
#: is not documented in huggingface_hub, so it is held as a deliberate safety margin.
MAX_COLLECTION_DESCRIPTION_CHARS = 150

REPO_TYPES = ("space", "dataset", "model")
STATUSES = ("planned", "live")
SPACE_SDKS = ("static", "gradio", "streamlit", "docker")
ITEM_TYPES = ("model", "dataset", "space", "paper")

_REPO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_PUBLISHER = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

TOP_KEYS = {"schema_version", "_comment", "oidc_publisher", "destinations", "collection"}
DEST_REQUIRED = {
    "repo_id", "repo_type", "url", "source_dir", "files", "status", "owner_approved",
    "publisher", "delete_remote_files", "max_file_bytes", "required_card_keys",
}  # fmt: skip
DEST_OPTIONAL = {"export_check", "audio_fixtures", "card_only"}
COLLECTION_KEYS = {"owner", "owner_approved", "title", "description", "private", "items"}
ITEM_REQUIRED = {"type", "id", "status", "url", "destination", "note", "evidence"}
PUBLISHER_KEYS = {"provider", "repository", "branch", "workflow", "environment", "docs"}

# (label, compiled bytes regex). Matches are NEVER echoed, only file:line and the label.
LEAK_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("Hugging Face token", re.compile(rb"hf_[A-Za-z0-9]{20,}")),
    ("GitHub token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("GitHub fine-grained token", re.compile(rb"github_pat_[A-Za-z0-9_]{20,}")),
    ("sk- style API key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}")),
    ("AWS access key id", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(rb"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("private key block", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "bearer credential",
        re.compile(rb"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]{16,}"),
    ),
    (
        "secret assignment",
        re.compile(
            rb"(?i)\b(?:HF_TOKEN|HUGGING_?FACE_HUB_TOKEN|API_KEY|PASSWORD|SECRET)"
            rb"\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"
        ),
    ),
    (
        "home-directory path",
        re.compile(
            rb"(?:/home|/Users)/(?!user\b|username\b|you\b|yourname\b|name\b|runner\b|yazses\b)"
            rb"[A-Za-z_][A-Za-z0-9._-]*/"
        ),
    ),
    (
        "Windows user path",
        re.compile(rb"[A-Za-z]:\\Users\\(?!user\b|username\b|you\b)[A-Za-z_][^\\\s]*\\"),
    ),
    ("work or legacy mailbox", re.compile(rb"@e4company\.com|@(?:[a-z0-9-]+\.)?unibo\.it")),
)


# --- results ---------------------------------------------------------------------


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


class ManifestError(Exception):
    """The manifest could not be read as strict JSON."""


def _no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ManifestError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def load_manifest(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{path} must contain a JSON object")
    return data


# --- derived names (also used by the workflow tests) --------------------------------


def oidc_resource(dest: dict) -> str:
    """The `resource` a Trusted Publisher token is scoped to (HF docs, trusted-publishers)."""
    repo_type, repo_id = dest["repo_type"], dest["repo_id"]
    return {"space": f"spaces/{repo_id}", "dataset": f"datasets/{repo_id}"}.get(
        repo_type, repo_id
    )


def hub_url(repo_type: str, repo_id: str) -> str:
    prefix = {"space": "spaces/", "dataset": "datasets/", "paper": "papers/"}.get(repo_type, "")
    return f"https://huggingface.co/{prefix}{repo_id}"


# --- schema ----------------------------------------------------------------------


def _is_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_relative_path(where: str, value: str, report: Report, *, allow_glob: bool) -> bool:
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        report.error(where, f"{value!r} must be a relative POSIX path")
        return False
    parts = value.split("/")
    if value.endswith("/"):
        parts = parts[:-1]
    if not parts or any(p in ("", ".", "..") for p in parts):
        report.error(where, f"{value!r} has an empty, '.' or '..' segment")
        return False
    if not allow_glob and any(ch in value for ch in "*?["):
        report.error(where, f"{value!r} may not contain wildcards")
        return False
    return True


def validate_schema(manifest: dict, report: Report) -> None:
    for key in manifest:
        if key not in TOP_KEYS:
            report.error("manifest", f"unknown top-level key {key!r}")
    if manifest.get("schema_version") != 1:
        report.error("manifest", "schema_version must be 1")

    publisher = manifest.get("oidc_publisher")
    if not isinstance(publisher, dict):
        report.error("oidc_publisher", "missing or not an object")
    else:
        for key in publisher:
            if key not in PUBLISHER_KEYS:
                report.error("oidc_publisher", f"unknown key {key!r}")
        for key in ("provider", "repository", "branch", "workflow", "environment"):
            if not _is_str(publisher.get(key)):
                report.error("oidc_publisher", f"{key} must be a non-empty string")
        if publisher.get("provider") != "github-actions":
            report.error("oidc_publisher", "provider must be 'github-actions'")

    dests = manifest.get("destinations")
    if not isinstance(dests, dict) or not dests:
        report.error("destinations", "must be a non-empty object")
        dests = {}

    seen_repo: dict[str, str] = {}
    seen_pub: dict[str, str] = {}
    source_dirs: dict[str, str] = {}
    for name, dest in dests.items():
        where = f"destination {name}"
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
            report.error(where, "name must be lowercase letters, digits and hyphens")
        if not isinstance(dest, dict):
            report.error(where, "must be an object")
            continue
        missing = DEST_REQUIRED - dest.keys()
        if missing:
            report.error(where, f"missing keys {sorted(missing)}")
        unknown = dest.keys() - DEST_REQUIRED - DEST_OPTIONAL
        if unknown:
            report.error(where, f"unknown keys {sorted(unknown)}")
        _validate_destination_fields(name, dest, report, seen_repo, seen_pub, source_dirs)

    dirs = sorted(source_dirs.items())
    for i, (a, name_a) in enumerate(dirs):
        for b, name_b in dirs[i + 1 :]:
            if b == a or b.startswith(a + "/"):
                report.error(
                    "destinations",
                    f"{name_a} ({a}) and {name_b} ({b}) overlap; source directories must be disjoint",
                )

    collection = manifest.get("collection")
    if collection is not None:
        _validate_collection(collection, dests, report)
    else:
        report.error("collection", "missing")


def _validate_destination_fields(
    name: str,
    dest: dict,
    report: Report,
    seen_repo: dict[str, str],
    seen_pub: dict[str, str],
    source_dirs: dict[str, str],
) -> None:
    where = f"destination {name}"
    repo_id = dest.get("repo_id")
    if not isinstance(repo_id, str) or not _REPO_ID.match(repo_id):
        report.error(where, f"repo_id {repo_id!r} must look like 'owner/name'")
    elif repo_id.lower() in seen_repo:
        report.error(where, f"repo_id {repo_id!r} duplicates destination {seen_repo[repo_id.lower()]}")
    else:
        seen_repo[repo_id.lower()] = name

    if dest.get("repo_type") not in REPO_TYPES:
        report.error(where, f"repo_type must be one of {REPO_TYPES}")
    if dest.get("status") not in STATUSES:
        report.error(where, f"status must be one of {STATUSES}")
    if not isinstance(dest.get("owner_approved"), bool):
        report.error(where, "owner_approved must be true or false")
    if dest.get("delete_remote_files") is not False:
        report.error(
            where,
            "delete_remote_files must be false: the publish workflow never deletes remote files",
        )

    publisher = dest.get("publisher")
    if not isinstance(publisher, str) or not _PUBLISHER.match(publisher):
        report.error(where, "publisher must be a lowercase slug (3-64 chars)")
    elif publisher in seen_pub:
        report.error(where, f"publisher {publisher!r} is shared with {seen_pub[publisher]}; each destination needs its own")
    else:
        seen_pub[publisher] = name

    cap = dest.get("max_file_bytes")
    if not isinstance(cap, int) or isinstance(cap, bool) or not 0 < cap <= HARD_MAX_FILE_BYTES:
        report.error(where, f"max_file_bytes must be an integer in 1..{HARD_MAX_FILE_BYTES}")

    keys = dest.get("required_card_keys")
    if not isinstance(keys, list) or not keys or not all(_is_str(k) for k in keys):
        report.error(where, "required_card_keys must be a non-empty list of strings")

    url, status = dest.get("url"), dest.get("status")
    if status == "planned" and url is not None:
        report.error(where, "a planned destination must have url null (a URL is a claim; verify first)")
    if status == "live":
        expected = hub_url(str(dest.get("repo_type")), str(repo_id))
        if url != expected:
            report.error(where, f"a live destination's url must be {expected!r}, got {url!r}")

    src = dest.get("source_dir")
    if not isinstance(src, str) or not _check_relative_path(where, str(src), report, allow_glob=False):
        report.error(where, "source_dir must be a relative path")
    else:
        src = src.rstrip("/")
        segments = src.split("/")
        if not src.startswith(UPLOAD_ROOT + "/"):
            report.error(where, f"source_dir {src!r} must be a subdirectory of {UPLOAD_ROOT}/")
        bad = FORBIDDEN_SEGMENTS.intersection(segments)
        if bad:
            report.error(where, f"source_dir contains forbidden segment(s) {sorted(bad)}")
        for blocked in NEVER_UPLOAD:
            if src == blocked or src.startswith(blocked + "/"):
                report.error(where, f"source_dir {src!r} is reference copy and is never uploaded")
        source_dirs[src] = name

    files = dest.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, str) for f in files):
        report.error(where, "files must be a non-empty list of strings")
    else:
        for entry in files:
            _check_relative_path(f"{where} files", entry, report, allow_glob=True)

    card_only = dest.get("card_only")
    if card_only is not None:
        if card_only is not True or dest.get("repo_type") != "space" or not str(repo_id).endswith("/README"):
            report.error(where, "card_only may only be true, on a Space whose repo_id is '<org>/README'")

    check = dest.get("export_check")
    if check is not None:
        ok = (
            isinstance(check, list)
            and len(check) == 2
            and isinstance(check[0], str)
            and re.match(r"^scripts/[A-Za-z0-9_.-]+\.py$", check[0])
            and check[1] == "--check"
        )
        if not ok:
            report.error(where, 'export_check must be ["scripts/<name>.py", "--check"]')

    fixtures = dest.get("audio_fixtures", [])
    if not isinstance(fixtures, list):
        report.error(where, "audio_fixtures must be a list")
    else:
        for fx in fixtures:
            if not (
                isinstance(fx, dict)
                and set(fx) == {"path", "synthetic"}
                and isinstance(fx["path"], str)
                and fx["synthetic"] is True
            ):
                report.error(
                    where,
                    'each audio fixture must be {"path": ..., "synthetic": true}; '
                    "real recordings are never allowed",
                )


def _validate_collection(collection: object, dests: dict, report: Report) -> None:
    where = "collection"
    if not isinstance(collection, dict):
        report.error(where, "must be an object")
        return
    for key in collection:
        if key not in COLLECTION_KEYS:
            report.error(where, f"unknown key {key!r}")
    owner = collection.get("owner")
    if not isinstance(owner, str) or not _OWNER.match(owner):
        report.error(where, "owner must be a Hub user or organisation name")
    if not isinstance(collection.get("owner_approved"), bool):
        report.error(where, "owner_approved must be true or false")
    if not _is_str(collection.get("title")):
        report.error(where, "title must be a non-empty string")
    desc = collection.get("description")
    if not _is_str(desc):
        report.error(where, "description must be a non-empty string")
    elif len(desc) > MAX_COLLECTION_DESCRIPTION_CHARS:
        report.error(
            where,
            f"description is {len(desc)} characters; keep it within "
            f"{MAX_COLLECTION_DESCRIPTION_CHARS} (conservative Hub form limit)",
        )
    if not isinstance(collection.get("private", False), bool):
        report.error(where, "private must be true or false")
    items = collection.get("items")
    if not isinstance(items, list) or not items:
        report.error(where, "items must be a non-empty list")
        return
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        iw = f"collection item #{index + 1}"
        if not isinstance(item, dict):
            report.error(iw, "must be an object")
            continue
        missing = ITEM_REQUIRED - item.keys()
        unknown = item.keys() - ITEM_REQUIRED
        if missing:
            report.error(iw, f"missing keys {sorted(missing)}")
        if unknown:
            report.error(iw, f"unknown keys {sorted(unknown)}")
        itype, iid, status = item.get("type"), item.get("id"), item.get("status")
        if itype not in ITEM_TYPES:
            report.error(iw, f"type must be one of {ITEM_TYPES}")
        if not _is_str(iid):
            report.error(iw, "id must be a non-empty string")
            continue
        iw = f"collection item {iid}"
        key = (str(itype), str(iid).lower())
        if key in seen:
            report.error(iw, "duplicate item")
        seen.add(key)
        if status not in STATUSES:
            report.error(iw, f"status must be one of {STATUSES}")
        note = item.get("note")
        if not _is_str(note):
            report.error(iw, "note must be a non-empty string")
        elif len(note) > MAX_NOTE_CHARS:
            report.error(iw, f"note is {len(note)} characters; the Hub allows {MAX_NOTE_CHARS}")
        url = item.get("url")
        if status == "planned" and url is not None:
            report.error(iw, "a planned item must have url null (a URL is a claim; verify first)")
        if status == "live":
            expected = hub_url(str(itype), iid)
            if url != expected:
                report.error(iw, f"a live item's url must be {expected!r}, got {url!r}")
            if not _is_str(item.get("evidence")):
                report.error(iw, "a live item needs evidence (how its existence was verified)")
        dest_name = item.get("destination")
        if dest_name is not None:
            dest = dests.get(dest_name)
            if not isinstance(dest, dict):
                report.error(iw, f"destination {dest_name!r} is not in the manifest")
                continue
            if dest.get("repo_id") != iid or dest.get("repo_type") != itype:
                report.error(iw, f"does not match destination {dest_name} ({dest.get('repo_type')} {dest.get('repo_id')})")
            if status == "live" and dest.get("status") != "live":
                report.error(iw, f"is live but destination {dest_name} is {dest.get('status')}")


# --- selection -------------------------------------------------------------------


class SelectionError(Exception):
    pass


def select_destinations(manifest: dict, target: str, *, require_approved: bool) -> list[str]:
    """Resolve `--select`. `all-approved` is the publishable set; a named target must
    itself be publishable when `require_approved` is set."""
    dests = manifest["destinations"]
    if target == "all":
        names = sorted(dests)
    elif target == "all-approved":
        names = sorted(n for n, d in dests.items() if d["owner_approved"] is True and d["status"] == "live")
        if require_approved and not names:
            raise SelectionError(
                "no destination is both owner_approved and live; nothing to publish "
                "(edit huggingface/manifest.json in a reviewed commit to approve one)"
            )
    elif target in dests:
        names = [target]
    else:
        raise SelectionError(f"unknown destination {target!r}; choose one of {sorted(dests)}")
    if require_approved:
        for name in names:
            dest = dests[name]
            if dest["owner_approved"] is not True:
                raise SelectionError(
                    f"destination {name} has owner_approved=false; refusing to select it for publishing"
                )
            if dest["status"] != "live":
                raise SelectionError(
                    f"destination {name} has status={dest['status']}; the Hub repository must exist "
                    "and be set to live before publishing"
                )
    return names


# --- file resolution -------------------------------------------------------------


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def resolve_files(root: Path, name: str, dest: dict, report: Report) -> list[str]:
    """Allowlist -> sorted list of POSIX paths relative to source_dir. Reports problems."""
    where = f"destination {name}"
    source = root / dest["source_dir"]
    if source.is_symlink() or not source.is_dir():
        report.error(where, f"source_dir {dest['source_dir']} is not a directory in the working tree")
        return []
    found: set[str] = set()
    matched: set[str] = set()  # files matched by the entry currently being resolved

    def add_file(path: Path) -> None:
        rel = path.relative_to(source).as_posix()
        if path.is_symlink():
            report.error(where, f"{rel} is a symlink; links are never uploaded")
            return
        if path.is_file():
            found.add(rel)
            matched.add(rel)

    for entry in dest["files"]:
        matched.clear()
        errors_before = len(report.errors)
        if entry.endswith("/"):
            base = source / entry.rstrip("/")
            if base.is_symlink() or not base.is_dir():
                report.error(where, f"allowlisted directory {entry} does not exist")
                continue
            for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
                for d in list(dirnames):
                    if (Path(dirpath) / d).is_symlink():
                        report.error(where, f"{(Path(dirpath) / d).relative_to(source).as_posix()} is a symlinked directory")
                        dirnames.remove(d)
                for filename in filenames:
                    add_file(Path(dirpath) / filename)
        elif any(ch in entry for ch in "*?["):
            for path in sorted(source.glob(entry)):
                add_file(path)
        else:
            path = source / entry
            if not (path.is_file() or path.is_symlink()):
                report.error(where, f"allowlisted file {entry} does not exist under {dest['source_dir']}")
                continue
            add_file(path)
        if not matched and len(report.errors) == errors_before:
            report.error(where, f"allowlist entry {entry!r} matched no files")
    return sorted(found)


def unlisted_files(root: Path, dest: dict, listed: list[str]) -> list[str]:
    """Files sitting in source_dir that the allowlist does not cover (informational)."""
    source = root / dest["source_dir"]
    listed_set = set(listed)
    extra = []
    for path in sorted(source.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        if path.is_file() and path.relative_to(source).as_posix() not in listed_set:
            extra.append(path.relative_to(source).as_posix())
    return extra


# --- per-file checks -------------------------------------------------------------


def check_paths_and_sizes(
    root: Path, name: str, dest: dict, files: list[str], report: Report
) -> None:
    where = f"destination {name}"
    source = root / dest["source_dir"]
    cap = min(dest["max_file_bytes"], HARD_MAX_FILE_BYTES)
    fixtures = {fx["path"] for fx in dest.get("audio_fixtures", []) if isinstance(fx, dict)}
    for fixture in sorted(fixtures - set(files)):
        report.error(where, f"audio fixture {fixture} is not in the upload set")
    total = 0
    for rel in files:
        full = f"{dest['source_dir']}/{rel}"
        parts = rel.split("/")
        bad = FORBIDDEN_SEGMENTS.intersection(parts)
        if bad:
            report.error(where, f"{full}: forbidden path segment(s) {sorted(bad)}")
        if any(p.startswith(".") for p in parts):
            report.error(where, f"{full}: dotfiles are never uploaded")
        suffix = posixpath.splitext(parts[-1])[1].lower()
        size = (source / rel).stat().st_size
        total += size
        if suffix in AUDIO_SUFFIXES or suffix in VIDEO_SUFFIXES:
            if rel not in fixtures:
                report.error(
                    where,
                    f"{full}: audio/video is never uploaded unless the manifest names it as a "
                    "synthetic audio_fixture",
                )
            elif size > MAX_AUDIO_FIXTURE_BYTES:
                report.error(where, f"{full}: audio fixture is {size} bytes; limit {MAX_AUDIO_FIXTURE_BYTES}")
        elif suffix in FORBIDDEN_SUFFIXES or parts[-1].lower().startswith(".env"):
            report.error(where, f"{full}: files of type {suffix or parts[-1]!r} are never uploaded")
        elif suffix not in ALLOWED_SUFFIXES and parts[-1] not in ALLOWED_BASENAMES:
            report.error(where, f"{full}: suffix {suffix!r} is not in the upload allowlist")
        if size > cap:
            report.error(where, f"{full}: {size} bytes exceeds the {cap} byte limit")
    if total > HARD_MAX_TOTAL_BYTES:
        report.error(where, f"upload set is {total} bytes; limit {HARD_MAX_TOTAL_BYTES}")


def scan_for_leaks(root: Path, name: str, dest: dict, files: list[str], report: Report) -> None:
    source = root / dest["source_dir"]
    for rel in files:
        data = (source / rel).read_bytes()
        suffix = posixpath.splitext(rel)[1].lower()
        if suffix in TEXT_SUFFIXES:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                report.error(f"destination {name}", f"{dest['source_dir']}/{rel}: not valid UTF-8")
        for label, pattern in LEAK_PATTERNS:
            for match in pattern.finditer(data):
                line = data.count(b"\n", 0, match.start()) + 1
                report.error(
                    f"destination {name}",
                    f"{dest['source_dir']}/{rel}:{line}: {label} (value not shown)",
                )
                break  # one report per pattern per file is enough


# --- cards -----------------------------------------------------------------------


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of keeping the last."""


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)

_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


def parse_front_matter(text: str) -> dict:
    """Return the card's YAML front matter. Raises ValueError with a precise message."""
    match = _FRONT_MATTER.match(text.lstrip("﻿"))
    if not match:
        raise ValueError("no YAML front matter (the file must start with a '---' block)")
    try:
        data = yaml.load(match.group(1), Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"front matter is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("front matter must be a YAML mapping")
    return data


def _matches_any(rel_patterns: list[str], files: list[str]) -> list[str]:
    """Patterns (card data_files style) that match no uploaded file."""
    unmatched = []
    for pattern in rel_patterns:
        pattern = pattern[2:] if pattern.startswith("./") else pattern
        regex = _glob_to_regex(pattern)
        if not any(regex.match(f) for f in files):
            unmatched.append(pattern)
    return unmatched


def _data_file_patterns(value: object) -> list[str] | None:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    if isinstance(value, list) and all(isinstance(v, dict) and "path" in v for v in value):
        out = []
        for v in value:
            p = _data_file_patterns(v["path"])
            if p is None:
                return None
            out.extend(p)
        return out
    return None


def check_card(root: Path, name: str, dest: dict, files: list[str], report: Report) -> None:
    where = f"destination {name}"
    if "README.md" not in files:
        report.error(where, "README.md (the Hub card) must be in the upload set")
        return
    full = f"{dest['source_dir']}/README.md"
    text = (root / dest["source_dir"] / "README.md").read_text(encoding="utf-8")
    try:
        card = parse_front_matter(text)
    except ValueError as exc:
        report.error(where, f"{full}: {exc}")
        return
    for key in dest["required_card_keys"]:
        if card.get(key) in (None, "", [], {}):
            report.error(where, f"{full}: front matter is missing required key {key!r}")
    kind = dest["repo_type"]
    short = card.get("short_description")
    if short is not None and (not isinstance(short, str) or len(short) > MAX_SHORT_DESCRIPTION):
        # The Hub rejects the push ("Too big: expected string to have <=60 characters").
        report.error(
            where,
            f"{full}: short_description must be a string of at most {MAX_SHORT_DESCRIPTION} "
            f"characters (it is {len(short) if isinstance(short, str) else type(short).__name__})",
        )
    if kind == "space":
        if not _is_str(card.get("title")):
            report.error(where, f"{full}: Space card needs a non-empty 'title'")
        sdk = card.get("sdk")
        if sdk not in SPACE_SDKS:
            report.error(where, f"{full}: Space card 'sdk' must be one of {SPACE_SDKS}, got {sdk!r}")
        elif sdk == "static" and dest.get("card_only") is True:
            pass  # an organisation card: the Hub renders README.md alone, no page file needed
        elif sdk == "static":
            entry = card.get("app_file", "index.html")
            if entry not in files:
                report.error(where, f"{full}: static Space needs {entry!r} in the upload set")
        elif sdk in ("gradio", "streamlit"):
            app_file = card.get("app_file")
            if not _is_str(app_file):
                report.error(where, f"{full}: Space card needs 'app_file' for sdk {sdk}")
            elif app_file not in files:
                report.error(where, f"{full}: app_file {app_file!r} is not in the upload set")
        elif _is_str(card.get("app_file")) and card["app_file"] not in files:
            report.error(where, f"{full}: app_file {card['app_file']!r} is not in the upload set")
    elif kind == "dataset":
        license_value = card.get("license")
        if not (_is_str(license_value) or (isinstance(license_value, list) and license_value)):
            report.error(where, f"{full}: Dataset card needs a 'license'")
        configs = card.get("configs")
        if not isinstance(configs, list) or not configs:
            report.error(where, f"{full}: Dataset card needs a non-empty 'configs' list")
        else:
            for config in configs:
                if not isinstance(config, dict) or not _is_str(config.get("config_name")):
                    report.error(where, f"{full}: every config needs a 'config_name'")
                    continue
                cname = config["config_name"]
                data_files = config.get("data_files")
                patterns: list[str] | None
                if isinstance(data_files, dict):
                    patterns = []
                    for split in data_files.values():
                        got = _data_file_patterns(split)
                        patterns = None if (got is None or patterns is None) else patterns + got
                else:
                    patterns = _data_file_patterns(data_files)
                if not patterns:
                    report.error(where, f"{full}: config {cname!r} needs 'data_files'")
                    continue
                for missing in _matches_any(patterns, files):
                    report.error(
                        where,
                        f"{full}: config {cname!r} data_files {missing!r} matches no uploaded file",
                    )


# --- references ------------------------------------------------------------------

_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_CSS_URL = re.compile(r"""url\(\s*(['"]?)(?P<ref>[^)'"]+?)\1\s*\)""", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"""@import\s+(['"])(?P<ref>[^'"]+)\1""", re.IGNORECASE)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_URL_ATTRS = {"href", "src", "poster", "data", "xlink:href", "data-src"}


class _HtmlRefs(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, int]] = []
        self.ids: set[str] = set()
        self._style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line = self.getpos()[0]
        for key, value in attrs:
            if value is None:
                continue
            if key in ("id", "name"):
                self.ids.add(value)
            elif key in _URL_ATTRS:
                self.refs.append((value, line))
            elif key in ("srcset", "data-srcset"):
                for candidate in value.split(","):
                    token = candidate.strip().split(" ")[0]
                    if token:
                        self.refs.append((token, line))
            elif key == "style":
                self.refs.extend((m.group("ref"), line) for m in _CSS_URL.finditer(value))
        if tag == "style":
            self._style = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._style = False

    def handle_data(self, data: str) -> None:
        if self._style:
            line = self.getpos()[0]
            self.refs.extend((m.group("ref"), line) for m in _CSS_URL.finditer(data))


def _classify_external(ref: str) -> str | None:
    """Return an error message for a bad absolute URL, or None if it is fine."""
    parts = urlsplit(ref)
    scheme = parts.scheme.lower()
    if scheme in ("mailto", "tel"):
        return None
    if scheme == "data":
        return None
    if scheme not in ("http", "https"):
        return f"scheme {scheme}: is not allowed in a published page"
    if scheme == "http":
        return f"{ref} uses http; use https"
    host = (parts.hostname or "").lower()
    if not host or host in _LOCAL_HOSTS or host.endswith(".local") or host.endswith(".localhost"):
        return f"{ref} points at a local host"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if address.is_private or address.is_loopback or address.is_link_local:
        return f"{ref} points at a private address"
    return None


def resolve_reference(
    ref: str, base_file: str, files: set[str]
) -> tuple[str, str | None, str | None]:
    """Classify one reference found in `base_file` (a path relative to source_dir).

    Returns (kind, target_file, error) where kind is one of: skip, fragment, external,
    local. `error` is a message when the reference is broken.
    """
    ref = ref.strip()
    if not ref:
        return "skip", None, None
    if ref.startswith("#"):
        return "fragment", base_file, None
    if ref.startswith("//"):
        return "external", None, f"{ref} is protocol-relative; use https://"
    if _SCHEME.match(ref):
        return "external", None, _classify_external(ref)
    if ref.startswith("/"):
        return "local", None, f"{ref} is root-absolute; use a relative path so the page works from any base"
    parts = urlsplit(ref)
    path = unquote(parts.path)
    if not path:
        return "skip", None, None
    base_dir = posixpath.dirname(base_file)
    target = posixpath.normpath(posixpath.join(base_dir, path))
    if target == ".." or target.startswith("../"):
        return "local", None, f"{ref} escapes the upload directory"
    if path.endswith("/") or target in ("", "."):
        target = posixpath.join(target, "index.html") if target not in ("", ".") else "index.html"
    if target not in files:
        return "local", None, f"{ref} -> {target} is not in the upload set"
    return "local", target, None


def check_references(root: Path, name: str, dest: dict, files: list[str], report: Report) -> None:
    where = f"destination {name}"
    source = root / dest["source_dir"]
    fileset = set(files)
    ids: dict[str, set[str]] = {}
    html_refs: dict[str, list[tuple[str, int]]] = {}
    for rel in files:
        if rel.endswith((".html", ".htm")):
            parser = _HtmlRefs()
            parser.feed((source / rel).read_text(encoding="utf-8"))
            parser.close()
            ids[rel] = parser.ids
            html_refs[rel] = parser.refs

    def check(rel: str, ref: str, line: int, *, fragments: bool) -> None:
        full = f"{dest['source_dir']}/{rel}:{line}"
        kind, target, error = resolve_reference(ref, rel, fileset)
        if error:
            report.error(where, f"{full}: {error}")
            return
        fragment = urlsplit(ref.strip()).fragment
        if kind in ("fragment", "local") and fragment and target in ids and fragments:
            if unquote(fragment) not in ids[target]:
                report.error(where, f"{full}: #{fragment} does not exist in {target}")

    for rel, refs in html_refs.items():
        for ref, line in refs:
            check(rel, ref, line, fragments=True)

    for rel in files:
        text_suffix = posixpath.splitext(rel)[1].lower()
        if text_suffix == ".css":
            text = (source / rel).read_text(encoding="utf-8")
            for match in list(_CSS_URL.finditer(text)) + list(_CSS_IMPORT.finditer(text)):
                line = text.count("\n", 0, match.start()) + 1
                check(rel, match.group("ref"), line, fragments=False)
        elif text_suffix == ".md":
            _check_markdown(source, dest, rel, fileset, ids, where, report)


_MD_FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)
_MD_INLINE_CODE = re.compile(r"`[^`\n]*`")
_MD_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_MD_REF_DEF = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*<?(\S+?)>?(?:\s+.*)?$", re.MULTILINE)
_MD_HTML_ATTR = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_MD_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)


def _slug(heading: str) -> str:
    text = re.sub(r"[`*_]", "", heading).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return re.sub(r"\s", "-", text)


def _check_markdown(
    source: Path,
    dest: dict,
    rel: str,
    fileset: set[str],
    html_ids: dict[str, set[str]],
    where: str,
    report: Report,
) -> None:
    text = (source / rel).read_text(encoding="utf-8")
    body = _FRONT_MATTER.sub("", text.lstrip("﻿"), count=1)
    body = _MD_FENCE.sub("", body)
    anchors = {_slug(m.group(1)) for m in _MD_HEADING.finditer(body)}
    body = _MD_INLINE_CODE.sub("", body)
    candidates: list[tuple[str, int]] = []
    for regex in (_MD_LINK, _MD_REF_DEF, _MD_HTML_ATTR):
        for match in regex.finditer(body):
            candidates.append((match.group(1), body.count("\n", 0, match.start()) + 1))
    for ref, line in candidates:
        full = f"{dest['source_dir']}/{rel}"
        kind, target, error = resolve_reference(ref, rel, fileset)
        if error:
            report.error(where, f"{full}: {error}")
            continue
        fragment = urlsplit(ref.strip()).fragment
        if fragment and kind == "fragment" and unquote(fragment).lower() not in anchors:
            report.warn(where, f"{full}: #{fragment} matches no heading (card anchors are heading slugs)")
        elif fragment and kind == "local" and target in html_ids and unquote(fragment) not in html_ids[target]:
            report.error(where, f"{full}: #{fragment} does not exist in {target}")


# --- export check ----------------------------------------------------------------


def _clean_env() -> dict[str, str]:
    """The environment for the exporter's --check: no tokens, no network to the Hub."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(("HF_", "HUGGING", "GH_", "GITHUB_TOKEN"))
        and "TOKEN" not in k.upper()
        and "SECRET" not in k.upper()
    }
    env["HF_HUB_OFFLINE"] = "1"
    return env


def run_export_check(root: Path, name: str, dest: dict, report: Report) -> None:
    check = dest.get("export_check")
    if not check:
        return
    where = f"destination {name}"
    script = root / check[0]
    if not script.is_file():
        report.error(where, f"export script {check[0]} does not exist, so the export cannot be checked")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(script), check[1]],
            cwd=root,
            env=_clean_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        report.error(where, f"{check[0]} --check timed out after 300 s")
        return
    if result.returncode != 0:
        tail = " | ".join((result.stdout + result.stderr).strip().splitlines()[-5:])
        report.error(
            where,
            f"{check[0]} --check exited {result.returncode}: the exported data is stale. {tail}",
        )


# --- plan, staging ---------------------------------------------------------------


def format_plan(manifest: dict, names: list[str], resolved: dict[str, list[str]], root: Path) -> str:
    lines = ["Publish plan (dry run; nothing is uploaded by this script):"]
    for name in names:
        dest = manifest["destinations"][name]
        lines.append(
            f"- {name}: {dest['repo_type']} {dest['repo_id']}  "
            f"[status={dest['status']}, owner_approved={str(dest['owner_approved']).lower()}, "
            f"publisher={dest['publisher']}, oidc_resource={oidc_resource(dest)}]"
        )
        files = resolved.get(name, [])
        if not files:
            lines.append("    (no files resolved)")
        for rel in files:
            size = (root / dest["source_dir"] / rel).stat().st_size
            lines.append(f"    {dest['source_dir']}/{rel} -> {rel}  ({size} bytes)")
        lines.append("    remote files not listed above are left untouched (delete_remote_files=false)")
    return "\n".join(lines)


def stage(root: Path, stage_dir: Path, name: str, dest: dict, files: list[str]) -> Path:
    """Copy exactly the allowlisted files to stage_dir/<name>. Returns that directory."""
    stage_dir = stage_dir.resolve()
    root = root.resolve()
    forbidden_zone = root / UPLOAD_ROOT
    if stage_dir == root or stage_dir in root.parents or stage_dir == forbidden_zone or forbidden_zone in stage_dir.parents:
        raise SelectionError(f"stage directory {stage_dir} must be outside the repository's {UPLOAD_ROOT}/ tree")
    target = stage_dir / name
    if target.exists():
        shutil.rmtree(target)
    for rel in files:
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / dest["source_dir"] / rel, out)
    return target


# --- driver ----------------------------------------------------------------------


def validate_destination(
    root: Path, name: str, dest: dict, report: Report, *, run_export: bool
) -> list[str]:
    files = resolve_files(root, name, dest, report)
    if not files:
        return files
    check_paths_and_sizes(root, name, dest, files, report)
    scan_for_leaks(root, name, dest, files, report)
    check_card(root, name, dest, files, report)
    check_references(root, name, dest, files, report)
    for extra in unlisted_files(root, dest, files):
        report.warn(
            f"destination {name}",
            f"{dest['source_dir']}/{extra} is not allowlisted and will NOT be uploaded",
        )
    if run_export:
        run_export_check(root, name, dest, report)
    return files


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Offline, read-only validator for the Hugging Face publish manifest.",
        epilog="Exit status: 0 clean, 1 validation failures, 2 unreadable manifest or bad usage.",
    )
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root (default: this checkout)")
    p.add_argument("--select", default="all", help="a destination name, 'all', or 'all-approved'")
    p.add_argument("--require-approved", action="store_true",
                   help="refuse any selected destination that is not owner_approved and live")
    p.add_argument("--print-plan", action="store_true", help="list which files would go to which repo")
    p.add_argument("--skip-export-check", action="store_true",
                   help="do not run the benchmark exporter's --check")
    p.add_argument("--stage-dir", type=Path,
                   help="after a clean validation, copy exactly the allowlisted files to DIR/<name>")
    p.add_argument("--github-output", action="store_true",
                   help="append selected=<json list> to the file named by $GITHUB_OUTPUT")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"hf_preflight: ERROR: {exc}", file=sys.stderr)
        return 2

    report = Report()
    validate_schema(manifest, report)
    if report.errors:
        return _finish(report, 0)

    try:
        names = select_destinations(manifest, args.select, require_approved=args.require_approved)
    except SelectionError as exc:
        print(f"hf_preflight: ERROR: {exc}", file=sys.stderr)
        return 1

    resolved: dict[str, list[str]] = {}
    for name in names:
        resolved[name] = validate_destination(
            root, name, manifest["destinations"][name], report,
            run_export=not args.skip_export_check,
        )

    if args.print_plan:
        print(format_plan(manifest, names, resolved, root))

    if not report.errors and args.stage_dir:
        for name in names:
            target = stage(root, args.stage_dir, name, manifest["destinations"][name], resolved[name])
            print(f"staged {len(resolved[name])} file(s) for {name} in {target}")

    if not report.errors and args.github_output:
        out = os.environ.get("GITHUB_OUTPUT")
        if not out:
            print("hf_preflight: ERROR: --github-output needs $GITHUB_OUTPUT", file=sys.stderr)
            return 2
        with open(out, "a", encoding="utf-8") as handle:
            handle.write(f"selected={json.dumps(names)}\n")

    return _finish(report, len(names))


def _finish(report: Report, checked: int) -> int:
    for warning in report.warnings:
        print(f"WARNING {warning}", file=sys.stderr)
    if report.errors:
        for error in report.errors:
            print(f"FAIL {error}", file=sys.stderr)
        print(f"hf_preflight: {len(report.errors)} failure(s)", file=sys.stderr)
        return 1
    print(f"hf_preflight: OK ({checked} destination(s) checked, {len(report.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
