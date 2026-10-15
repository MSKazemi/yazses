#!/usr/bin/env python3
"""The non-hardware eye-control evaluation, as ONE entry point a CI runner can call.

``design/eye-control/EVALUATION.md`` E0-E2 is the part of the eye-control evidence ladder
that needs no camera, no person and no desktop session. This script runs the pieces of it
that are checkable from a base install and leaves behind a small, validated record of what
ran, on which machine, at which commit::

    uv run python scripts/eye_eval_ci.py --out-dir eye-eval-ci            # one machine
    uv run python scripts/eye_eval_ci.py --out-dir out --require-commit   # what CI runs
    uv run python scripts/eye_eval_ci.py --out-dir out --with-pytest      # + the eye-eval tests
    uv run python scripts/eye_eval_ci.py --collect downloaded-artifacts   # the matrix verdict

What a run checks (each is one entry in the record's ``checks``):

* ``lazy_imports``  -- importing the eye-eval package pulls in no camera, vision or Qt module;
* ``task_fixtures`` -- the generated tasks equal the checked-in fixtures (parsed, so line
  endings cannot matter) and validate;
* ``result:<task>`` -- a synthetic result for each task is built, schema-validated, swept for
  machine/person identifiers and written, exactly as ``yazses eye-eval --synthetic`` does;
* ``determinism``   -- building the same result twice gives the same bytes;
* ``replay:face_switch`` and ``replay:grounding`` -- the committed synthetic trace reports
  still match what the real code produces (their own ``--check`` drift gates, run as
  subprocesses so their exit codes are what is judged);
* ``pytest:eye_eval`` -- only with ``--with-pytest``: the test files that import
  ``yazses.eyeeval`` (derived by scanning ``tests/``, not listed by hand).

What it must NOT be read as claiming is written into the record itself (``does_not_prove``):
real webcam accuracy, the real pointer permission or UI, human usability, and false
activations during natural behaviour. This is CI evidence, not hardware evidence.

``--collect DIR`` is the other half: it looks for ``eye-eval-ci.json`` in every leg's
download, re-validates each, and exits non-zero if any expected OS is **absent**, malformed
or failed. A leg that never ran cannot upload anything, so the matrix needs a judge that
counts the legs it expected -- an artifact that is not there looks exactly like a leg that
was never asked for.

Properties that are deliberate:

* **Base install only.** stdlib plus ``yazses``; no cv2, mediapipe, PySide6,
  network, camera or display. Run it under ``scripts/simulate-missing-deps.py``'s
  blocker to prove it.
* **The record is written even when a check fails**, then the exit code says so. A failed
  leg must leave evidence of how it failed, not a hole.
* **Exit codes.** ``0`` every check passed; ``1`` at least one check failed (or, with
  ``--collect``, a leg is missing/failed); ``2`` the script could not run at all (a bad
  argument or an unwritable output directory).
* **ASCII output and LF-only files.** A Windows console decoding as cp1252 must not turn a
  dash into a crash, and ``write_text`` there would turn ``\\n`` into ``\\r\\n``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from yazses.eyeeval import (  # noqa: E402
    SCHEMA_VERSION,
    TASK_IDS,
    EyeEvalRunError,
    build_result,
    check_task,
    collect_provenance,
    dump_result,
    forbidden_field_problems,
    generate_task,
    local_identifiers,
    privacy_problems,
    synthetic_records,
    write_result,
)
from yazses.eyeeval.provenance import as_sections  # noqa: E402
from yazses.eyeeval.runner import _LEAK_PATTERNS  # noqa: E402
from yazses.eyeeval.tasks import FIXTURE_FILENAMES  # noqa: E402

RECORD_KIND = "eye_eval_ci"
RECORD_VERSION = "1.0"
RECORD_NAME = "eye-eval-ci.json"
RESULTS_DIR = "results"

#: What a leg of the CI matrix is called, from ``platform.system()``. Closed on purpose: the
#: matrix is Linux, macOS and Windows, and an unexpected name is a finding, not a new row.
EXPECTED_SYSTEMS = ("Linux", "Darwin", "Windows")

#: Modules that must never be loaded merely by importing the eye-eval package.
HEAVY_MODULES = ("cv2", "mediapipe", "PySide6")

#: What this record does and does not support -- carried in every record so an artifact
#: separated from its workflow still states its own limits.
PROVES = (
    "the package installs and imports on this OS and Python",
    "the result schema, the task fixtures and the privacy sweep hold",
    "synthetic task results build, validate and serialise deterministically",
    "the committed synthetic trace reports still match the code",
)
DOES_NOT_PROVE = (
    "real webcam accuracy",
    "real pointer permission or on-screen behaviour",
    "human usability",
    "false activations during natural behaviour",
)

_TIMEOUT_S = 600


class CiRunError(Exception):
    """The script could not run at all. Exit 2, never a record that looks like a result."""


# --- the checks -------------------------------------------------------------------------


def _subprocess_env() -> dict[str, str]:
    """The child environment: source tree importable, and UTF-8 regardless of the console."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(argv: list[str]) -> tuple[int, str]:
    """Run *argv* from the repository root; return (exit code, last lines of its output)."""
    try:
        proc = subprocess.run(
            argv, cwd=ROOT, env=_subprocess_env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_TIMEOUT_S, check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {_TIMEOUT_S}s"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
    return proc.returncode, " | ".join(line.strip() for line in tail)[:600]


def scrub(text: str) -> str:
    """Remove this checkout's path and this machine's identifiers from a failure message.

    A failing check quotes a subprocess's output, and a traceback names the absolute path of
    the file -- `/home/<login>/...`, `C:\\Users\\<login>\\...` -- which is exactly what a
    public workflow artifact must not carry. Scrubbing happens where the text is captured, so
    the worst case is a vaguer message, never a leaked one.
    """
    ids = local_identifiers()
    roots = {str(ROOT), ROOT.as_posix(), *ids.home_paths}
    roots |= {p.replace("\\", "/") for p in roots}
    for root in sorted(roots, key=len, reverse=True):
        if len(root) >= 3:
            text = text.replace(root, "<path>")
    for _label, pattern in _LEAK_PATTERNS:
        text = pattern.sub("<redacted>", text)
    for name in (ids.hostname, *ids.usernames):
        if len(name) >= 3:
            text = text.replace(name, "<redacted>")
    return text


def _check(check_id: str, fn: Callable[[], str]) -> dict[str, str]:
    """Run one check. Any exception is a FAIL with its message -- never a skipped entry."""
    try:
        return {"id": check_id, "status": "PASS", "detail": scrub(fn())}
    except Exception as exc:  # noqa: BLE001 - a crashed check must be recorded as failed
        return {"id": check_id, "status": "FAIL", "detail": scrub(f"{type(exc).__name__}: {exc}")[:600]}


def optional_dependencies() -> dict[str, str]:
    """Which camera/vision/Qt modules are installed here -- informational, never a verdict.

    Recorded so a reader can tell a base-install leg (all ``absent``) from a developer
    machine, which is the difference between "the lazy imports hold" being proven and
    merely not contradicted.
    """
    out: dict[str, str] = {}
    for name in HEAVY_MODULES:
        try:
            out[name] = "installed" if importlib.util.find_spec(name) is not None else "absent"
        except (ImportError, ValueError):
            # `scripts/simulate-missing-deps.py` makes find_spec itself raise
            # ModuleNotFoundError rather than answer None, and so can a broken finder on a
            # real machine. Either way the module cannot be used here: it is absent.
            out[name] = "absent"
    return out


def check_lazy_imports() -> str:
    """Import the whole eye-eval package in a fresh interpreter; none of HEAVY_MODULES may load."""
    code = (
        "import json, sys\n"
        "import yazses.eyeeval, yazses.eyeeval.switch_replay, yazses.eyeeval.gaze_field\n"
        f"print(json.dumps([m for m in {HEAVY_MODULES!r} if m in sys.modules]))\n"
    )
    rc, out = _run([sys.executable, "-c", code])
    if rc != 0:
        raise AssertionError(f"the eye-eval package did not import (exit {rc}): {out}")
    loaded = json.loads(out.rsplit("|", 1)[-1].strip())
    if loaded:
        raise AssertionError(f"importing yazses.eyeeval loaded {', '.join(loaded)}")
    installed = [m for m, state in optional_dependencies().items() if state == "installed"]
    if installed:
        return f"none of {', '.join(HEAVY_MODULES)} loaded ({', '.join(installed)} installed, so laziness is observed)"
    return f"imports cleanly; {', '.join(HEAVY_MODULES)} are absent (so laziness is not observable, only import-safety)"


def check_task_fixtures() -> str:
    """Every task id has a fixture; each fixture parses, validates and equals the generator."""
    fixture_dir = ROOT / "tests" / "fixtures" / "eye_eval_tasks"
    problems: list[str] = []
    for task_id in TASK_IDS:
        name = FIXTURE_FILENAMES[task_id]
        path = fixture_dir / name
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{name}: unreadable ({exc})")
            continue
        generated = generate_task(task_id)
        check_task(generated)
        if on_disk != generated:
            problems.append(f"{name}: differs from generate_task({task_id!r})")
    if problems:
        raise AssertionError("; ".join(problems))
    return f"{len(TASK_IDS)} tasks match their fixtures"


def build_task_result(task_id: str, timestamp: str) -> dict[str, Any]:
    """The synthetic ``ci`` result for one task -- what ``yazses eye-eval --synthetic`` builds."""
    task = generate_task(task_id)
    check_task(task)
    return build_result(
        task=task,
        records=synthetic_records(task),
        provenance=collect_provenance(),
        study_mode="ci",
        timestamp=timestamp,
        camera_class="none",
        capture_mode="synthetic_replay",
        records_source="synthetic",
    )


def _result_check(task_id: str, timestamp: str, results_dir: Path) -> Callable[[], str]:
    def run() -> str:
        doc = build_task_result(task_id, timestamp)
        try:
            written = write_result(doc, results_dir / f"{task_id}.json", identifiers=local_identifiers())
        except EyeEvalRunError as exc:
            raise AssertionError(str(exc)) from None
        run_ = doc["run"]
        return f"{run_['verdict']}; {run_['scored_trials_recorded']}/{run_['scored_trials_expected']} trials; {written.name}"

    return run


def check_determinism(timestamp: str) -> str:
    """The same inputs must give the same bytes -- twice in one process is the cheap proof."""
    for task_id in TASK_IDS:
        first = dump_result(build_task_result(task_id, timestamp))
        second = dump_result(build_task_result(task_id, timestamp))
        if first != second:
            raise AssertionError(f"{task_id}: two builds of the same result differ")
    return f"{len(TASK_IDS)} results rebuilt byte-identically"


def _replay_check(script: str) -> Callable[[], str]:
    def run() -> str:
        rc, out = _run([sys.executable, str(ROOT / "scripts" / script), "--check"])
        if rc != 0:
            raise AssertionError(f"scripts/{script} --check exited {rc}: {out}")
        return f"scripts/{script} --check exited 0"

    return run


def eye_eval_test_files(tests_dir: Path | None = None) -> list[str]:
    """The test files that import ``yazses.eyeeval``, derived from the tree.

    A hand-written list would go stale the day a test is added; this one cannot. Posix
    separators are returned (relative to the repository root) so the list reads the same
    on every OS.
    """
    base = tests_dir or ROOT / "tests"
    found = sorted(
        path.relative_to(base.parent).as_posix()
        for path in base.glob("test_*.py")
        if "yazses.eyeeval" in path.read_text(encoding="utf-8", errors="replace")
    )
    return found


def _pytest_check() -> str:
    files = eye_eval_test_files()
    if not files:
        raise AssertionError("no test file imports yazses.eyeeval; the selection is empty")
    rc, out = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files])
    if rc != 0:
        raise AssertionError(f"pytest exited {rc} over {len(files)} files: {out}")
    return f"pytest exited 0 over {len(files)} files"


