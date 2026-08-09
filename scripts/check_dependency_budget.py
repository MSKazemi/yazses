#!/usr/bin/env python3
"""Enforce the dependency budget: a lean base install stays lean.

YazSes ships 18 base dependencies against 140+ features on purpose — a user who
wants plain dictation should not download mediapipe, speechbrain, sherpa-onnx, or
llama-cpp. Everything heavy lives behind an extra in `[project.optional-dependencies]`
and is imported lazily, inside the function that needs it, so the base install stays
dormant to those packages. Nothing enforced that until now; it survived on reviewer
vigilance, and a top-level `import` in the wrong file is invisible to every test we
have.

Three checks, run against the *base* install (whatever `uv sync` gives you with no
extras — exactly what CI already has):

1. Base dependency growth. `[project.dependencies]` is compared against the recorded
   baseline below. New names fail the PR unless it carries the
   `dependency-budget-override` label — growth should be a decision, not a diff nobody
   noticed.
2. Eager optional imports. Import `yazses.core.daemon` (what every user runs, extras
   or not) and check `sys.modules` for anything that belongs to an extra. A lazy
   import moved to the top of a file during an unrelated refactor is invisible to
   review and to the test suite; this is the check that actually catches it.
3. Cold-start import time. Measured with `python -X importtime` and compared against
   a recorded budget with headroom, so a real regression fails without chasing
   machine noise.

    uv run python scripts/check_dependency_budget.py
    uv run python scripts/check_dependency_budget.py --record-baseline   # after a
        deliberate change, to update dependency_budget_baseline.json

See CONTRIBUTING.md for the override label and how to update the baseline.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
BASELINE_FILE = Path(__file__).with_name("dependency_budget_baseline.json")

OVERRIDE_LABEL = "dependency-budget-override"

# What every `yazses` process runs through, extras or not — the check that matters is
# against this, not against a synthetic import of the whole package.
DAEMON_ENTRYPOINT = "yazses.core.daemon"

# Cold-start import time varies with the machine (and a bit with the OS), so the gate
# allows this much headroom over the recorded baseline before it fails. Wide enough to
# absorb CI-runner noise, narrow enough to still catch a heavy top-level import.
IMPORT_TIME_TOLERANCE = 1.5

# Extras whose package name already matches its import name, mapped to the top-level
# module a base-only install must never see in sys.modules. `overlay` (PySide6) and
# `parakeet` (onnx-asr) are deliberately absent: both packages already ship in the
# base install for other reasons (see the comments in pyproject.toml), so their
# modules are *expected* to be loaded even without the extra.
OPTIONAL_IMPORT_MODULES = {
    "llama_cpp": "slm / notes",
    "pygls": "lsp",
    "pynvim": "lsp",
    "serial": "emg",
    "bleak": "ble",
    "parselmouth": "prosody",
    "kokoro_onnx": "tts",
    "onnxruntime": "tts / silero",
    "soundfile": "tts",
    "speechbrain": "voiceprint",
    "sherpa_onnx": "diarization",
    "silero_vad": "silero",
    "mcp": "agent",
    "mediapipe": "gaze",
    "cv2": "gaze",
}


def base_dependency_names() -> list[str]:
    """The PyPI distribution names in ``[project.dependencies]``, order preserved."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    names = []
    for spec in data["project"]["dependencies"]:
        # A dependency spec is `name[extras]<version markers>; env marker`. The name
        # is everything before the first character that can start any of those.
        name = re.split(r"[\[<>=!~; ]", spec, maxsplit=1)[0]
        names.append(name)
    return names


def load_baseline() -> dict:
    return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))


def write_baseline(base_dependencies: list[str], import_time_us: int) -> None:
    baseline = {
        "_comment": (
            "Recorded by `scripts/check_dependency_budget.py --record-baseline`. "
            "Update deliberately — this file changing is the point, not a bug in "
            "the diff."
        ),
        "base_dependencies": sorted(base_dependencies, key=str.lower),
        "import_time_budget_us": import_time_us,
    }
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")


def pr_labels() -> set[str]:
    raw = os.environ.get("PR_LABELS", "")
    return {label.strip() for label in raw.split(",") if label.strip()}


def check_growth(current: list[str], baseline: dict, *, is_pull_request: bool) -> bool:
    baseline_names = set(baseline["base_dependencies"])
    current_names = set(current)
    new = sorted(current_names - baseline_names, key=str.lower)
    removed = sorted(baseline_names - current_names, key=str.lower)

    print(f"Base dependencies: {len(current_names)} (baseline: {len(baseline_names)})")

    if not new:
        if removed:
            print(
                f"  {len(removed)} removed since the baseline ({', '.join(removed)}) — "
                "run --record-baseline to reflect the shrink."
            )
        return True

    labels = pr_labels()
    if OVERRIDE_LABEL in labels:
        print(
            f"  +{len(new)} new: {', '.join(new)} — allowed, PR carries "
            f"'{OVERRIDE_LABEL}'. Run --record-baseline before merge so this "
            "doesn't fail the next PR too."
        )
        return True

    if not is_pull_request:
        # No PR context to check a label against (a push run on main, or a local
        # run). The label gate only makes sense during review; treat this as a
        # reminder rather than a failure so a maintainer who forgot to bump the
        # baseline in the same commit doesn't get a red main branch for it.
        print(
            f"  +{len(new)} new: {', '.join(new)} — baseline is stale. Run "
            "--record-baseline and commit the update."
        )
        return True

    print(
        f"FAIL: +{len(new)} new base dependency/ies not in the recorded baseline: "
        f"{', '.join(new)}",
        file=sys.stderr,
    )
    print(
        f"  A base dependency is a decision, not a side effect (see #141). Either "
        f"drop it, or ask a maintainer for the '{OVERRIDE_LABEL}' label if it's "
        "deliberate — then run --record-baseline.",
        file=sys.stderr,
    )
    return False


