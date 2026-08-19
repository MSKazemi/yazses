"""`yazses doctor` printed **Microphone** twice, for two different questions.

Run on a real machine:

    [OK] Microphone: ok
    ...
    [OK] Microphone: OS default: default → Raptor Lake-P/U/H cAVS Digital Microphone

Two different questions wearing one name — *can a microphone be reached at all*, a
permission/hardware check, and *which device will be used*, part of the config summary.
That matters more here than in most output: `doctor`'s report is what people paste into
issues, so "Microphone failed" becomes unanswerable without asking which one, and a
reader scanning for a single line finds two.

The config-summary line is now **Input device**.

## Why the obvious guard was wrong

The first version of this file parsed `doctor.py` and flagged any label appearing twice
in the source. It reported eight duplicates that are not duplicates at all: `Config dir`,
`Injection`, `systemd unit` and the rest appear once per branch of an `if`/`else`, and
only one branch ever runs. Counting source occurrences measures the wrong thing.

The real defect was one label shared by two **different** checks, so that is what is
checked: `_config_summary` is called for real — it is hermetic, degrading to "unknown"
with no audio, which is what CI has — and its labels must be unique among themselves and
must not collide with the permission check's.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from yazses.config import Config
from yazses.system.doctor import _config_summary

#: The label the *permission/hardware* check owns. The config summary must not reuse it.
PERMISSION_LABEL = "Microphone"


def _summary_labels(cfg=None) -> list[str]:
    """The config-summary check labels, from the real function."""
    rows = _config_summary(cfg or Config(), Path("/nonexistent/config.toml"))
    return [row[0] for row in rows]


def test_the_summary_really_runs() -> None:
    """A guard over an empty set passes on everything."""
    labels = _summary_labels()
    assert len(labels) >= 4, f"only {len(labels)} summary rows: {labels}"
    assert "Hotkey" in labels


def test_the_device_row_no_longer_borrows_the_permission_label() -> None:
    """The defect itself."""
    labels = _summary_labels()
    assert PERMISSION_LABEL not in labels, (
        f"the config summary emits {PERMISSION_LABEL!r}, the same name the "
        "permission/hardware check uses — doctor prints both and a reader cannot tell "
        "which failed"
    )
    assert "Input device" in labels


def test_the_summary_labels_are_unique_among_themselves() -> None:
    labels = _summary_labels()
    dupes = sorted(label for label, n in Counter(labels).items() if n > 1)
    assert not dupes, f"the config summary prints these twice: {dupes}"


def test_both_device_branches_use_the_new_label() -> None:
    """Pinned and unpinned are separate branches; the rename had to cover both.

    Missing one would be invisible on a machine that happens to take the other path —
    and CI takes the unpinned one, so only the pinned branch is at risk of drifting.
    """
    pinned = Config()
    pinned.audio.device = "Some USB Microphone"
    labels = _summary_labels(pinned)
    assert "Input device" in labels
    assert PERMISSION_LABEL not in labels, "the pinned branch kept the old label"
