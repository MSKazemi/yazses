#!/usr/bin/env python3
"""Enforce the dependency budget: a lean base install stays lean.

YazSes ships 16 base dependencies against 140+ features on purpose — a user who
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

# Every extra in `[project.optional-dependencies]`, mapped to the top-level modules its
# packages import as — a base-only install must never see any of these in sys.modules.
#
# This map is the reason the check has teeth, and it is also the one thing that can
# quietly rot: an extra added to pyproject.toml with no entry here would be enforced by
# nothing. `check_extras_covered` closes that loop by failing when pyproject grows an
# extra this map has never heard of, so the gate cannot be outgrown in silence.
EXTRA_MODULES: dict[str, tuple[str, ...]] = {
    "agent": ("mcp",),
    "ble": ("bleak",),
    "chinese": ("opencc",),
    # PySide6 left the base install (648 MB of Qt a headless box cannot use), so the
    # two extras that own it are now genuinely enforceable: nothing may import Qt at
    # daemon-import time. `desktop` and `overlay` are the same dependency under two
    # names -- one states intent, the other names the widget.
    "desktop": ("PySide6",),
    "denoise": ("noisereduce",),
    "emg-band": ("brainflow",),
    "diarization": ("sherpa_onnx",),
    # The alternative diarizer. Mapped by its dotted name rather than the bare
    # `pyannote` namespace, which is shared with pyannote.core/pyannote.database
    # and would flag packages this extra does not own.
    "diarization-pyannote": ("pyannote.audio",),
    "emg": ("serial",),
    "gaze": ("mediapipe", "cv2"),
    "lsp": ("pygls", "pynvim"),
    "notes": ("llama_cpp",),
    "overlay": ("PySide6",),
    "parakeet": ("onnx_asr",),
    "prosody": ("parselmouth",),
    "silero": ("silero_vad", "onnxruntime"),
    "slm": ("llama_cpp",),
    "tts": ("kokoro_onnx", "onnxruntime", "soundfile"),
    "voiceprint": ("speechbrain",),
    "voiceprint-resemblyzer": ("resemblyzer",),
}

# Extras that exist but cannot be enforced this way, each for a stated reason. An extra
# belongs here only when a base install is *expected* to have its modules importable.
EXEMPT_EXTRAS: dict[str, str] = {
    "all": "aggregate of every other extra; its members are checked individually",
}

# module -> the extra(s) that own it, for the failure message.
OPTIONAL_IMPORT_MODULES: dict[str, str] = {
    module: " / ".join(sorted(e for e, mods in EXTRA_MODULES.items() if module in mods))
    for modules in EXTRA_MODULES.values()
    for module in modules
}


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def canonical(name: str) -> str:
    """PEP 503 normalised form, so `Pillow` and `pillow` are not two dependencies."""
    return re.sub(r"[-_.]+", "-", name).lower()


def base_dependency_names() -> list[str]:
    """The PyPI distribution names in ``[project.dependencies]``, order preserved."""
    names = []
    for spec in _pyproject()["project"]["dependencies"]:
        # A dependency spec is `name[extras]<version markers>; env marker`. The name
        # is everything before the first character that can start any of those.
        name = re.split(r"[\[<>=!~; ]", spec, maxsplit=1)[0]
        names.append(name)
    return names


def declared_extras() -> list[str]:
    return sorted(_pyproject()["project"].get("optional-dependencies", {}))


def check_extras_covered(extras: list[str]) -> bool:
    """Fail when pyproject grows an extra `EXTRA_MODULES` has never heard of.

    Without this, the eager-import check silently stops covering new features: the
    extra exists, nothing maps it to a module, and a top-level import of it passes.
    """
    unknown = [e for e in extras if e not in EXTRA_MODULES and e not in EXEMPT_EXTRAS]
    if not unknown:
        print(f"Extras covered: {len(EXTRA_MODULES)} mapped, {len(EXEMPT_EXTRAS)} exempt.")
        return True

    print(
        f"FAIL: {len(unknown)} extra(s) in [project.optional-dependencies] that the "
        f"eager-import check does not know about: {', '.join(unknown)}",
        file=sys.stderr,
    )
    print(
        "  Add each one to EXTRA_MODULES in this file (extra -> the top-level modules "
        "its packages import as), or to EXEMPT_EXTRAS with the reason a base install "
        "is expected to have them importable. An unmapped extra is enforced by nothing.",
        file=sys.stderr,
    )
    return False


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


def baseline_at_base_ref() -> dict | None:
    """The baseline file as it exists on the PR's *base* branch, or None.

    Measuring growth against the baseline committed in the same PR makes the label
    gate decorative: adding a dependency and running `--record-baseline` in one commit
    leaves `new` empty and the check passes. Growth has to be measured against what the
    base branch says, so the only way past the gate is the label.
    """
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if not base_ref:
        return None
    rel = BASELINE_FILE.relative_to(ROOT).as_posix()
    for rev in (f"origin/{base_ref}", base_ref, "FETCH_HEAD"):
        proc = subprocess.run(
            ["git", "show", f"{rev}:{rel}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                return None
    return None


def check_growth(current: list[str], baseline: dict, *, is_pull_request: bool) -> bool:
    baseline_names = {canonical(n) for n in baseline["base_dependencies"]}
    current_names = {canonical(n) for n in current}
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
        # `-X importtime` writes its table to stderr as well, so the traceback that
        # actually names the offending import arrives underneath a few hundred lines
        # of timings — in a CI log, the one line the contributor needs is the one
        # line they cannot find. Keep the diagnosis, drop the instrumentation.
        diagnosis = "\n".join(
            line for line in proc.stderr.splitlines()
            if not line.startswith("import time:")
        ).strip()
        print(
            f"FAIL: `import {entrypoint}` raised on a base install:\n"
            f"{diagnosis or proc.stderr.strip()}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    modules: list[str] = []
    cumulative_us: int | None = None
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

    # `-X importtime`'s output is a CPython implementation detail, not a stable API. If
    # its format ever moves, every line above is skipped, `modules` comes back empty and
    # the timing reads as 0us — which the budget check would happily call "within
    # budget" forever, leaving both check 2 and check 3 green and dead. Refuse to
    # report a measurement we did not actually take.
    if cumulative_us is None or not modules:
        print(
            f"FAIL: could not parse `python -X importtime` output for {entrypoint} "
            f"({len(modules)} module lines, no cumulative time for the entrypoint).\n"
            "  The probe cannot measure anything, so this gate is not enforcing "
            "anything either — fix the parser rather than ignoring the check.",
            file=sys.stderr,
        )
        raise SystemExit(1)
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


def check_import_time(cumulative_us: int, baseline: dict, *, enforced: bool = True) -> bool:
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

    over = (
        f"{seconds:.3f}s exceeds the recorded budget of {budget_seconds:.3f}s "
        f"x {IMPORT_TIME_TOLERANCE} tolerance ({threshold_us / 1_000_000:.3f}s)."
    )
    if not enforced:
        # The budget is a single number recorded on a GitHub `ubuntu-latest` runner. A
        # contributor's laptop is not that machine, and telling them to
        # `--record-baseline` would overwrite a shared budget with a local one. Report
        # it, don't fail on it — CI is where this gate has a fixed reference.
        print(
            f"  NOTE: {over}\n"
            "  Not failing: the budget is CI-referenced and this is not CI. Compare "
            "against your own machine before reading anything into it.",
        )
        return True

    print(f"FAIL: {over}", file=sys.stderr)
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
    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"

    modules, cumulative_us = run_import_probe(DAEMON_ENTRYPOINT)

    if args.record_baseline:
        write_baseline(current, cumulative_us)
        print(f"Baseline recorded to {BASELINE_FILE.relative_to(ROOT)}.")
        return 0

    # Growth is judged against the base branch's baseline when we can reach it, so a PR
    # cannot excuse a new dependency by rewriting the baseline in the same commit.
    growth_baseline = baseline
    if is_pull_request:
        from_base = baseline_at_base_ref()
        if from_base is not None:
            growth_baseline = from_base
        else:
            print(
                "  NOTE: could not read the baseline from the base branch — comparing "
                "against the one in this checkout, which this PR is able to edit.",
            )

    ok = check_growth(current, growth_baseline, is_pull_request=is_pull_request)
    ok &= check_extras_covered(declared_extras())
    ok &= check_eager_imports(modules)
    ok &= check_import_time(cumulative_us, baseline, enforced=in_ci)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