# --- the record -------------------------------------------------------------------------


def run_checks(out_dir: Path, timestamp: str, *, with_pytest: bool) -> list[dict[str, str]]:
    results_dir = out_dir / RESULTS_DIR
    checks = [
        _check("lazy_imports", check_lazy_imports),
        _check("task_fixtures", check_task_fixtures),
        *(_check(f"result:{t}", _result_check(t, timestamp, results_dir)) for t in TASK_IDS),
        _check("determinism", lambda: check_determinism(timestamp)),
        _check("replay:face_switch", _replay_check("replay_face_switch_trace.py")),
        _check("replay:grounding", _replay_check("replay_grounding_trace.py")),
    ]
    if with_pytest:
        checks.append(_check("pytest:eye_eval", _pytest_check))
    return checks


def build_record(checks: list[dict[str, str]], timestamp: str) -> dict[str, Any]:
    """The per-leg record. Pure given its inputs apart from the machine facts it stamps."""
    sections = as_sections(collect_provenance())
    # `displays` are omitted: a CI runner has none worth naming, and the fingerprint of an
    # empty topology adds a field that varies between runners for no reader's benefit.
    return {
        "record_kind": RECORD_KIND,
        "record_version": RECORD_VERSION,
        "result_schema_version": SCHEMA_VERSION,
        "study_mode": "ci",
        "timestamp": timestamp,
        "platform_system": platform.system(),
        "software": sections["software"],
        "machine": sections["machine"],
        "optional_dependencies": optional_dependencies(),
        "checks": checks,
        "overall": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
        "proves": list(PROVES),
        "does_not_prove": list(DOES_NOT_PROVE),
    }


