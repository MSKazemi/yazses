"""XR privacy guards: bounded retention, log redaction, persistence policy, zero egress."""
from __future__ import annotations

import ast
import copy
import gc
import math
import pickle
import re
import weakref
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

import yazses.xr
from yazses.xr.privacy import (
    EGRESS,
    PersistencePolicy,
    SampleRetention,
    confidence_bucket,
    may_persist,
    redact_for_log,
)
from yazses.xr.types import Ray, RaySource, Vec3, XrSample

# Distinctive coordinates: no digit pattern here may appear in any log-safe rendering.
_ORIGIN = Vec3(0.123456, 1.654321, -0.987654)
_DIRECTION = Vec3(0.0, 0.0, -1.0)


def _sample(t: float, source: RaySource = RaySource.EYE, confidence: float = 0.9) -> XrSample:
    return XrSample(t, source, Ray(_ORIGIN, _DIRECTION), confidence)


# --- construction -----------------------------------------------------------


def test_defaults() -> None:
    buf = SampleRetention()
    assert buf.window_s == 2.0
    assert buf.max_samples == 240
    assert len(buf) == 0


@pytest.mark.parametrize("bad", [0, -1.0, float("nan"), float("inf"), True, "2", None])
def test_bad_window_rejected(bad: object) -> None:
    with pytest.raises(ValueError):
        SampleRetention(window_s=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0, -3, 1.5, True, "5", None])
def test_bad_max_samples_rejected(bad: object) -> None:
    with pytest.raises(ValueError):
        SampleRetention(max_samples=bad)  # type: ignore[arg-type]


def test_add_rejects_non_sample() -> None:
    with pytest.raises(TypeError):
        SampleRetention().add("not a sample")  # type: ignore[arg-type]


# --- age window -------------------------------------------------------------


def test_sample_exactly_window_old_is_kept_and_older_is_dropped() -> None:
    buf = SampleRetention(window_s=2.0)
    buf.add(_sample(10.0))
    assert len(buf.snapshot(12.0)) == 1  # age == window_s: kept
    assert len(buf.snapshot(12.000001)) == 0  # just older: gone


def test_add_prunes_old_samples_using_the_new_sample_time() -> None:
    buf = SampleRetention(window_s=2.0)
    buf.add(_sample(1.0))
    buf.add(_sample(2.0))
    buf.add(_sample(3.5))  # t=1.0 is now 2.5 s old
    assert [s.timestamp_s for s in buf.snapshot(3.5)] == [2.0, 3.5]


def test_prune_drops_everything_after_a_long_gap() -> None:
    buf = SampleRetention()
    for t in (1.0, 1.1, 1.2):
        buf.add(_sample(t))
    buf.prune(100.0)
    assert len(buf) == 0


def test_snapshot_prunes_in_place() -> None:
    buf = SampleRetention(window_s=1.0)
    buf.add(_sample(0.0))
    buf.snapshot(5.0)
    assert len(buf) == 0
    assert buf.snapshot(0.0) == ()  # the data is really gone, not hidden


def test_future_samples_are_kept() -> None:
    buf = SampleRetention(window_s=1.0)
    buf.add(_sample(10.0))
    assert len(buf.snapshot(5.0)) == 1  # now_s earlier than the sample: not "old"


def test_sample_stale_on_arrival_is_not_stored() -> None:
    buf = SampleRetention(window_s=2.0)
    buf.add(_sample(10.0))
    buf.add(_sample(7.9))  # 2.1 s older than the newest
    assert [s.timestamp_s for s in buf.snapshot(10.0)] == [10.0]


def test_late_sample_inside_window_is_slotted_in_order() -> None:
    buf = SampleRetention(window_s=5.0)
    for t in (1.0, 3.0, 4.0):
        buf.add(_sample(t))
    buf.add(_sample(2.0))
    assert [s.timestamp_s for s in buf.snapshot(4.0)] == [1.0, 2.0, 3.0, 4.0]


def test_equal_timestamps_keep_arrival_order() -> None:
    buf = SampleRetention()
    first, second = _sample(1.0, RaySource.EYE), _sample(1.0, RaySource.HEAD)
    buf.add(first)
    buf.add(second)
    assert buf.snapshot(1.0) == (first, second)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1", None])
