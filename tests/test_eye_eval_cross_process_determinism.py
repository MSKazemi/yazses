"""The eye-control task fixtures and their results are the same bytes in every process.

`test_eye_eval_tasks.py` proves the generator reproduces the checked-in file. That is one
process, one hash seed, one interpreter run: it cannot see a dependence on set or dict
ordering, on `PYTHONHASHSEED`, or on state left behind by an earlier call in the same
process, because all of those are constant inside a single run. Determinism is a claim
about *separate* runs, so this file starts separate interpreters under different hash seeds
and compares what they print.

What each child hashes, and why those four things:

* every task fixture for several seeds (the generator, including the PRNG);
* the result document a synthetic run of each task writes (`runner`, with a fixed fake
  machine and a fixed timestamp, because the real ones are inputs, not outputs);
* the metrics a *mixed*-outcome run tallies (an all-success run never exercises the
  branches that count failures);
* the face-switch replay report over the committed traces (`switch_trace`,
  `switch_replay`).

The hash is compared across children *and* against the parent. Three children agreeing with
each other but not with the parent would mean the answer depends on the interpreter's own
startup state, which is just as much a determinism bug.

The static checks at the bottom close the other half. A process-level comparison can only
fail on a dependence it happens to trigger; a module that imports `random` or `time` could
be green for years. The imports and calls those modules may make are fixed here, not
inferred from what they make today.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from yazses.eyeeval.tasks import _SplitMix64

ROOT = Path(__file__).resolve().parent.parent
EYEEVAL = ROOT / "src" / "yazses" / "eyeeval"
TRACE_DIR = ROOT / "tests" / "fixtures" / "face_switch_traces"

#: Chosen to differ in every way a hash seed can: zero (hashing disabled), a small value, a
#: large one. The environment variable is the only thing that varies between children.
HASH_SEEDS = ("0", "1", "2718281828")

#: Run in a fresh interpreter. Kept as source text so the child imports nothing from this
#: test module -- the parent must not be able to leak state into it.
CHILD = r"""
import hashlib, json, sys
from pathlib import Path

from yazses.eyeeval import (
    Provenance, build_result, completeness_verdict, dump_result, dump_task,
    generate_task, synthetic_records, tally,
)
from yazses.eyeeval.switch_replay import replay_traces
from yazses.eyeeval.switch_trace import check_trace
from yazses.eyeeval.tasks import DEFAULT_SEEDS, TASK_IDS

trace_dir = Path(sys.argv[1])
parts = []
for task_id in TASK_IDS:
    for seed in (DEFAULT_SEEDS[task_id], 0, 1, 2**63 + 5, 2**64 + 7):
        parts.append(dump_task(generate_task(task_id, seed)))

machine = Provenance(
    yazses_version="9.9.9", git_commit="0123456789ab", python_version="3.13.0",
    os_name="ExampleOS", os_version="1.2", kernel="0.0.0-test", arch="x86_64",
    cpu_model="Example CPU 1000", logical_cpus=8, ram_gb=16.0, session_type="headless",
    displays=({"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
               "scale": 1.0, "primary": True},),
    packages={"yazses": "9.9.9"},
)
for task_id in TASK_IDS:
    task = generate_task(task_id)
    records = synthetic_records(task)
    parts.append(dump_result(build_result(
        task=task, records=records, provenance=machine, study_mode="synthetic",
        timestamp="2026-09-25T00:00:00+00:00", camera_class="none",
        capture_mode="synthetic_replay", records_source="synthetic",
    )))
    # A mixed run: every third outcome is the task's last (failure-shaped) outcome.
    from yazses.eyeeval.tasks import TASK_OUTCOMES
    mixed = [dict(r) for r in records]
    for index, record in enumerate(mixed):
        if "outcome" in record and index % 3 == 0:
            record["outcome"] = TASK_OUTCOMES[task_id][-1]
    parts.append(json.dumps(tally(task, mixed)) + completeness_verdict(task, mixed))

traces = [check_trace(json.loads(p.read_text(encoding="utf-8")))
          for p in sorted(trace_dir.glob("*.json"))]
parts.append(json.dumps(replay_traces(traces, sweep=[0.4, 0.5, 0.6])))