def validate_record(doc: Any, *, require_commit: bool = False) -> list[str]:
    """Every problem with a per-leg record, so ``--collect`` can refuse a bad one.

    The same two sweeps a result gets -- forbidden field names and machine/person
    identifiers -- because this document is attached to a public workflow run too.
    """
    if not isinstance(doc, dict):
        return [f"the record is {type(doc).__name__}, not an object"]
    problems: list[str] = []
    if doc.get("record_kind") != RECORD_KIND:
        problems.append(f"record_kind is {doc.get('record_kind')!r}, expected {RECORD_KIND!r}")
    version = str(doc.get("record_version"))
    if version.split(".")[0] != RECORD_VERSION.split(".")[0]:
        problems.append(f"record_version {version!r} is not a {RECORD_VERSION.split('.')[0]}.x record")
    if doc.get("study_mode") != "ci":
        problems.append(f"study_mode is {doc.get('study_mode')!r}; this record is always 'ci'")
    if doc.get("platform_system") not in EXPECTED_SYSTEMS:
        problems.append(f"platform_system {doc.get('platform_system')!r} is not one of {EXPECTED_SYSTEMS}")
    arch = (doc.get("machine") or {}).get("arch") if isinstance(doc.get("machine"), dict) else None
    if not arch or arch == "unknown":
        problems.append("machine.arch is missing: the record cannot name its runner")
    commit = (doc.get("software") or {}).get("git_commit") if isinstance(doc.get("software"), dict) else None
    if require_commit and not commit:
        problems.append("software.git_commit is missing: the record cannot name its commit")
    checks = doc.get("checks")
    if not isinstance(checks, list) or not checks:
        problems.append("checks is empty or missing; a record of no checks reads as a pass")
        checks = []
    for index, entry in enumerate(checks):
        if not isinstance(entry, dict) or entry.get("status") not in ("PASS", "FAIL") or not entry.get("id"):
            problems.append(f"checks[{index}] is malformed")
    failed = [c.get("id") for c in checks if isinstance(c, dict) and c.get("status") != "PASS"]
    expected_overall = "FAIL" if failed or not checks else "PASS"
    if doc.get("overall") != expected_overall:
        problems.append(f"overall is {doc.get('overall')!r} but the checks say {expected_overall!r}")
    if not doc.get("does_not_prove"):
        problems.append("does_not_prove is empty: the record must state its own limits")
    problems += forbidden_field_problems(doc)
    problems += privacy_problems(doc, local_identifiers())
    return problems