def test_prune_rejects_bad_now(bad: object) -> None:
    with pytest.raises(ValueError):
        SampleRetention().prune(bad)  # type: ignore[arg-type]


# --- count cap --------------------------------------------------------------


def test_cap_evicts_oldest_first() -> None:
    buf = SampleRetention(window_s=100.0, max_samples=3)
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        buf.add(_sample(t))
    assert [s.timestamp_s for s in buf.snapshot(5.0)] == [3.0, 4.0, 5.0]
    assert len(buf) == 3


def test_cap_of_one_keeps_only_the_newest() -> None:
    buf = SampleRetention(window_s=100.0, max_samples=1)
    buf.add(_sample(1.0))
    buf.add(_sample(2.0))
    assert [s.timestamp_s for s in buf.snapshot(2.0)] == [2.0]


def test_cap_holds_exactly_at_the_limit() -> None:
    buf = SampleRetention(window_s=100.0, max_samples=3)
    for t in (1.0, 2.0, 3.0):
        buf.add(_sample(t))
    assert len(buf) == 3


def test_late_sample_older_than_all_is_the_one_evicted_at_the_cap() -> None:
    buf = SampleRetention(window_s=100.0, max_samples=2)
    buf.add(_sample(5.0))
    buf.add(_sample(6.0))
    buf.add(_sample(4.0))  # sorts oldest, so it is the eviction victim
    assert [s.timestamp_s for s in buf.snapshot(6.0)] == [5.0, 6.0]


@given(
    times=st.lists(st.floats(min_value=0, max_value=1000, allow_nan=False), max_size=60),
    cap=st.integers(min_value=1, max_value=10),
    window=st.floats(min_value=0.1, max_value=50),
)
def test_invariants_hold_for_any_stream(times: list[float], cap: int, window: float) -> None:
    buf = SampleRetention(window_s=window, max_samples=cap, max_future_s=math.inf)
    for t in times:
        buf.add(_sample(t))
        assert len(buf) <= cap
    snap = buf.snapshot(max(times, default=0.0))
    assert len(snap) <= cap
    stamps = [s.timestamp_s for s in snap]
    assert stamps == sorted(stamps)
    if stamps:
        assert stamps[-1] - stamps[0] <= window


# --- snapshot / clear -------------------------------------------------------


def test_snapshot_is_a_tuple_oldest_to_newest() -> None:
    buf = SampleRetention()
    a, b = _sample(1.0), _sample(1.5)
    buf.add(a)
    buf.add(b)
    snap = buf.snapshot(1.5)
    assert isinstance(snap, tuple)
    assert snap == (a, b)


def test_snapshot_is_detached_from_the_buffer() -> None:
    buf = SampleRetention()
    buf.add(_sample(1.0))
    snap = buf.snapshot(1.0)
    buf.clear()
    assert len(snap) == 1  # the caller's copy is theirs
    assert len(buf) == 0


def test_clear_empties_and_buffer_is_reusable() -> None:
    buf = SampleRetention()
    buf.add(_sample(1.0))
    buf.clear()
    assert len(buf) == 0
    assert buf.snapshot(1.0) == ()
    buf.add(_sample(2.0))
    assert len(buf) == 1


def test_clear_really_drops_references() -> None:
    buf = SampleRetention()
    sample = _sample(1.0)
    ref = weakref.ref(sample)
    buf.add(sample)
    del sample
    gc.collect()
    assert ref() is not None  # the buffer is what keeps it alive
    buf.clear()
    gc.collect()
    assert ref() is None


def test_prune_releases_expired_samples() -> None:
    buf = SampleRetention(window_s=1.0)
    sample = _sample(1.0)
    ref = weakref.ref(sample)
    buf.add(sample)
    del sample
    buf.prune(50.0)
    gc.collect()
    assert ref() is None


# --- hostile timestamps -----------------------------------------------------


def test_far_future_sample_cannot_poison_later_adds() -> None:
    """Reviewer reproducer: add(t=1e9) used to make every later add a silent no-op."""
    buf = SampleRetention()
    buf.add(_sample(1.0))
    with pytest.raises(ValueError, match="ahead"):
        buf.add(_sample(1e9))
    assert len(buf) == 1  # refused, nothing changed
    buf.add(_sample(2.0))
    assert [s.timestamp_s for s in buf.snapshot(2.0)] == [1.0, 2.0]