blob = "\x00".join(parts).encode("utf-8")
print(hashlib.sha256(blob).hexdigest(), len(blob))
"""


def _run_child(hash_seed: str, cwd: Path) -> str:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hash_seed
    # A different locale and timezone per child: a result that depended on either would
    # show up as a hash difference rather than as a surprise on someone else's machine.
    env["TZ"] = "Pacific/Auckland" if hash_seed == "1" else "UTC"
    env["LC_ALL"] = "C"
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(TRACE_DIR)],
        capture_output=True, text=True, env=env, cwd=cwd, check=False, timeout=300,
    )
    assert done.returncode == 0, f"child (PYTHONHASHSEED={hash_seed}) failed:\n{done.stderr}"
    return done.stdout.strip()


@pytest.fixture(scope="module")
def child_hashes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    cwd = tmp_path_factory.mktemp("cwd")
    return {seed: _run_child(seed, cwd) for seed in HASH_SEEDS}


def test_the_traces_the_children_replay_exist() -> None:
    """Without this the replay part of the hash is the hash of an empty report."""
    assert len(list(TRACE_DIR.glob("*.json"))) >= 2


def test_separate_processes_under_different_hash_seeds_agree(child_hashes: dict[str, str]) -> None:
    assert len(set(child_hashes.values())) == 1, child_hashes


def test_the_child_hashes_something_substantial(child_hashes: dict[str, str]) -> None:
    """A child that printed the hash of an empty blob would agree with itself forever."""
    for line in child_hashes.values():
        digest, size = line.split()
        assert len(digest) == 64
        assert int(size) > 100_000, f"only {size} bytes were hashed"
        assert digest != hashlib.sha256(b"").hexdigest()


def test_the_hash_would_notice_a_difference() -> None:
    """The comparison above is only evidence if it can fail: different seeds must differ."""
    from yazses.eyeeval import dump_task, generate_task
    from yazses.eyeeval.tasks import GAZE_TASK

    a = hashlib.sha256(dump_task(generate_task(GAZE_TASK, 1)).encode()).hexdigest()
    b = hashlib.sha256(dump_task(generate_task(GAZE_TASK, 2)).encode()).hexdigest()
    assert a != b


# --- the PRNG against a published vector ----------------------------------------------


def test_splitmix64_matches_the_published_reference_vector() -> None:
    """Independent evidence that the generator is SplitMix64 and not merely stable.

    A characterization test (the fixture comparison) would freeze a wrong generator as the
    contract. These are the first five outputs of Vigna's reference `splitmix64.c` for
    state 1234567, the vector shipped with several independent implementations.
    """
    rng = _SplitMix64(1234567)
    assert [rng.next_u64() for _ in range(5)] == [
        6457827717110365317,
        3203168211198807973,
        9817491932198370423,
        4593380528125082431,
        16408922859458223821,
    ]


def test_a_seed_wider_than_64_bits_wraps_instead_of_failing() -> None:
    assert _SplitMix64(2**64 + 7).next_u64() == _SplitMix64(7).next_u64()


# --- what these modules may not touch -------------------------------------------------

#: Everything that can bring wall-clock time, an unseeded stream, the host or the network
#: into a module whose output is meant to be a pure function of its arguments.
FORBIDDEN_IMPORTS = frozenset(
    {"random", "secrets", "time", "datetime", "uuid", "os", "sys", "tempfile", "platform",
     "socket", "urllib", "http", "subprocess", "shutil", "glob", "locale", "getpass"}
)
FORBIDDEN_CALLS = frozenset({"hash", "id", "open", "input", "eval", "exec"})
PURE_MODULES = ("tasks.py", "runner.py", "switch_trace.py", "switch_replay.py")


def _tree(name: str) -> ast.Module:
    return ast.parse((EYEEVAL / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", PURE_MODULES)
def test_no_module_imports_a_clock_an_unseeded_stream_or_the_host(name: str) -> None:
    found: set[str] = set()
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    assert not (found & FORBIDDEN_IMPORTS), sorted(found & FORBIDDEN_IMPORTS)


@pytest.mark.parametrize("name", PURE_MODULES)
def test_no_module_calls_an_ordering_or_io_builtin(name: str) -> None:
    called = {
        node.func.id
        for node in ast.walk(_tree(name))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not (called & FORBIDDEN_CALLS), sorted(called & FORBIDDEN_CALLS)


def test_the_guard_is_not_vacuous() -> None:
    """The scans above are green on a module with nothing in it; prove they can fail."""
    tree = ast.parse("import random\nx = hash('a')\n")
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert imports & FORBIDDEN_IMPORTS
    assert calls & FORBIDDEN_CALLS
    assert all((EYEEVAL / name).stat().st_size > 1000 for name in PURE_MODULES)


#: A path literal bakes one platform's separator into a fixture or a report.
_PATH_LITERAL = re.compile(r"^(/[A-Za-z0-9_.-]+){2,}|^[A-Za-z]:\\|\\\\")


@pytest.mark.parametrize("name", ["tasks.py", "switch_trace.py", "switch_replay.py"])
def test_no_string_literal_is_a_platform_path(name: str) -> None:
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(_tree(name))
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    bad = [
        node.value
        for node in ast.walk(_tree(name))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and _PATH_LITERAL.search(node.value)
    ]
    assert not bad, bad


def test_the_checked_in_fixtures_use_unix_newlines_and_ascii() -> None:
    """A fixture saved with CRLF or non-ASCII text is a different file on another machine."""
    root = ROOT / "tests" / "fixtures" / "eye_eval_tasks"
    files = sorted(root.glob("*.json"))
    assert len(files) == 3
    for path in files:
        raw = path.read_bytes()
        assert b"\r" not in raw, path.name
        raw.decode("ascii")
        assert raw.endswith(b"}\n"), path.name
