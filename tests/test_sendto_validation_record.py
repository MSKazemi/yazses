"""The "never sent" validation record for Send to (ADR-031 §5, issue #637).

ADR-031 §5 makes "the hand-off pre-fills and does not submit" something *observed* per
client and OS, not assumed from the vendors' documentation: a validation row per client
and OS, the client versions it was verified on named by ``features info``, and a target
removed in the next release if a client is ever seen to submit on open.

The rows themselves need a person, a real Claude or Codex install and a desktop, so none
exists yet. What this file pins is the machinery that makes the record honest once they
arrive, all pure and synthetic:

* **the record is one list** -- ``sendto.validation.ROWS`` -- and the human-readable table
  in ADR-031 between the ``sendto-validation`` markers says exactly the same thing, so
  the ADR cannot claim a verification the code does not (or the reverse);
* **a row is complete or it is a defect** -- a known target, a real OS and opener for that
  OS, an ISO date, a client version, a tester and a link to the evidence;
* **a target seen to submit cannot stay in the table** -- ADR-031 §5's removal rule as a
  failing test, not a promise;
* **``features info`` reads the record** -- with no row the card says "Not yet verified",
  and a verified row puts the client version on the card, derived, never hand-written;
* **an outcome that is not "pre-filled, not submitted" verifies nothing** -- a client that
  did not open, or opened with an empty box, is a recorded result but not a verification.

NOT shown here: any real client's behaviour. That is the human half of #637.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from yazses.config import Config
from yazses.sendto import validation
from yazses.sendto.targets import TARGETS
from yazses.sendto.validation import (
    OPENERS_BY_OS,
    REMOVED_TARGETS,
    ROWS,
    Outcome,
    ValidationRow,
    row_problems,
    submitted_targets,
    verification_sentence,
    verified_rows,
)
from yazses.system.features import feature_status

ROOT = Path(__file__).resolve().parents[1]
ADR_031 = ROOT / "design" / "adr" / "adr-031-send-to-prefill-handoff.md"
START = "<!-- sendto-validation:start -->"
END = "<!-- sendto-validation:end -->"


def _row(**overrides: object) -> ValidationRow:
    fields: dict[str, object] = dict(
        target="claude",
        os="linux",
        environment="Ubuntu 24.04, GNOME 46, Wayland",
        client_version="Claude 0.0.0-synthetic",
        yazses_version="2.50.0",
        opener="portal",
        date="2026-11-06",
        outcome=Outcome.PREFILLED_NOT_SUBMITTED,
        tester="synthetic tester",
        evidence="https://github.com/MSKazemi/yazses/issues/637",
    )
    fields.update(overrides)
    return ValidationRow(**fields)  # type: ignore[arg-type]


def _feature():
    found = [f for f in feature_status(Config()) if f.slug == "sendto"]
    assert len(found) == 1
    return found[0]


# --- the shipped record ------------------------------------------------------------------


def test_the_shipped_record_has_no_problems() -> None:
    assert row_problems(ROWS, frozenset(TARGETS)) == []


def test_no_target_in_the_table_has_been_seen_to_submit() -> None:
    """ADR-031 §5: a client observed to submit on open loses its target next release."""
    still_offered = submitted_targets(ROWS) & set(TARGETS)
    assert not still_offered, (
        f"{sorted(still_offered)} submitted the prompt on open in a validation run; "
        "remove the target from sendto/targets.py::TARGETS and say why in the release notes"
    )


def _adr_table_rows() -> list[list[str]]:
    text = ADR_031.read_text(encoding="utf-8")
    assert text.count(START) == 1 and text.count(END) == 1, "ADR-031 lost its record markers"
    block = text.split(START, 1)[1].split(END, 1)[0]
    lines = [ln.strip() for ln in block.splitlines() if ln.strip().startswith("|")]
    assert len(lines) >= 2, "the record table has no header"
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    assert header == list(validation.TABLE_COLUMNS), header
    assert re.fullmatch(r"\|(\s*-+\s*\|)+", lines[1]), "second line must be the separator"
    return [[c.strip() for c in ln.strip("|").split("|")] for ln in lines[2:]]


def test_the_adr_table_is_the_code_record() -> None:
    """The ADR's human-readable table and ``ROWS`` say the same thing, row for row."""
    assert _adr_table_rows() == [list(r.table_cells()) for r in ROWS]