def test_first_sample_poison_is_removed_by_prune_with_the_real_clock() -> None:
    buf = SampleRetention()
    buf.add(_sample(1e9))  # empty buffer, no now_s: no reference to judge it by
    buf.prune(20.0)  # earlier-than-newest now: future-stamped entry is dropped
    assert len(buf) == 0
    buf.add(_sample(20.5))
    assert len(buf) == 1


def test_now_s_is_the_reference_when_given() -> None:
    buf = SampleRetention()
    with pytest.raises(ValueError, match="ahead"):
        buf.add(_sample(1e9), now_s=20.0)
    assert len(buf) == 0
    buf.add(_sample(24.9), now_s=20.0)  # within max_future_s of the caller's clock
    assert len(buf) == 1
    with pytest.raises(ValueError):
        buf.add(_sample(25.1), now_s=20.0)


def test_now_s_drives_the_age_check() -> None:
    buf = SampleRetention(window_s=2.0)
    buf.add(_sample(10.0), now_s=10.0)
    buf.add(_sample(10.5), now_s=20.0)  # the clock moved on: the old sample is aged out
    assert [s.timestamp_s for s in buf.snapshot(20.0)] == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1"])
def test_add_rejects_bad_now_s(bad: object) -> None:
    with pytest.raises(ValueError):
        SampleRetention().add(_sample(1.0), now_s=bad)  # type: ignore[arg-type]


def test_prune_keeps_samples_inside_the_future_allowance() -> None:
    buf = SampleRetention(window_s=1.0, max_future_s=5.0)
    buf.add(_sample(10.0))
    buf.prune(5.0)  # exactly max_future_s ahead: kept
    assert len(buf) == 1
    buf.prune(4.999)  # just beyond: dropped
    assert len(buf) == 0


@pytest.mark.parametrize("bad", [0, -1.0, float("nan"), True, "5", None])
def test_bad_max_future_rejected(bad: object) -> None:
    with pytest.raises(ValueError):
        SampleRetention(max_future_s=bad)  # type: ignore[arg-type]


def test_max_future_inf_disables_the_check() -> None:
    buf = SampleRetention(max_future_s=math.inf)
    buf.add(_sample(1.0))
    buf.add(_sample(1e9))
    assert len(buf) == 1  # the 1e9 sample is stored; the old one aged out


# --- no serialisation, no duplication ---------------------------------------


def test_pickle_is_refused_at_every_protocol() -> None:
    buf = SampleRetention()
    buf.add(_sample(1.0))
    for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
        with pytest.raises(TypeError, match="pickled"):
            pickle.dumps(buf, protocol=protocol)


def test_copy_and_deepcopy_are_refused() -> None:
    """Reviewer reproducer: deepcopy kept samples alive after the original's clear()."""
    buf = SampleRetention()
    buf.add(_sample(1.0))
    with pytest.raises(TypeError):
        copy.copy(buf)
    with pytest.raises(TypeError):
        copy.deepcopy(buf)
    assert len(buf) == 1


# --- log safety -------------------------------------------------------------


def test_repr_and_str_never_contain_coordinates() -> None:
    buf = SampleRetention()
    buf.add(_sample(7.0))
    for text in (repr(buf), str(buf), f"{buf}", "%s" % buf, f"{[buf]}"):
        for fragment in ("123456", "654321", "987654", "0.1234", "1.6543", "EYE", "eye"):
            assert fragment not in text
        assert "x=" not in text and "Vec3" not in text and "XrSample" not in text


def test_repr_reports_only_counts_and_limits() -> None:
    buf = SampleRetention(window_s=2.0, max_samples=240)
    buf.add(_sample(1.0))
    assert repr(buf) == "SampleRetention(count=1, window_s=2.0, max_samples=240)"
    assert str(buf) == repr(buf)


def test_buffer_has_no_instance_dict_to_leak_through_vars() -> None:
    assert not hasattr(SampleRetention(), "__dict__")


@pytest.mark.parametrize(
    ("confidence", "bucket"),
    [(1.0, "high"), (0.8, "high"), (0.7999, "medium"), (0.5, "medium"), (0.4999, "low"), (0.0, "low")],
)
def test_confidence_buckets(confidence: float, bucket: str) -> None:
    assert confidence_bucket(confidence) == bucket


