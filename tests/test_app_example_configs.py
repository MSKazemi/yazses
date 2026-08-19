"""The per-app example configs must be loadable, not just parseable (#43).

`examples/config.toml` is generated and guarded by `test_example_config.py`.
The per-app profiles next to it — `config.vscode.toml`, `config.kitty.toml`,
and the rest — are hand-written by contributors, one per PR, and until this
file nothing checked them at all.

That matters more than it sounds. These are copied verbatim by newcomers, and
the loader is deliberately total (#52): an unknown key or a mistyped value is
dropped and recorded as a `ConfigProblem`, never raised. So a profile naming a
setting that does not exist — or putting a real setting under the wrong
section — installs cleanly, starts cleanly, and silently does nothing.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

from yazses.config import load_config_checked

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

# config.toml is the generated one; test_example_config.py owns it.
APP_CONFIGS = sorted(p for p in EXAMPLES.glob("config.*.toml") if p.name != "config.toml")

# The exemption list and the marker words live in the checker script, not here.
# That script is the one a contributor runs before opening the PR — and on a fork PR
# from a first-time contributor it is the *only* one that runs, because every real
# workflow is held at `action_required` until a maintainer clears it. Two copies of
# this list would drift, and the copy that reaches the contributor is the one that
# matters, so this reads that one.
_CHECKER = ROOT / "scripts" / "check-app-profile.py"
_spec = importlib.util.spec_from_file_location("check_app_profile", _CHECKER)
assert _spec and _spec.loader
check_app_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_app_profile)

GENERIC_EXAMPLES = check_app_profile.GENERIC_EXAMPLES
EVIDENCE_MARKERS = check_app_profile.EVIDENCE_MARKERS

APP_PROFILES = [p for p in APP_CONFIGS if p.name not in GENERIC_EXAMPLES]


def test_there_are_app_configs_to_check():
    """Guards the glob: an empty parametrize list passes silently."""
    assert APP_CONFIGS, f"no examples/config.<app>.toml found under {EXAMPLES}"


@pytest.mark.parametrize("path", APP_CONFIGS, ids=lambda p: p.name)
def test_it_is_valid_toml(path: Path):
    tomllib.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", APP_CONFIGS, ids=lambda p: p.name)
def test_it_loads_with_no_config_problems(path: Path):
    """Every key must reach a real field on a real section.

    `load_config` never raises, so this is the only place a typo in a
    contributed profile can be caught.
    """
    problems = load_config_checked(path).problems
    assert not problems, "\n".join(
        [f"{path.name} would not load cleanly:"] + [f"  - {p}" for p in problems]
    )


@pytest.mark.parametrize("path", APP_CONFIGS, ids=lambda p: p.name)
def test_it_explains_itself(path: Path):
    """An app profile with no prose is a config dump.

    The point of these files is *why* a setting suits that app, not the
    settings themselves — a newcomer can already get those from
    `examples/config.toml`.
    """
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#"), f"{path.name} does not open with a comment header"
    assert text.endswith("\n"), f"{path.name} has no trailing newline"


def test_the_generic_examples_still_exist():
    """Pins the exemption list against a rename.

    If one of these files is renamed the entry becomes dead weight, and the reason
    written beside it stops being true of anything.
    """
    missing = sorted(n for n in GENERIC_EXAMPLES if not (EXAMPLES / n).exists())
    assert not missing, f"exempted example(s) no longer exist: {missing}"


def test_there_are_app_profiles_to_check():
    """Guards the filter above: an empty parametrize list passes silently."""
    assert APP_PROFILES, "every example was treated as generic -- the evidence guard is blind"


@pytest.mark.parametrize("path", APP_PROFILES, ids=lambda p: p.name)
def test_it_records_what_was_observed(path: Path):
    """An app profile must say what was seen, not what should work.

    Every check above this one passes just as happily on a *plausible* profile as
    on a real one: valid TOML, real keys, real values, and a comment header can all
    be produced without the application ever being opened. That is the failure the
    task issues warn about in as many words -- "a generated config that nobody
    tested is worse than none, because the next person trusts it" -- and until this
    test nothing in the gate could tell the two apart.

    It still cannot tell them apart, and should not be read as if it could: a
    marker word is cheap to add. What it does is make the requirement mechanical
    and visible at review time instead of remembered, the same job the header check
    does. All 14 app profiles already met it when it was written.
    """
    assert check_app_profile.records_evidence(path.read_text(encoding="utf-8")), (
        f"{path.name} never says what was observed in the running application. "
        f"Record it in a comment -- what you dictated and what arrived, as the "
        f"other profiles do -- using one of: {', '.join(EVIDENCE_MARKERS)}."
    )


def test_the_evidence_check_can_actually_fail(tmp_path: Path):
    """Red-green guard: a schema-clean but unevidenced profile must be rejected.

    Modelled on a real one. PR #309 proposed an `examples/config.logseq.toml` whose
    every section was invented, so it was caught earlier by the TOML and schema
    checks; this is the same file after those two are satisfied, which is what the
    next attempt looks like.
    """
    plausible = tmp_path / "config.plausible.toml"
    plausible.write_text(
        "# examples/config.plausible.toml\n"
        "# A YazSes setup for dictating into Plausible.\n\n"
        '[hotkey]\nkey = "right_ctrl"\n',
        encoding="utf-8",
    )
    assert not load_config_checked(plausible).problems, "fixture should be schema-clean"
    assert not check_app_profile.records_evidence(plausible.read_text(encoding="utf-8")), (
        "a profile with no observation passed the evidence check -- the guard above is inert"
    )


def test_an_unresolved_todo_does_not_count_as_evidence(tmp_path: Path):
    """The scaffold must not satisfy the check that exists to reject scaffolds.

    Taken verbatim from the review on PR #309, which handed the contributor a starter
    file headed `TODO(you): replace this block with what you actually observed.` The
    word "observed" in that instruction satisfied the evidence check on its own, so the
    likeliest next submission would have passed by quoting the instruction to fill it in
    — the guard endorsing exactly the file it was written to catch.
    """
    scaffold = tmp_path / "config.scaffold.toml"
    scaffold.write_text(
        "# examples/config.scaffold.toml\n"
        "# A YazSes setup for dictating into Scaffold.\n"
        "#\n"
        "# TODO(you): replace this block with what you actually observed.\n\n"
        '[hotkey]\nkey = "right_ctrl"\n',
        encoding="utf-8",
    )
    assert not check_app_profile.records_evidence(scaffold.read_text(encoding="utf-8"))


def test_a_todo_beside_real_evidence_is_still_accepted(tmp_path: Path):
    """Saying what you did *not* test is the point of these files, not a defect.

    The rule above skips TODO lines rather than rejecting a file that contains one:
    "half a measurement, honestly labelled, is worth more than a whole one asserted"
    is the standard these profiles are held to, and a blanket ban would punish exactly
    the contributor who follows it.
    """
    honest = tmp_path / "config.honest.toml"
    honest.write_text(
        "# examples/config.honest.toml\n"
        '# Measured: dictated "kubectl get pods --namespace prod", arrived exact.\n'
        "# TODO: not tested on Wayland.\n\n"
        '[hotkey]\nkey = "right_ctrl"\n',
        encoding="utf-8",
    )
    assert check_app_profile.records_evidence(honest.read_text(encoding="utf-8"))


def test_a_true_marker_about_the_wrong_subject_still_passes(tmp_path: Path):
    """The guard's known limit, pinned deliberately so nobody "fixes" it into a worse one.

    PR #309 satisfied the evidence check with *"Verified: this file parses with Python's
    tomllib"* while its own header said injection into the app was never run. The marker
    is truthful; it just answers a question the guard was never worried about. So this
    file passes, and that is **accepted**, not an oversight.

    It is accepted because every prose rule that would catch it was measured against the
    directory first and is worse:

    - requiring the conventional ``dictated:``/``arrived:`` pair -- **only 5 of the 14
      app profiles carry both**, so it turns `main` red on nine contributors' files;
    - blacklisting negative phrases ("not verified", "unmeasured") -- **8 of the 14 carry
      an honest caveat of their own**, so it spares them only by an accident of wording
      and **punishes candour**: the most forthright submission is rejected for saying so
      while a silent omission sails through.

    Whether a profile was really run is a human review call. If that ever changes, it
    changes structurally -- a machine-checkable observed pair plus normalising the nine
    merged files -- not by adding another word to a keyword list. Deleting this test is
    the signal that the decision was revisited.
    """
    parses = tmp_path / "config.parses.toml"
    parses.write_text(
        "# examples/config.parses.toml\n"
        "# A YazSes setup for dictating into Parses.\n"
        "#\n"
        "# Verified: this file parses with Python's tomllib.\n"
        "# Injection into the app itself has not been tried.\n\n"
        '[hotkey]\nkey = "right_ctrl"\n',
        encoding="utf-8",
    )
    assert not load_config_checked(parses).problems, "fixture should be schema-clean"
    assert check_app_profile.records_evidence(parses.read_text(encoding="utf-8")), (
        "the fixture no longer reproduces the #309 shape -- if a marker about a parse is "
        "now rejected, the guard changed and this decision needs re-reading, not deleting"
    )


def test_the_evidence_guard_does_not_claim_to_know_the_profile_was_run(tmp_path: Path):
    """The docstring said "Does this profile say what was observed" -- it cannot know that.

    An overclaiming docstring is how the limit above gets mistaken for a bug and
    "fixed" by whoever reads the function next. Pinned to the words that matter.
    """
    doc = check_app_profile.records_evidence.__doc__ or ""
    assert "schema" in doc.lower()
    assert "human review" in doc.lower()
    assert "#309" in doc


def test_the_problem_check_can_actually_fail(tmp_path: Path):
    """Red-green guard for the assertion above.

    `load_config_checked` reporting nothing is exactly what a passing profile
    looks like, so a version of this suite that could never fail would be
    indistinguishable from one that works.
    """
    bogus = tmp_path / "config.bogus.toml"
    bogus.write_text('[stt]\nnot_a_real_key = "x"\n', encoding="utf-8")
    assert load_config_checked(bogus).problems, (
        "an unknown key produced no ConfigProblem — the profile check above is inert"
    )