def test_an_empty_record_says_so_in_the_adr() -> None:
    if ROWS:
        pytest.skip("the record has rows")
    block = ADR_031.read_text(encoding="utf-8").split(START, 1)[1].split(END, 1)[0]
    assert "No row yet" in block


# --- row validation ----------------------------------------------------------------------


def test_a_complete_row_has_no_problems() -> None:
    assert row_problems((_row(),), frozenset(TARGETS)) == []


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"target": "gemini"}, "unknown target"),
        ({"os": "freebsd"}, "unknown os"),
        ({"opener": "nsworkspace"}, "opener"),
        ({"date": "06/11/2026"}, "date"),
        ({"date": "2026-02-30"}, "date"),
        ({"client_version": " "}, "client_version"),
        ({"environment": ""}, "environment"),
        ({"yazses_version": ""}, "yazses_version"),
        ({"tester": ""}, "tester"),
        ({"evidence": ""}, "evidence"),
        ({"evidence": "see chat"}, "evidence"),
        ({"evidence": "https://"}, "evidence"),
        ({"evidence": "https:///issues/637"}, "evidence"),
        ({"client_version": "Claude 1.0 | 2.0"}, "|"),
        ({"environment": "Ubuntu 24.04\nGNOME 46"}, "line break"),
        ({"tester": "someone\r"}, "line break"),
    ],
)
def test_an_incomplete_row_is_a_problem(override, fragment) -> None:
    problems = row_problems((_row(**override),), frozenset(TARGETS))
    assert problems, f"{override} was accepted"
    assert any(fragment in p for p in problems), problems


def test_a_removed_target_may_keep_its_submitted_row_as_history() -> None:
    """Once a submitting target is removed, its row stays as the reason why -- but only
    because the removal itself is written down in ``REMOVED_TARGETS``."""
    row = _row(target="claude", outcome=Outcome.SUBMITTED)
    problems = row_problems(
        (row,), frozenset({"claude-code", "codex"}), removed_targets=frozenset({"claude"})
    )
    assert problems == []
    assert submitted_targets((row,)) == frozenset({"claude"})


@pytest.mark.parametrize("slug", ["claud", "Claude", "claude code", "CODEX", " codex"])
def test_a_submitted_row_must_name_a_real_target(slug) -> None:
    """A mistyped slug on a ``submitted`` row would switch off the removal rule.

    ``submitted_targets`` compares slugs exactly, so a ``submitted`` row for ``claud``
    leaves ``claude`` in ``TARGETS`` and the removal test green. The row is a defect
    instead: it names a live target (and the removal test catches it) or a target that
    was deliberately removed.
    """
    row = _row(target=slug, outcome=Outcome.SUBMITTED)
    problems = row_problems((row,), frozenset(TARGETS))
    assert any("unknown target" in p for p in problems), problems


def test_a_submitted_row_for_a_live_target_fails_the_removal_rule() -> None:
    """The case the removal test exists for: the slug is right, so it is caught there."""
    row = _row(target="claude", outcome=Outcome.SUBMITTED)
    assert row_problems((row,), frozenset(TARGETS)) == []
    assert submitted_targets((row,)) & set(TARGETS) == {"claude"}


def test_removed_targets_are_not_live_targets() -> None:
    """A slug is either offered or removed, never both."""
    assert not REMOVED_TARGETS & set(TARGETS)


def test_every_removed_target_has_the_submitted_row_that_removed_it() -> None:
    """§5 removes a target only for a run seen to submit; the record must show that run."""
    missing = REMOVED_TARGETS - submitted_targets(ROWS)
    assert not missing, f"{sorted(missing)} removed with no submitted row in ROWS"


def test_a_removed_target_cannot_carry_a_verification() -> None:
    row = _row(target="claude")
    problems = row_problems((row,), frozenset({"claude-code", "codex"}))
    assert any("unknown target" in p for p in problems)


@pytest.mark.parametrize("os_name", sorted(OPENERS_BY_OS))
def test_every_os_has_its_own_openers(os_name) -> None:
    for opener in OPENERS_BY_OS[os_name]:
        assert row_problems((_row(os=os_name, opener=opener),), frozenset(TARGETS)) == []


