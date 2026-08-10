"""The dependency-budget gate (`scripts/check_dependency_budget.py`).

This script decides whether a PR may merge, so its own failure modes matter more than
most: a gate that passes when it cannot measure anything is worse than no gate, because
the green check says the opposite. These tests pin the decisions, not the wording.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_dependency_budget.py"


@pytest.fixture(scope="module")
def cdb():
    spec = importlib.util.spec_from_file_location("check_dependency_budget", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _baseline(names, budget_us=500_000):
    return {"base_dependencies": list(names), "import_time_budget_us": budget_us}


# --- check 1: base dependency growth ----------------------------------------------


def test_unchanged_dependencies_pass(cdb):
    base = ["numpy", "typer"]
    assert cdb.check_growth(base, _baseline(base), is_pull_request=True) is True


def test_new_dependency_fails_a_pr_without_the_label(cdb, monkeypatch):
    monkeypatch.setenv("PR_LABELS", "")
    assert cdb.check_growth(
        ["numpy", "typer", "six"], _baseline(["numpy", "typer"]), is_pull_request=True
    ) is False


def test_new_dependency_passes_with_the_override_label(cdb, monkeypatch):
    monkeypatch.setenv("PR_LABELS", f"documentation,{cdb.OVERRIDE_LABEL}")
    assert cdb.check_growth(
        ["numpy", "typer", "six"], _baseline(["numpy", "typer"]), is_pull_request=True
    ) is True


def test_new_dependency_only_warns_outside_a_pr(cdb, monkeypatch):
    # A push to main has no label to check against; a red default branch for a baseline
    # nobody bumped yet helps nobody.
    monkeypatch.setenv("PR_LABELS", "")
    assert cdb.check_growth(
        ["numpy", "six"], _baseline(["numpy"]), is_pull_request=False
    ) is True


def test_dependency_names_compare_case_and_separator_insensitively(cdb, monkeypatch):
    # PEP 503: `Pillow`, `pillow` and `pil_low`-style spellings are one distribution.
    # Without normalisation a rename in pyproject reads as one addition plus one
    # removal, and the addition fails the PR for no reason.
    monkeypatch.setenv("PR_LABELS", "")
    assert cdb.check_growth(
        ["pillow", "typing-extensions"],
        _baseline(["Pillow", "typing_extensions"]),
        is_pull_request=True,
    ) is True


def test_removing_a_dependency_is_never_a_failure(cdb, monkeypatch):
    monkeypatch.setenv("PR_LABELS", "")
    assert cdb.check_growth(["numpy"], _baseline(["numpy", "six"]), is_pull_request=True) is True


# --- the bypass this gate has to survive ------------------------------------------


def test_growth_is_measured_against_the_base_branch_not_the_local_file(cdb, monkeypatch):
    """Adding a dependency *and* re-recording the baseline must still fail.

    Both files move together in one commit, so a baseline read out of the PR's own
    checkout shows no growth and the label requirement becomes decorative.
    """
    monkeypatch.setenv("PR_LABELS", "")
    pr_pyproject = ["numpy", "typer", "six"]
    baseline_in_this_pr = _baseline(pr_pyproject)      # what --record-baseline wrote
    baseline_on_main = _baseline(["numpy", "typer"])   # what main still says

    assert cdb.check_growth(pr_pyproject, baseline_in_this_pr, is_pull_request=True) is True
    assert cdb.check_growth(pr_pyproject, baseline_on_main, is_pull_request=True) is False


def test_base_ref_baseline_is_none_without_a_base_ref(cdb, monkeypatch):
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    assert cdb.baseline_at_base_ref() is None


# --- check 2: eager optional imports ----------------------------------------------


def test_clean_module_list_passes(cdb):
    assert cdb.check_eager_imports(["yazses.core.daemon", "numpy", "typer"]) is True


def test_top_level_optional_import_is_caught(cdb):
    assert cdb.check_eager_imports(["yazses.core.daemon", "mediapipe"]) is False


def test_submodule_of_an_optional_package_is_caught(cdb):
    # The offender is usually `import mediapipe.tasks...`, not the bare package.
    assert cdb.check_eager_imports(["yazses.core.daemon", "mediapipe.tasks.python"]) is False


def test_a_module_merely_prefixed_like_an_extra_is_not_a_false_positive(cdb):
    assert cdb.check_eager_imports(["yazses.core.daemon", "mcpanel", "serialisation"]) is True


def test_every_extra_is_either_mapped_or_exempt(cdb):
    """The check that stops this gate rotting: a new extra must be classified here."""
    assert cdb.check_extras_covered(cdb.declared_extras()) is True


def test_an_unmapped_extra_fails(cdb):
    assert cdb.check_extras_covered(["gaze", "some-new-extra"]) is False


def test_exempt_extras_carry_a_stated_reason(cdb):
    for extra, reason in cdb.EXEMPT_EXTRAS.items():
        assert reason.strip(), f"{extra} is exempt with no reason given"


def test_the_real_pyproject_extras_are_all_classified(cdb):
    # Guards the mapping against pyproject drift directly, not through the printout.
    unknown = [
        e for e in cdb.declared_extras()
        if e not in cdb.EXTRA_MODULES and e not in cdb.EXEMPT_EXTRAS
    ]
    assert unknown == [], f"extras with no entry in EXTRA_MODULES/EXEMPT_EXTRAS: {unknown}"


# --- check 3: cold-start import time ----------------------------------------------


def test_within_budget_passes(cdb):
    assert cdb.check_import_time(400_000, _baseline([], 500_000)) is True


def test_inside_tolerance_passes(cdb):
    # 1.5x tolerance: 700ms against a 500ms budget is noise, not a regression.
    assert cdb.check_import_time(700_000, _baseline([], 500_000)) is True


def test_over_tolerance_fails_in_ci(cdb):
    assert cdb.check_import_time(900_000, _baseline([], 500_000), enforced=True) is False


def test_over_tolerance_only_warns_off_ci(cdb):
    # The budget is one number from one `ubuntu-latest` runner. A contributor's laptop
    # is not that machine, and the failure text tells them to --record-baseline, which
    # would overwrite the shared budget with a local measurement.
    assert cdb.check_import_time(900_000, _baseline([], 500_000), enforced=False) is True


def test_no_recorded_budget_is_not_a_failure(cdb):
    assert cdb.check_import_time(900_000, {"base_dependencies": []}) is True


def test_unparseable_importtime_output_fails_instead_of_reading_as_zero(cdb, monkeypatch):
    """`-X importtime` output is a CPython implementation detail, not an API.

    If its format moves, every line is skipped and the probe returns nothing. Reporting
    that as 0us would put check 3 permanently "within budget" and check 2 permanently
    clean — two dead gates behind a green check.
    """
    class _Proc:
        returncode = 0
        stdout = ""
        stderr = "import time: this is not the format we parse\n"

    monkeypatch.setattr(cdb.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(SystemExit) as excinfo:
        cdb._import_probe_once("yazses.core.daemon")
    assert excinfo.value.code == 1


def test_a_failed_import_fails_loudly(cdb, monkeypatch):
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "ModuleNotFoundError: No module named 'mediapipe'"

    monkeypatch.setattr(cdb.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(SystemExit) as excinfo:
        cdb._import_probe_once("yazses.core.daemon")
    assert excinfo.value.code == 1


def test_a_failed_import_reports_the_traceback_not_the_timing_table(cdb, monkeypatch, capsys):
    """`-X importtime` shares stderr with the traceback that explains the failure.

    Printing stderr verbatim buries the one line the contributor needs — the import
    they must move — under every module Python loaded on the way there. This is the
    path someone lands on precisely when they have broken the rule, so it is the
    path that can least afford to be unreadable.
    """
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = (
            "import time:       335 |        335 |   _io\n"
            "import time:      1437 |       2287 | _frozen_importlib_external\n"
            "Traceback (most recent call last):\n"
            "ModuleNotFoundError: No module named 'mediapipe'\n"
        )

    monkeypatch.setattr(cdb.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(SystemExit):
        cdb._import_probe_once("yazses.core.daemon")

    err = capsys.readouterr().err
    assert "No module named 'mediapipe'" in err
    assert "_frozen_importlib_external" not in err, "timing table leaked into the failure"


def test_a_failure_with_nothing_but_timings_still_says_something(cdb, monkeypatch, capsys):
    """Stripping the table must not leave an empty failure message."""
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "import time:       335 |        335 |   _io\n"

    monkeypatch.setattr(cdb.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(SystemExit):
        cdb._import_probe_once("yazses.core.daemon")
    assert "_io" in capsys.readouterr().err


# --- parsing ----------------------------------------------------------------------


def test_dependency_specs_reduce_to_bare_names(cdb):
    names = cdb.base_dependency_names()
    assert names, "pyproject.toml declares no base dependencies"
    for name in names:
        assert not any(c in name for c in "[<>=!~; "), f"{name!r} still carries a spec"


def test_recorded_baseline_matches_pyproject(cdb):
    """The committed baseline is the reference CI compares against — keep it true."""
    recorded = {cdb.canonical(n) for n in json.loads(
        cdb.BASELINE_FILE.read_text(encoding="utf-8")
    )["base_dependencies"]}
    current = {cdb.canonical(n) for n in cdb.base_dependency_names()}
    assert recorded == current, (
        "scripts/dependency_budget_baseline.json is out of step with "
        "[project.dependencies] — run `--record-baseline` and commit."
    )