def _import_probe_once(entrypoint: str) -> tuple[list[str], int]:
    """Import *entrypoint* in a subprocess; return (loaded modules, its own us)."""
    proc = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", f"import {entrypoint}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(
            f"FAIL: `import {entrypoint}` raised on a base install:\n"
            f"{proc.stderr.strip()}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    modules: list[str] = []
    cumulative_us = 0
    for line in proc.stderr.splitlines():
        if not line.startswith("import time:"):
            continue
        fields = [f.strip() for f in line[len("import time:") :].split("|")]
        if len(fields) != 3:
            continue
        self_us, cum_us, name = fields
        if not self_us.lstrip("-").isdigit():
            continue  # the header row ("self [us] | cumulative | imported package")
        modules.append(name)
        if name == entrypoint:
            cumulative_us = int(cum_us)
    return modules, cumulative_us


# A shared CI runner is a noisy neighbour: two `import yazses.core.daemon` runs
# 5 minutes apart measured 0.559s and 0.874s here, a swing no fixed tolerance on a
# single sample survives. A process can only be slowed by contention, never sped up,
# so the fastest of a few samples is the closest thing to a clean measurement without
# needing a dedicated runner.
IMPORT_PROBE_SAMPLES = 3


def run_import_probe(entrypoint: str) -> tuple[list[str], int]:
    """Import *entrypoint* :data:`IMPORT_PROBE_SAMPLES` times; return (modules, best us)."""
    modules: list[str] = []
    samples: list[int] = []
    for _ in range(IMPORT_PROBE_SAMPLES):
        modules, cumulative_us = _import_probe_once(entrypoint)
        samples.append(cumulative_us)
    print(f"  {IMPORT_PROBE_SAMPLES} samples (us): {samples}")
    return modules, min(samples)


def check_eager_imports(modules: list[str]) -> bool:
    loaded = set(modules)
    offenders = []
    for module, extra in OPTIONAL_IMPORT_MODULES.items():
        if module in loaded or any(m.startswith(module + ".") for m in loaded):
            offenders.append((module, extra))

    if not offenders:
        print(f"No optional-extra module in sys.modules after `import {DAEMON_ENTRYPOINT}`.")
        return True

    print(
        f"FAIL: {DAEMON_ENTRYPOINT} eagerly imports module(s) that belong to an "
        "extra:",
        file=sys.stderr,
    )
    for module, extra in offenders:
        print(f"  {module}  (extra: {extra})", file=sys.stderr)
    print(
        "  A base install must never load these. Move the import inside the "
        "function that needs it, gated on the feature being enabled.",
        file=sys.stderr,
    )
    return False


def check_import_time(cumulative_us: int, baseline: dict) -> bool:
    seconds = cumulative_us / 1_000_000
    print(f"Cold-start import time ({DAEMON_ENTRYPOINT}): {seconds:.3f}s")

    budget_us = baseline.get("import_time_budget_us")
    if not budget_us:
        print("  No recorded budget yet — run --record-baseline once on a clean CI run.")
        return True

    threshold_us = budget_us * IMPORT_TIME_TOLERANCE
    budget_seconds = budget_us / 1_000_000
    if cumulative_us <= threshold_us:
        print(f"  Within budget ({budget_seconds:.3f}s x {IMPORT_TIME_TOLERANCE}).")
        return True

    print(
        f"FAIL: {seconds:.3f}s exceeds the recorded budget of {budget_seconds:.3f}s "
        f"x {IMPORT_TIME_TOLERANCE} tolerance ({threshold_us / 1_000_000:.3f}s).",
        file=sys.stderr,
    )
    print(
        "  If this regression is deliberate (a base dependency got heavier on "
        "purpose), run --record-baseline and explain why in the PR.",
        file=sys.stderr,
    )
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help="write the current dependency set and import time as the new baseline",
    )
    args = parser.parse_args(argv)

    baseline = load_baseline()
    current = base_dependency_names()
    is_pull_request = os.environ.get("GITHUB_EVENT_NAME") == "pull_request"

    modules, cumulative_us = run_import_probe(DAEMON_ENTRYPOINT)

    if args.record_baseline:
        write_baseline(current, cumulative_us)
        print(f"Baseline recorded to {BASELINE_FILE.relative_to(ROOT)}.")
        return 0

    ok = check_growth(current, baseline, is_pull_request=is_pull_request)
    ok &= check_eager_imports(modules)
    ok &= check_import_time(cumulative_us, baseline)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