def write_record(doc: dict[str, Any], path: Path) -> None:
    """LF-only, ASCII, trailing newline -- bytes, so no OS can translate the line endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, indent=2, ensure_ascii=True) + "\n").encode("ascii"))


# --- the matrix verdict -----------------------------------------------------------------


def collect_matrix(root: Path, expected: tuple[str, ...] = EXPECTED_SYSTEMS, *, require_commit: bool = True) -> tuple[int, list[str]]:
    """Judge a directory of downloaded legs. Returns (exit code, human-readable lines).

    Every ``eye-eval-ci.json`` under *root* is a leg. An expected system with no record is
    reported as MISSING and fails the run: absence is the failure this exists to see.
    """
    lines: list[str] = []
    seen: dict[str, dict[str, Any]] = {}
    bad = False
    paths = sorted(root.rglob(RECORD_NAME)) if root.is_dir() else []
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            lines.append(f"UNREADABLE {path.as_posix()}: {exc}")
            bad = True
            continue
        problems = validate_record(doc, require_commit=require_commit)
        system = str(doc.get("platform_system")) if isinstance(doc, dict) else "?"
        if problems:
            bad = True
            lines.append(f"INVALID    {system}: " + "; ".join(problems))
            continue
        if system in seen:
            bad = True
            lines.append(f"DUPLICATE  {system}: more than one record")
            continue
        seen[system] = doc
        failed = [c["id"] for c in doc["checks"] if c["status"] != "PASS"]
        arch = doc["machine"]["arch"]
        commit = doc["software"].get("git_commit")
        if doc["overall"] == "PASS":
            lines.append(f"PASS       {system} ({arch}) commit {commit}: {len(doc['checks'])} checks")
        else:
            bad = True
            lines.append(f"FAIL       {system} ({arch}) commit {commit}: {', '.join(failed)}")
    for system in expected:
        if system not in seen and not any(system in line for line in lines):
            bad = True
            lines.append(f"MISSING    {system}: no {RECORD_NAME} was found for this leg")
    commits = {d["software"].get("git_commit") for d in seen.values()}
    if len(commits) > 1:
        bad = True
        lines.append(f"MISMATCH   legs report different commits: {sorted(str(c) for c in commits)}")
    lines.append("matrix: " + ("FAIL" if bad else "PASS") + " (CI evidence only; no camera, pointer or person was involved)")
    return (1 if bad else 0), lines


# --- the command line -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    parser.add_argument("--out-dir", type=Path, help="where to write eye-eval-ci.json and results/")
    parser.add_argument("--collect", type=Path, help="judge a directory of downloaded legs instead of running")
    parser.add_argument("--require-commit", action="store_true", help="fail if the checkout's commit cannot be named")
    parser.add_argument("--with-pytest", action="store_true", help="also run the test files that import yazses.eyeeval")
    parser.add_argument("--timestamp", help="fix the timestamp (ISO 8601) for a reproducible record")
    args = parser.parse_args(argv)

    if args.collect is not None:
        code, lines = collect_matrix(args.collect, require_commit=True)
        print("\n".join(lines))
        return code

    if args.out_dir is None:
        parser.error("--out-dir is required unless --collect is given")
    timestamp = args.timestamp or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        checks = run_checks(args.out_dir, timestamp, with_pytest=args.with_pytest)
        record = build_record(checks, timestamp)
        problems = validate_record(record, require_commit=args.require_commit)
        if problems:
            # Withhold every detail rather than risk the one that tripped the sweep, and
            # name only the count: a problem message quotes the very value it objects to.
            for entry in record["checks"]:
                entry["detail"] = "withheld: the record failed validation"
            record["checks"].append(
                {"id": "record", "status": "FAIL", "detail": f"{len(problems)} validation problem(s)"}
            )
            record["overall"] = "FAIL"
            if validate_record(record, require_commit=False):
                print("the record cannot be made safe to write; nothing was written", file=sys.stderr)
                return 2
        write_record(record, args.out_dir / RECORD_NAME)
    except OSError as exc:
        print(f"cannot write the record: {exc}", file=sys.stderr)
        return 2

    for entry in record["checks"]:
        print(f"{entry['status']:<4} {entry['id']:<22} {entry['detail']}")
    print(f"overall: {record['overall']}  ({platform.system()} {record['machine']['arch']}, "
          f"commit {record['software'].get('git_commit')}) -> {args.out_dir / RECORD_NAME}")
    print("This is CI evidence. It proves nothing about a real camera, pointer or person.")
    return 0 if record["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