@pytest.mark.parametrize("source", list(RaySource))
def test_redaction_has_source_and_bucket_only(source: RaySource) -> None:
    text = redact_for_log(_sample(123.456, source, confidence=0.93))
    assert text == f"xr-sample source={source.value} confidence=high"


def test_redaction_leaks_no_coordinate_timestamp_or_exact_confidence() -> None:
    text = redact_for_log(_sample(123.456, confidence=0.93))
    for fragment in ("123456", "654321", "987654", "123.456", "0.93", "93"):
        assert fragment not in text
    assert not any(ch.isdigit() for ch in text)


def test_redaction_rejects_non_sample() -> None:
    with pytest.raises(TypeError):
        redact_for_log(_ORIGIN)  # type: ignore[arg-type]


# --- persistence policy -----------------------------------------------------


def test_never_policy_refuses_even_with_consent() -> None:
    assert may_persist(PersistencePolicy.NEVER, research_consent=True) is False
    assert may_persist(PersistencePolicy.NEVER, research_consent=False) is False


def test_research_policy_needs_explicit_consent() -> None:
    assert may_persist(PersistencePolicy.RESEARCH_CONSENT_ONLY, research_consent=True) is True
    assert may_persist(PersistencePolicy.RESEARCH_CONSENT_ONLY, research_consent=False) is False


@pytest.mark.parametrize("not_consent", [1, "yes", "true", [True], object()])
def test_truthy_non_bool_is_not_consent(not_consent: object) -> None:
    assert may_persist(PersistencePolicy.RESEARCH_CONSENT_ONLY, research_consent=not_consent) is False  # type: ignore[arg-type]


def test_unknown_policy_fails_closed() -> None:
    assert may_persist("research_consent_only", research_consent=True) is False  # type: ignore[arg-type]
    assert may_persist(None, research_consent=True) is False  # type: ignore[arg-type]


def test_consent_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        may_persist(PersistencePolicy.RESEARCH_CONSENT_ONLY, True)  # type: ignore[misc]


def test_policy_members_are_closed() -> None:
    assert {p.name for p in PersistencePolicy} == {"NEVER", "RESEARCH_CONSENT_ONLY"}


# --- zero egress and no disk writes -----------------------------------------
#
# The scan reads real AST nodes (imports, calls, names), never prose or string
# literals, so a variable called ``http`` or the text "ssl" is not a finding. Same
# conservative stance as `tests/test_egress_inventory.py`: a false positive costs a
# look, a false negative costs the promise (no outbound path, no raw sample on disk).

#: Modules that open an outbound path, run another program, load code by name,
#: serialise to disk, or write temp files. Matched on the import's root name.
_BANNED_MODULES = frozenset(
    {
        # network / process
        "socket", "ssl", "socketserver", "selectors", "select", "asyncio", "subprocess",
        "multiprocessing", "ftplib", "smtplib", "poplib", "imaplib", "nntplib", "telnetlib",
        "webbrowser", "imaplib", "requests", "aiohttp", "xmlrpc", "websockets", "websocket",
        # dynamic code / foreign memory
        "importlib", "builtins", "ctypes", "runpy", "code", "pty",
        # persistence
        "pickle", "cPickle", "shelve", "dbm", "marshal", "sqlite3", "tempfile", "mmap",
        "zipfile", "tarfile",
    }
)
#: Root-name prefixes (urllib, urllib3, http, httpx, httplib2, ...).
_BANNED_PREFIXES = ("urllib", "http", "websocket", "xmlrpc")
#: Dotted modules banned although their root (``logging``) is fine.
_BANNED_DOTTED = ("logging.handlers", "logging.config")

_OS_DANGEROUS = re.compile(
    r"^os\.(exec\w*|spawn\w*|posix_spawn\w*|system|popen|fork\w*|startfile|open|fdopen)$"
)
_DANGEROUS_ATTR = re.compile(
    r"^(system|popen|exec\w*|spawn\w*|posix_spawn\w*|fork\w*|write_text|write_bytes|"
    r"import_module|__import__|__builtins__|open)$"
)
_WRITE_ATTRS = frozenset({"write_text", "write_bytes"})
_FILE_HANDLERS = frozenset(
    {"FileHandler", "WatchedFileHandler", "RotatingFileHandler", "TimedRotatingFileHandler"}
)
_DYNAMIC_NAMES = frozenset({"exec", "eval", "compile", "__import__", "__builtins__"})
_MODE_CHARS = frozenset("rwxabtU+")


