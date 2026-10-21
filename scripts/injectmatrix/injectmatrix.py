#!/usr/bin/env python3
"""Persian injection matrix: does the target receive exactly the code points YazSes sent?

FA-08 / #517. The question is narrower than "does Persian work": it is whether the
text a backend types arrives in a real application **code point for code point**,
asked separately from whether it then *looks* right (bidi layout is a human visual
check, recorded in its own field and filed as its own kind of bug).

Standard library only, so it runs on a fresh Linux, macOS or Windows Python with
nothing installed beyond YazSes itself. Tk (for the target window) is imported only
by the command that opens one.

The pieces, in the order a tester uses them:

    receive    open a Tk text window that records what arrives, as code points
    drive      type every fixture into the focused window through `yazses inject`
    assemble   pair the captures with the fixtures and write the result JSON
    visual     record the human bidi-layout check for one case
    validate   check a result JSON against the schema and the shipped fixtures
    render     print the matrix table and the two separate defect lists
    compare    one fixture against one raw UTF-8 file (any other target app,
               e.g. what scripts/appprobe/probe-gui.sh saved)
    fixtures   list the fixture set
    text       print one fixture's text exactly, e.g. as appprobe's PROBE_TEXT

Nothing here sends anything anywhere: no network, and the receiver only ever sees
what is typed into its own window. The fixtures are synthetic or copied from
`contract/vectors/`, so a result never contains anything a person dictated.

The comparator, the result builder and the validator are pure functions of their
arguments; `tests/test_injectmatrix.py` drives them directly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURES_PATH = HERE / "fixtures.json"
SCHEMA_PATH = HERE / "result.schema.json"

SCHEMA_VERSION = 1
RESULT_KIND = "yazses-injection-matrix-result"

#: The content classes FA-08 and design/specs/persian-benchmark-and-validation.md §10
#: require. `control` is the ASCII baseline that separates "the harness or focus is
#: wrong" from "Unicode is mangled".
REQUIRED_CATEGORIES = (
    "persian", "mixed", "zwnj", "url-path", "digits", "punctuation", "multiline", "emoji",
)
CATEGORIES = ("control", *REQUIRED_CATEGORIES)

OS_VALUES = ("linux", "macos", "windows")
SESSION_VALUES = ("x11", "wayland", "none")
RECEIVERS = ("tk", "raw-file")
CODEPOINT_VERDICTS = ("EXACT", "MISMATCH", "NOTHING", "RECEIVER_LIMIT")
VISUAL_STATUSES = ("pending", "pass", "fail", "not-applicable")

REQUIRED_TOP_LEVEL = (
    "schema_version", "kind", "recorded_at", "fixture_set", "environment", "cases", "summary",
)
REQUIRED_ENVIRONMENT = (
    "os", "os_version", "session", "yazses_version", "backend", "backend_version",
    "receiver", "target_app", "target_app_version", "python_version",
)
#: Environment fields that must name something. The acceptance line is "results
#: identify OS, backend and version" -- a blank or "unknown" there identifies nothing.
IDENTIFYING_ENVIRONMENT = ("os", "os_version", "yazses_version", "backend", "target_app")
REQUIRED_CASE = (
    "fixture_id", "categories", "expected_code_points", "received_code_points",
    "codepoint_verdict", "first_divergence", "corruption_hints", "visual_check",
)
REQUIRED_SUMMARY = ("cases", "exact", "mismatch", "nothing", "receiver_limit",
                    "visual_pending", "visual_fail")

_PLACEHOLDERS = {"", "unknown", "n/a", "none", "?", "todo"}


# --------------------------------------------------------------------------- fixtures


@dataclass(frozen=True)
class Fixture:
    id: str
    categories: tuple[str, ...]
    text: str
    source: Any
    why: str


def load_fixture_doc(path: Path = FIXTURES_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixtures(path: Path = FIXTURES_PATH) -> list[Fixture]:
    doc = load_fixture_doc(path)
    return [
        Fixture(f["id"], tuple(f["categories"]), f["text"], f["source"], f["why"])
        for f in doc["fixtures"]
    ]


def fixture_set_id(path: Path = FIXTURES_PATH) -> dict[str, str]:
    """Version plus a hash of the texts, so a result names exactly what it typed."""
    doc = load_fixture_doc(path)
    canon = json.dumps(
        [[f["id"], f["text"]] for f in doc["fixtures"]], ensure_ascii=True, separators=(",", ":")
    )
    return {
        "version": str(doc["fixture_set_version"]),
        "sha256": hashlib.sha256(canon.encode("ascii")).hexdigest(),
    }


# ------------------------------------------------------------------------- comparator


def code_points(text: str) -> list[str]:
    return [f"U+{ord(ch):04X}" for ch in text]


def text_from_code_points(cps: list[str]) -> str:
    return "".join(chr(int(cp[2:], 16)) for cp in cps)


@dataclass(frozen=True)
class Comparison:
    verdict: str
    first_divergence: dict[str, Any] | None
    hints: tuple[str, ...]


def first_divergence(expected: str, received: str) -> dict[str, Any] | None:
    """Index of the first differing code point, and what stood on each side of it.

    When one string is a prefix of the other the index is the shorter length and the
    side that ran out is ``None`` -- "truncated here" and "extra text from here" are
    the two shapes that answer, and both are worth more than a bare "differs".
    """
    if expected == received:
        return None
    n = min(len(expected), len(received))
    i = next((k for k in range(n) if expected[k] != received[k]), n)
    return {
        "index": i,
        "expected": f"U+{ord(expected[i]):04X}" if i < len(expected) else None,
        "received": f"U+{ord(received[i]):04X}" if i < len(received) else None,
        "expected_name": _name(expected[i]) if i < len(expected) else None,
        "received_name": _name(received[i]) if i < len(received) else None,
    }


def _name(ch: str) -> str:
    if 0xD800 <= ord(ch) <= 0xDFFF:
        return "LONE SURROGATE"
    return unicodedata.name(ch, f"U+{ord(ch):04X}")


_BIDI_CONTROLS = dict.fromkeys(
    [0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)]
)
_FA_TO_AR = str.maketrans({"ک": "ك", "ی": "ي"})
_AR_TO_FA = str.maketrans({"ك": "ک", "ي": "ی"})
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGITS_TO_ASCII = str.maketrans(_FA_DIGITS + _AR_DIGITS, "0123456789" * 2)


def corruption_hints(expected: str, received: str) -> tuple[str, ...]:
    """Name the known corruption shapes that *exactly* explain a mismatch.

    Each hint is a specific, checkable transformation of `expected` that reproduces
    `received` (or a property `received` provably has). None is a heuristic: a hint
    either holds exactly or is absent, so an empty tuple means "a mismatch nobody
    has catalogued", which is itself worth reporting. Hints help the person filing
    the bug; they never change the verdict.
    """
    if expected == received or not received:
        return ()
    hints: list[str] = []
    if any(0xD800 <= ord(c) <= 0xDFFF for c in received):
        hints.append("lone-surrogates")
    if "�" in received and "�" not in expected:
        hints.append("replacement-characters")
    if len(received) == len(expected) and all(
        r == e or (r == "?" and ord(e) > 127) for e, r in zip(expected, received, strict=True)
    ):
        hints.append("non-ascii-as-question-marks")
    if "‌" in expected:
        if received == expected.replace("‌", ""):
            hints.append("zwnj-dropped")
        if received == expected.replace("‌", " "):
            hints.append("zwnj-as-space")
    stripped = expected.translate(_BIDI_CONTROLS)
    if stripped != expected and received == stripped:
        hints.append("bidi-controls-dropped")
    for form in ("NFC", "NFD", "NFKC", "NFKD"):
        if received == unicodedata.normalize(form, expected):
            hints.append(f"normalized-{form}")
    for table in (_FA_TO_AR, _AR_TO_FA):
        swapped = expected.translate(table)
        if swapped != expected and received == swapped:
            hints.append("arabic-persian-letter-swap")
    as_ascii = expected.translate(_DIGITS_TO_ASCII)
    if as_ascii != expected and received == as_ascii:
        hints.append("digits-to-ascii")
    if "\n" in expected:
        if received in (expected.replace("\n", "\r\n"), expected.replace("\n", "\r")):
            hints.append("newline-translated")
        if received in (expected.replace("\n", ""), expected.replace("\n", " ")):
            hints.append("newlines-dropped")
    if received == expected + "\n":
        hints.append("trailing-newline-added")
    elif expected.startswith(received):
        hints.append("truncated")
    elif received.startswith(expected):
        reps, rem = divmod(len(received), len(expected))
        hints.append("repeated" if rem == 0 and received == expected * reps else "extra-text")
    if sorted(received) == sorted(expected):
        hints.append("same-code-points-reordered")
    return tuple(dict.fromkeys(hints))


def compare(expected: str, received: str, *, receiver_ok: bool = True) -> Comparison:
    """The verdict on one case. The pass condition is code-point equality, nothing less.

    `receiver_ok=False` means the target window could not hold this text even when
    it was inserted directly (see `receiver_roundtrip`): a mismatch then says
    something about the harness, not the backend, and is reported as such.
    """
    if expected == received:
        return Comparison("EXACT", None, ())
    if not receiver_ok:
        return Comparison(
            "RECEIVER_LIMIT", first_divergence(expected, received),
            corruption_hints(expected, received),
        )
    if not received:
        return Comparison("NOTHING", first_divergence(expected, received), ())
    return Comparison(
        "MISMATCH", first_divergence(expected, received), corruption_hints(expected, received)
    )


# ---------------------------------------------------------------------- result document


def detect_environment() -> dict[str, Any]:
    """What can be read from this machine without asking. The rest comes from flags."""
    system = platform.system()
    os_name = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(system, system)
    if os_name == "linux":
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session not in ("x11", "wayland"):
            session = "wayland" if os.environ.get("WAYLAND_DISPLAY") else (
                "x11" if os.environ.get("DISPLAY") else "none"
            )
    else:
        session = "none"
    if os_name == "macos":
        os_version = f"macOS {platform.mac_ver()[0]}"
    elif os_name == "windows":
        os_version = f"Windows {platform.release()} {platform.version()}"
    else:
        os_version = _linux_pretty_name() or f"Linux {platform.release()}"
    return {"os": os_name, "os_version": os_version, "session": session,
            "python_version": platform.python_version()}


def _linux_pretty_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass  # no /etc/os-release (not Linux, or a minimal container): report no name
    return ""


def build_case(fixture: Fixture, received: str, *, receiver_ok: bool = True) -> dict[str, Any]:
    cmp = compare(fixture.text, received, receiver_ok=receiver_ok)
    return {
        "fixture_id": fixture.id,
        "categories": list(fixture.categories),
        "expected_code_points": code_points(fixture.text),
        "received_code_points": code_points(received),
        "codepoint_verdict": cmp.verdict,
        "first_divergence": cmp.first_divergence,
        "corruption_hints": list(cmp.hints),
        "visual_check": {"status": "pending", "notes": ""},
    }


def summarize(cases: list[dict[str, Any]]) -> dict[str, int]:
    def count(verdict: str) -> int:
        return sum(c["codepoint_verdict"] == verdict for c in cases)

    return {
        "cases": len(cases),
        "exact": count("EXACT"),
        "mismatch": count("MISMATCH"),
        "nothing": count("NOTHING"),
        "receiver_limit": count("RECEIVER_LIMIT"),
        "visual_pending": sum(c["visual_check"]["status"] == "pending" for c in cases),
        "visual_fail": sum(c["visual_check"]["status"] == "fail" for c in cases),
    }


def build_result(
    environment: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    fixture_set: dict[str, str],
    recorded_at: str,
    receiver_selftest: dict[str, bool] | None = None,
    stray_captures: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": RESULT_KIND,
        "recorded_at": recorded_at,
        "fixture_set": fixture_set,
        "environment": environment,
        "receiver_selftest": receiver_selftest,
        "stray_captures": stray_captures,
        "cases": cases,
        "summary": summarize(cases),
    }


def validate_result(doc: Any, fixtures: list[Fixture] | None = None) -> list[str]:
    """Every way `doc` breaks the schema or disagrees with itself. Empty means valid.

    Hand-written rather than `jsonschema`, which a base install does not carry; the
    `result.schema.json` beside this file is the published contract and
    `tests/test_injectmatrix.py` pins the two to the same required fields.

    With `fixtures`, each case is also checked against the shipped fixture text.
    Every verdict is recomputed from the stored code points -- a result that says
    EXACT must actually be exact -- and RECEIVER_LIMIT is accepted only for a case
    whose `receiver_selftest` entry is false, so a backend failure cannot be
    relabelled as the receiver's.
    """
    if not isinstance(doc, dict):
        return ["result is not a JSON object"]
    problems = [f"missing top-level field {k!r}" for k in REQUIRED_TOP_LEVEL if k not in doc]
    if problems:
        return problems
    if doc["schema_version"] != SCHEMA_VERSION:
        problems.append(f"schema_version {doc['schema_version']!r} != {SCHEMA_VERSION}")
    if doc["kind"] != RESULT_KIND:
        problems.append(f"kind {doc['kind']!r} != {RESULT_KIND!r}")
    try:
        datetime.fromisoformat(str(doc["recorded_at"]))
    except ValueError:
        problems.append(f"recorded_at {doc['recorded_at']!r} is not an ISO-8601 timestamp")

    env = doc["environment"]
    if not isinstance(env, dict):
        return [*problems, "environment is not an object"]
    problems += [f"environment missing {k!r}" for k in REQUIRED_ENVIRONMENT if k not in env]
    for key in IDENTIFYING_ENVIRONMENT:
        value = env.get(key)
        if not isinstance(value, str) or value.strip().lower() in _PLACEHOLDERS:
            problems.append(f"environment.{key} must identify something, got {value!r}")
    if env.get("os") not in OS_VALUES:
        problems.append(f"environment.os {env.get('os')!r} not in {OS_VALUES}")
    if env.get("session") not in SESSION_VALUES:
        problems.append(f"environment.session {env.get('session')!r} not in {SESSION_VALUES}")
    if env.get("os") in ("macos", "windows") and env.get("session") != "none":
        problems.append("environment.session applies to Linux only; use 'none'")
    if env.get("os") == "linux" and env.get("session") == "none":
        problems.append("environment.session must be 'x11' or 'wayland' on Linux")
    if env.get("receiver") not in RECEIVERS:
        problems.append(f"environment.receiver {env.get('receiver')!r} not in {RECEIVERS}")

    selftest = doc.get("receiver_selftest")
    if selftest is not None and not (
        isinstance(selftest, dict) and all(isinstance(v, bool) for v in selftest.values())
    ):
        problems.append("receiver_selftest must be null or an object of booleans")
        selftest = None

    by_id = {f.id: f for f in fixtures} if fixtures is not None else None
    cases = doc["cases"]
    if not isinstance(cases, list) or not cases:
        return [*problems, "cases must be a non-empty list"]
    seen: set[str] = set()
    for n, case in enumerate(cases):
        where = f"cases[{n}]"
        missing = [k for k in REQUIRED_CASE if k not in case]
        if missing:
            problems += [f"{where} missing {k!r}" for k in missing]
            continue
        fid = case["fixture_id"]
        where = f"cases[{n}] ({fid})"
        if fid in seen:
            problems.append(f"{where} appears twice")
        seen.add(fid)
        verdict = case["codepoint_verdict"]
        if verdict not in CODEPOINT_VERDICTS:
            problems.append(f"{where} codepoint_verdict {verdict!r} not in {CODEPOINT_VERDICTS}")
        status = case["visual_check"].get("status") if isinstance(case["visual_check"], dict) \
            else None
        if status not in VISUAL_STATUSES:
            problems.append(f"{where} visual_check.status {status!r} not in {VISUAL_STATUSES}")
        try:
            expected = text_from_code_points(case["expected_code_points"])
            received = text_from_code_points(case["received_code_points"])
        except (ValueError, TypeError, IndexError):
            problems.append(f"{where} code points must be 'U+XXXX' strings")
            continue
        if by_id is not None:
            fixture = by_id.get(fid)
            if fixture is None:
                problems.append(f"{where} is not in the shipped fixture set")
            elif fixture.text != expected:
                problems.append(f"{where} expected_code_points differ from the shipped fixture")
        # Only the receiver's own self-test can excuse a mismatch: an entry that is
        # absent or true means the window held this text, so the backend is judged.
        recomputed = compare(
            expected,
            received,
            receiver_ok=not (isinstance(selftest, dict) and selftest.get(fid) is False),
        ).verdict
        if verdict in CODEPOINT_VERDICTS and recomputed != verdict:
            why = (" (receiver_selftest does not mark this fixture as one the receiver"
                   " cannot hold)" if verdict == "RECEIVER_LIMIT" else "")
            problems.append(
                f"{where} says {verdict} but the code points give {recomputed}{why}"
            )
    if isinstance(doc["summary"], dict) and all(
        isinstance(c, dict) and "codepoint_verdict" in c and isinstance(c.get("visual_check"), dict)
        for c in cases
    ):
        want = summarize(cases)
        for k in REQUIRED_SUMMARY:
            if doc["summary"].get(k) != want[k]:
                problems.append(f"summary.{k} is {doc['summary'].get(k)!r}, cases give {want[k]}")
    return problems


# ------------------------------------------------------------------ capture assembly


def assign_captures(
    timeline: list[dict[str, Any]], captures: list[dict[str, Any]]
) -> tuple[dict[str, str], int]:
    """Pair each capture with the fixture whose injection window contains it.

    Fixture i owns ``[start_i, start_{i+1})``; the last one is open-ended. Pairing by
    time rather than by order is what keeps one silent fixture from shifting every
    later result onto the wrong expectation. A fixture that the receiver split into
    two captures (the backend paused longer than the settle time) gets them joined
    in arrival order. Captures before the first injection are counted, not paired.
    """
    ordered = sorted(timeline, key=lambda t: t["start"])
    received: dict[str, str] = {t["fixture_id"]: "" for t in ordered}
    stray = 0
    for cap in sorted(captures, key=lambda c: c["first_change"]):
        owner = None
        for t in ordered:
            if cap["first_change"] >= t["start"]:
                owner = t["fixture_id"]
            else:
                break
        if owner is None:
            stray += 1
        else:
            received[owner] += text_from_code_points(cap["code_points"])
    return received, stray


def receiver_roundtrip(widget: Any, text: str) -> bool:
    """Can the target window hold `text` at all, when nobody types it?

    Tcl/Tk before 9.0 stores text as UCS-2 in many builds, so an astral emoji can
    come back as two lone surrogates *with no injection involved*. Without this, the
    harness would file its own limitation as a backend bug.
    """
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    got = widget.get("1.0", "end-1c")
    widget.delete("1.0", "end")
    return bool(got == text)


# ---------------------------------------------------------------------- rendering


def _render_cell(cases: list[dict[str, Any]]) -> str:
    """One category's cell. RECEIVER_LIMIT is the receiver's failure, never the backend's.

    A case the target window could not hold even when inserted directly says nothing
    about the backend, so it is neither EXACT nor FAIL: it is "not tested", named so
    the gap is visible rather than blank (the evidence standard's wording).
    """
    if not cases:
        return "not tested"
    failed = [c["fixture_id"] for c in cases if c["codepoint_verdict"] in ("MISMATCH", "NOTHING")]
    limited = [c["fixture_id"] for c in cases if c["codepoint_verdict"] == "RECEIVER_LIMIT"]
    if failed:
        cell = "FAIL: " + ", ".join(failed)
    elif len(limited) == len(cases):
        return "not tested (receiver limit: " + ", ".join(limited) + ")"
    else:
        cell = "EXACT"
    if limited:
        cell += " (receiver limit, not tested: " + ", ".join(limited) + ")"
    return cell


def render_matrix(results: list[dict[str, Any]]) -> str:
    cols = REQUIRED_CATEGORIES
    head = ["OS", "Session", "Backend", "YazSes", "Target", *cols, "Visual"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    corruption: list[str] = []
    limits: list[str] = []
    layout: list[str] = []
    for doc in results:
        env = doc["environment"]
        row = [env["os_version"], env["session"],
               f"{env['backend']}" + (f" {env['backend_version']}" if env["backend_version"] else ""),
               env["yazses_version"],
               f"{env['target_app']}" + (f" {env['target_app_version']}"
                                          if env["target_app_version"] else "")]
        for cat in cols:
            row.append(_render_cell([c for c in doc["cases"] if cat in c["categories"]]))
        s = doc["summary"]
        row.append("fail" if s["visual_fail"] else ("pending" if s["visual_pending"] else "pass"))
        lines.append("| " + " | ".join(row) + " |")
        label = f"{env['os_version']} / {env['session']} / {env['backend']} / {env['yazses_version']}"
        for c in doc["cases"]:
            if c["codepoint_verdict"] != "EXACT":
                d = c["first_divergence"] or {}
                hints = ", ".join(c["corruption_hints"]) or "uncatalogued"
                entry = (
                    f"- {label}: `{c['fixture_id']}` {c['codepoint_verdict']} at index "
                    f"{d.get('index')} (expected {d.get('expected')}, got {d.get('received')}; "
                    f"{hints})"
                )
                (limits if c["codepoint_verdict"] == "RECEIVER_LIMIT" else corruption).append(entry)
            if c["visual_check"]["status"] == "fail":
                layout.append(f"- {label}: `{c['fixture_id']}` {c['visual_check']['notes']}")
    out = ["\n".join(lines), "", "Code-point failures (file each as a Unicode-corruption issue):",
           *(corruption or ["- none"]), "",
           "Visual-layout failures (file each as a bidi-layout issue, separately):",
           *(layout or ["- none"]), "",
           "Receiver limits (the target window could not hold the text even when inserted"
           + " directly; not a backend failure, do not file -- re-run with another target):",
           *(limits or ["- none"])]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- CLI


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _environment_from_args(args: argparse.Namespace, receiver: str,
                           tk_patchlevel: str | None, backend: str | None,
                           yazses_version: str | None) -> dict[str, Any]:
    env = detect_environment()
    env.update({
        "yazses_version": args.yazses_version or yazses_version or "",
        "backend": args.backend or backend or "",
        "backend_version": args.backend_version or None,
        "receiver": receiver,
        "target_app": args.target_app or (
            f"injectmatrix Tk receiver (Tk {tk_patchlevel})" if receiver == "tk" else ""
        ),
        "target_app_version": args.target_app_version or None,
    })
    if args.os_version:
        env["os_version"] = args.os_version
    if args.session:
        env["session"] = args.session
    return env


def cmd_receive(args: argparse.Namespace) -> int:
    import tkinter as tk

    fixtures = load_fixtures()
    out = Path(args.out)
    out.write_text("", encoding="utf-8")
    root = tk.Tk()
    root.title("YazSes injection target")
    text = tk.Text(root, width=90, height=14, undo=False, wrap="word")
    text.pack(fill="both", expand=True)
    status = tk.Label(root, anchor="w")
    status.pack(fill="x")
    selftest = {f.id: receiver_roundtrip(text, f.text) for f in fixtures}
    meta = {"type": "meta", "tk_patchlevel": str(root.tk.call("info", "patchlevel")),
            "receiver_selftest": selftest}
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(meta) + "\n")
    failing = [k for k, ok in selftest.items() if not ok]
    state: dict[str, Any] = {"last": "", "changed": 0.0, "first": None, "n": 0}

    def poll() -> None:
        now = time.time()
        content = text.get("1.0", "end-1c")
        if content != state["last"]:
            state["last"], state["changed"] = content, now
            if state["first"] is None:
                state["first"] = now
        elif content and now - state["changed"] >= args.settle:
            cap = {"type": "capture", "first_change": state["first"], "settled": now,
                   "code_points": code_points(content)}
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(cap) + "\n")
            state.update(last="", first=None, n=state["n"] + 1)
            text.delete("1.0", "end")
            if args.count and state["n"] >= args.count:
                root.destroy()
                return
        status.config(text=f"captures: {state['n']}   receiver self-test failures: "
                           f"{', '.join(failing) or 'none'}   (close the window to finish)")
        root.after(100, poll)

    text.focus_set()
    root.after(100, poll)
    root.mainloop()
    return 0


def split_command(command: str) -> list[str]:
    """`--yazses "uv run yazses"` as argv, on Windows too.

    Non-POSIX `shlex` keeps the quotes around a quoted path such as
    ``"C:\\Program Files\\YazSes\\yazses-cli.exe"``, and CreateProcess would then
    look for a file whose name starts with a quote.
    """
    if os.name != "nt":
        return shlex.split(command)
    return [t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t
            for t in shlex.split(command, posix=False)]


def cmd_drive(args: argparse.Namespace) -> int:
    fixtures = load_fixtures()
    if args.only:
        wanted = set(args.only.split(","))
        fixtures = [f for f in fixtures if f.id in wanted]
    yazses = split_command(args.yazses)
    # `yazses inject` echoes the text back; on a Windows pipe the locale code page
    # cannot encode Persian, and a crash *after* typing would read as a failure.
    child_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    version = subprocess.run([*yazses, "--version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", env=child_env,
                             check=False).stdout.strip()
    out = Path(args.out)
    with out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "meta", "yazses_version": version}) + "\n")
        for n, fixture in enumerate(fixtures):
            cmd = [*yazses, "inject"]
            if n == 0 and args.focus_delay > 0:
                cmd += ["--delay", str(args.focus_delay)]
            start = time.time() + (args.focus_delay if n == 0 else 0)
            proc = subprocess.run([*cmd, fixture.text], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", env=child_env,
                                  check=False)
            backend = next((ln.split(":", 1)[1].strip() for ln in proc.stdout.splitlines()
                            if ln.startswith("Backend:")), None)
            fh.write(json.dumps({"type": "inject", "fixture_id": fixture.id, "start": start,
                                 "end": time.time(), "returncode": proc.returncode,
                                 "backend": backend}) + "\n")
            print(f"{fixture.id}: exit {proc.returncode}, backend {backend}")
            time.sleep(args.gap)
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    fixtures = load_fixtures()
    by_id = {f.id: f for f in fixtures}
    drive = _read_jsonl(Path(args.timeline))
    recv = _read_jsonl(Path(args.captures))
    timeline = [r for r in drive if r["type"] == "inject"]
    meta_d = next((r for r in drive if r["type"] == "meta"), {})
    meta_r = next((r for r in recv if r["type"] == "meta"), {})
    selftest = meta_r.get("receiver_selftest")
    backends = {t["backend"] for t in timeline if t["backend"]}
    if len(backends) > 1:
        print(f"backend changed during the run: {sorted(backends)}", file=sys.stderr)
        return 2
    received, stray = assign_captures(timeline, [r for r in recv if r["type"] == "capture"])
    cases = [build_case(by_id[fid], text, receiver_ok=(selftest or {}).get(fid, True))
             for fid, text in received.items()]
    env = _environment_from_args(args, "tk", meta_r.get("tk_patchlevel"),
                                 next(iter(backends), None), meta_d.get("yazses_version"))
    doc = build_result(env, cases, fixture_set=fixture_set_id(), recorded_at=_now(),
                       receiver_selftest=selftest, stray_captures=stray)
    return _finish(doc, fixtures, Path(args.out))


def cmd_compare(args: argparse.Namespace) -> int:
    fixtures = load_fixtures()
    fixture = next((f for f in fixtures if f.id == args.fixture), None)
    if fixture is None:
        print(f"no fixture {args.fixture!r}", file=sys.stderr)
        return 2
    raw = Path(args.received).read_bytes()
    received = raw.decode("utf-8", errors="surrogateescape")
    if args.strip_final_newline and received.endswith("\n"):
        received = received[:-2] if received.endswith("\r\n") else received[:-1]
    env = _environment_from_args(args, "raw-file", None, None, None)
    doc = build_result(env, [build_case(fixture, received)], fixture_set=fixture_set_id(),
                       recorded_at=_now())
    if args.strip_final_newline:
        doc["receiver_normalization"] = "strip-one-final-newline"
    return _finish(doc, fixtures, Path(args.out))


def _finish(doc: dict[str, Any], fixtures: list[Fixture], out: Path) -> int:
    _write_json(out, doc)
    problems = validate_result(doc, fixtures)
    s = doc["summary"]
    print(f"wrote {out}: {s['exact']}/{s['cases']} EXACT, {s['mismatch']} MISMATCH, "
          f"{s['nothing']} NOTHING, {s['receiver_limit']} RECEIVER_LIMIT")
    for p in problems:
        print(f"  invalid: {p}", file=sys.stderr)
    return 1 if problems else 0


def cmd_visual(args: argparse.Namespace) -> int:
    path = Path(args.result)
    doc = json.loads(path.read_text(encoding="utf-8"))
    case = next((c for c in doc["cases"] if c["fixture_id"] == args.case), None)
    if case is None:
        print(f"no case {args.case!r} in {path}", file=sys.stderr)
        return 2
    case["visual_check"] = {"status": args.status, "notes": args.notes}
    doc["summary"] = summarize(doc["cases"])
    _write_json(path, doc)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    fixtures = load_fixtures()
    bad = 0
    for p in args.results:
        problems = validate_result(json.loads(Path(p).read_text(encoding="utf-8")), fixtures)
        print(f"{p}: {'valid' if not problems else 'INVALID'}")
        for prob in problems:
            print(f"  {prob}")
        bad += bool(problems)
    return 1 if bad else 0


def cmd_render(args: argparse.Namespace) -> int:
    docs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.results]
    sys.stdout.write(render_matrix(docs))
    return 0


def cmd_fixtures(args: argparse.Namespace) -> int:
    for f in load_fixtures():
        print(f"{f.id:24} {','.join(f.categories):40} {len(f.text):5} code points")
    print(json.dumps(fixture_set_id()))
    return 0


def cmd_text(args: argparse.Namespace) -> int:
    """One fixture's text, byte-exact, for a harness that takes it as an argument."""
    fixture = next((f for f in load_fixtures() if f.id == args.fixture), None)
    if fixture is None:
        print(f"no fixture {args.fixture!r}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(fixture.text.encode("utf-8"))
    sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def env_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--out", required=True, help="result JSON to write")
        p.add_argument("--backend", help="concrete backend (default: what `yazses inject` printed)")
        p.add_argument("--backend-version", help="e.g. `xdotool --version`; optional")
        p.add_argument("--yazses-version", help="default: `yazses --version` from the drive log")
        p.add_argument("--target-app", help="receiving application (default: the Tk receiver)")
        p.add_argument("--target-app-version")
        p.add_argument("--os-version", help="override the detected OS version string")
        p.add_argument("--session", choices=SESSION_VALUES, help="override the detected session")

    p = sub.add_parser("receive", help="open the Tk target window and record what arrives")
    p.add_argument("--out", required=True, help="captures JSONL")
    p.add_argument("--settle", type=float, default=3.0,
                   help="seconds without change that end one capture")
    p.add_argument("--count", type=int, default=0, help="stop after N captures (0: on close)")
    p.set_defaults(fn=cmd_receive)

    p = sub.add_parser("drive", help="type each fixture via `yazses inject`")
    p.add_argument("--out", required=True, help="timeline JSONL")
    p.add_argument("--yazses", default="yazses", help="command that runs YazSes")
    p.add_argument("--focus-delay", type=float, default=8.0,
                   help="seconds to click into the receiver before the first fixture")
    p.add_argument("--gap", type=float, default=7.0,
                   help="seconds between fixtures; must exceed the receiver's --settle")
    p.add_argument("--only", help="comma-separated fixture ids")
    p.set_defaults(fn=cmd_drive)

    p = sub.add_parser("assemble", help="pair captures with fixtures; write the result")
    p.add_argument("--timeline", required=True)
    p.add_argument("--captures", required=True)
    env_flags(p)
    p.set_defaults(fn=cmd_assemble)

    p = sub.add_parser("compare", help="judge one raw UTF-8 file against one fixture")
    p.add_argument("--fixture", required=True)
    p.add_argument("--received", required=True, help="file holding exactly what arrived")
    p.add_argument("--strip-final-newline", action="store_true",
                   help="drop ONE trailing newline an editor added on save (recorded)")
    env_flags(p)
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("visual", help="record the human bidi-layout check for one case")
    p.add_argument("result")
    p.add_argument("--case", required=True)
    p.add_argument("--status", required=True, choices=VISUAL_STATUSES)
    p.add_argument("--notes", default="")
    p.set_defaults(fn=cmd_visual)

    p = sub.add_parser("validate", help="check result JSON files")
    p.add_argument("results", nargs="+")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("render", help="print the matrix table and defect lists")
    p.add_argument("results", nargs="+")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("fixtures", help="list the fixture set")
    p.set_defaults(fn=cmd_fixtures)

    p = sub.add_parser("text", help="print one fixture's text exactly (e.g. for PROBE_TEXT)")
    p.add_argument("fixture")
    p.set_defaults(fn=cmd_text)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