def test_the_openers_are_the_seam_s_real_paths() -> None:
    """Each OS lists the paths its UrlOpener can take (ADR-031 implementation notes)."""
    assert OPENERS_BY_OS == {
        "linux": ("portal", "xdg-open"),
        "macos": ("nsworkspace", "open"),
        "windows": ("shellexecute",),
    }


# --- what `features info` says -----------------------------------------------------------


def test_no_rows_means_not_yet_verified() -> None:
    sentence = verification_sentence(())
    assert sentence == "Not yet verified against any real Claude or Codex app."


@pytest.mark.parametrize(
    "outcome", [Outcome.DID_NOT_OPEN, Outcome.NOT_PREFILLED, Outcome.SUBMITTED]
)
def test_only_prefilled_and_not_submitted_verifies(outcome) -> None:
    rows = (_row(outcome=outcome),)
    assert verified_rows("claude", rows) == ()
    assert verification_sentence(rows).startswith("Not yet verified")


def test_a_verified_row_names_the_client_version_and_the_os() -> None:
    rows = (_row(), _row(target="codex", client_version="Codex 9.9-synthetic", os="linux"))
    sentence = verification_sentence(rows)
    assert "Claude 0.0.0-synthetic" in sentence
    assert "Codex 9.9-synthetic" in sentence
    assert "Linux" in sentence
    assert "Not yet verified: Claude Code." in sentence
    # The guard in test_sendto_feature_registry.py forbids this phrase while there are
    # no rows; once there are, it is the phrase §5 asks for.
    assert sentence.startswith("Verified pre-filled and not sent on ")


def test_verified_rows_are_per_target() -> None:
    rows = (_row(), _row(target="codex"))
    assert [r.target for r in verified_rows("claude", rows)] == ["claude"]
    assert verified_rows("claude-code", rows) == ()


def test_the_feature_card_reads_the_record() -> None:
    """The card's verification sentence is derived from ROWS, not written by hand."""
    assert verification_sentence(ROWS) in _feature().why


def test_the_feature_card_follows_a_new_row(monkeypatch) -> None:
    """Adding a row changes what `features info` says, with no other edit."""
    monkeypatch.setattr(validation, "ROWS", (_row(),))
    why = _feature().why
    assert "Verified pre-filled and not sent on " in why
    assert "Claude 0.0.0-synthetic" in why
    assert "Not yet verified against any real" not in why


# --- prose that is true only while the record is empty -----------------------------------

#: Hand-written sentences that say nothing has been tried. Each is true while ``ROWS`` is
#: empty and false once a single run is recorded, so the first row must change every one
#: (and, for the CLI docstring, regenerate the reference: ``scripts/gen-docs.py`` and
#: ``scripts/gen-man.py``).
_EMPTY_RECORD_CLAIMS: tuple[tuple[str, str], ...] = (
    ("src/yazses/cli.py", "Not yet tried against the real desktop apps."),
    ("docs/cli-reference.md", "not yet tried\nagainst the real desktop apps."),
    ("src/yazses/sendto/validation.py", "**It is empty**"),
    ("design/architecture.md", "**empty**, nothing has been tried against a real client"),
    ("design/adr/adr-031-send-to-prefill-handoff.md",
     "**Unverified:** no hand-off has yet been tried against a real Claude or Codex install"),
)


@pytest.mark.parametrize(("rel", "claim"), _EMPTY_RECORD_CLAIMS)
def test_an_empty_record_claim_is_true_exactly_while_the_record_is_empty(rel, claim) -> None:
    text = (ROOT / rel).read_text(encoding="utf-8")
    if ROWS:
        assert claim not in text, (
            f"{rel} still says nothing has been tried, but ROWS has {len(ROWS)} row(s); "
            "rewrite it from the record (and regenerate docs/man if it is the CLI help)"
        )
    else:
        assert claim in text, (
            f"{rel} no longer carries {claim!r}; update _EMPTY_RECORD_CLAIMS so the first "
            "row still has to revisit that sentence"
        )


def test_the_procedure_names_the_regeneration_step() -> None:
    """A new verified row changes generated docs; the ADR procedure must say to rebuild."""
    text = ADR_031.read_text(encoding="utf-8")
    procedure = text.split("**How a row is made", 1)[1].split(START, 1)[0]
    assert "scripts/gen-docs.py" in procedure
    assert "scripts/gen-man.py" in procedure