def _banned_module(name: str) -> bool:
    root = name.split(".")[0]
    return (
        root in _BANNED_MODULES
        or root.startswith(_BANNED_PREFIXES)
        or any(name == d or name.startswith(d + ".") for d in _BANNED_DOTTED)
    )


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _writes(mode: ast.AST | None) -> bool:
    """True unless ``mode`` is absent or a literal that provably only reads."""
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return bool(set(mode.value) & set("wax+"))
    return True  # a computed mode cannot be proven read-only


def _outbound_findings(source: str) -> list[str]:
    """Egress, disk-write and dynamic-code primitives in ``source`` (empty means clean)."""
    tree = ast.parse(source)
    findings: list[str] = []
    aliases: dict[str, str] = {}  # local name -> what it was imported as
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
                if _banned_module(a.name):
                    findings.append(f"import {a.name}")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if _banned_module(node.module):
                findings.append(f"from {node.module} import ...")
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
                if _banned_module(f"{node.module}.{a.name}") or _OS_DANGEROUS.match(
                    f"{node.module}.{a.name}"
                ):
                    findings.append(f"from {node.module} import {a.name}")

    def resolve(dotted: str) -> str:
        root, _, rest = dotted.partition(".")
        origin = aliases.get(root, root)
        return f"{origin}.{rest}" if rest else origin

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            builtin_shadowed = node.id in aliases and not aliases[node.id].startswith("builtins")
            if node.id in _DYNAMIC_NAMES and not builtin_shadowed:
                findings.append(f"name {node.id}")
            if node.id in _FILE_HANDLERS:
                findings.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr in _FILE_HANDLERS:
                findings.append(f"attribute {node.attr}")
            if node.attr in _WRITE_ATTRS:
                findings.append(f"attribute {node.attr}")
            if node.attr in {"__builtins__", "__import__"}:
                findings.append(f"attribute {node.attr}")
        elif isinstance(node, ast.Call):
            func = _dotted(node.func)
            full = resolve(func) if func else ""
            has_star = any(isinstance(a, ast.Starred) for a in node.args) or any(
                k.arg is None for k in node.keywords
            )
            if _OS_DANGEROUS.match(full):
                findings.append(f"call {full}")
            elif full == "getattr" or full == "builtins.getattr":
                name = node.args[1] if len(node.args) > 1 else None
                own = (
                    bool(node.args)
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in {"self", "cls"}
                    and isinstance(name, ast.Name)  # a bare variable, not a built-up string
                )
                if has_star or not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                    if not own or has_star:  # getattr(self, field_name) only reads the object's own fields
                        findings.append("getattr with a non-literal name")
                elif _DANGEROUS_ATTR.match(name.value):
                    findings.append(f"getattr {name.value!r}")
            elif full in {"open", "io.open", "codecs.open", "builtins.open"}:
                mode = next((k.value for k in node.keywords if k.arg == "mode"), None)
                if mode is None and len(node.args) > 1:
                    mode = node.args[1]
                if has_star or _writes(mode):
                    findings.append("open() in a write mode (or an unprovable one)")
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "open":
                # Path(...).open("w"), gzip.open(f, "wb"): judge every literal that looks like a mode
                modes = [a for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                modes = [m for m in modes if m.value and set(m.value) <= _MODE_CHARS]
                kw = next((k.value for k in node.keywords if k.arg == "mode"), None)
                if has_star or _writes(kw) or any(_writes(m) for m in modes):
                    findings.append(".open() in a write mode")
            elif func and func.endswith("basicConfig") and any(
                k.arg in {"filename", "handlers"} for k in node.keywords
            ):
                findings.append("logging.basicConfig to a file or custom handler")
    return findings


def _xr_sources() -> list[Path]:
    pkg = Path(yazses.xr.__file__).resolve().parent
    return sorted(pkg.rglob("*.py"))


def test_egress_constant_is_empty() -> None:
    assert EGRESS == frozenset()


def test_xr_package_sources_are_found() -> None:
    names = {p.name for p in _xr_sources()}
    assert {"__init__.py", "types.py", "privacy.py", "wire.py"} <= names  # the scan is not vacuous


@pytest.mark.parametrize("path", _xr_sources(), ids=lambda p: p.name)
def test_xr_module_opens_no_outbound_path_and_writes_no_file(path: Path) -> None:
    assert _outbound_findings(path.read_text(encoding="utf-8")) == [], (
        f"{path.name} touches an egress or disk-write primitive; yazses.xr must stay offline "
        "and never persist raw samples (ADR-019) -- declare it there first or remove it"
    )


#: Each snippet is something the package must never contain. Several are the exact
#: reproducers from the security review (they all returned no findings before).
_BAD_SNIPPETS = [
    "import socket",
    "import urllib.request",
    "import urllib3",
    "from http.client import HTTPSConnection",
    "import requests",
    "import subprocess",
    "import ssl",
    "import smtplib",
    "import imaplib",
    "import xmlrpc.client",
    "import websockets",
    "import socketserver",
    "import selectors",
    "import asyncio\nasyncio.open_connection('h', 1)",
    "from asyncio import open_connection",
    "import importlib\nmod = importlib.import_module(name)",
    "import builtins\nbuiltins.exec('x')",
    "import ctypes",
    "import pickle\npickle.dump(obj, fh)",
    "import shelve",
    "import sqlite3",
    "import tempfile",
    "import os\nos.system('curl x')",
    "import os\nos.execv('/bin/sh', ['sh'])",
    "import os\nos.spawnl(os.P_NOWAIT, 'x')",
    "import os\nos.posix_spawn('/bin/sh', ['sh'], {})",
    "import os as o\no.popen('ls')",
    "from os import system\nsystem('ls')",
    "import os\ngetattr(os, 'sys' + 'tem')('ls')",
    "getattr(obj, name)",
    "getattr(self, 'sys' + 'tem')",
    "getattr(self.os, name)",
    "getattr(os, 'system')",
    "open('f.bin', 'w')",
    "open('f.bin', mode='ab')",
    "open('f.bin', 'r+')",
    "open('f.bin', mode)",
    "import io\nio.open('f', 'wb')",
    "from pathlib import Path\nPath('f').write_text('x')",
    "p.write_bytes(b'x')",
    "from pathlib import Path\nPath('f').open('w')",
    "import logging\nlogging.FileHandler('x.log')",
    "from logging.handlers import RotatingFileHandler",
    "import logging\nlogging.basicConfig(filename='x.log')",
    "exec('x = 1')",
    "eval(text)",
    "compile(text, 'f', 'exec')",
    "e = exec",
    "__import__('socket')",
]

_GOOD_SNIPPETS = [
    '"""Mentions socket, http, ssl and pickle in prose."""\n# subprocess\nimport math\nx = math.pi\n',
    "http = 3\nhttp_status = http + 1",
    "name = 'ssl'\nlabel = 'socket'",
    "class A:\n    socket = 1\nprint(A().socket)",
    "with open('f.bin') as fh:\n    data = fh.read()",
    "with open('f.bin', 'rb') as fh:\n    data = fh.read()",
    "with open('f.txt', mode='r', encoding='utf-8') as fh:\n    fh.read()",
    "import logging\nlog = logging.getLogger(__name__)\nlog.info('x')",
    "x = getattr(obj, 'name')\ny = getattr(obj, 'name', None)",
    "for name in names:\n    v = getattr(self, name)",
    "import re\npattern = re.compile('a+')",
    "import os\npath = os.path.join('a', 'b')",
    "import json, math, enum, collections, dataclasses\ns = json.dumps({'a': 1})",
    "def write_textual(self):\n    return 1\nwrite_textual(1)",
    "from yazses.xr.socket_like import thing",
]


@pytest.mark.parametrize("snippet", _BAD_SNIPPETS)
def test_scanner_flags_each_bad_snippet(snippet: str) -> None:
    assert _outbound_findings(snippet), snippet


@pytest.mark.parametrize("snippet", _GOOD_SNIPPETS)
def test_scanner_passes_each_good_snippet(snippet: str) -> None:
    assert _outbound_findings(snippet) == [], snippet
