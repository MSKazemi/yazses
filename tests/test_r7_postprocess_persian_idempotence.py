"""normalise_persian must be idempotent even when bidi controls hide other rules.

The spec (design/specs/persian-text-and-rtl.md §1, §12) and the function's own
docstring promise idempotence. A bidi control (§6, stripped everywhere) used to
be removed only *after* NFC (§4) and the boundary-ZWNJ strip (§5), so a control
that shielded a boundary ZWNJ, or separated a base letter from a combining
mark, left work for a second pass: ``f(f(x)) != f(x)``. Synthetic inputs only.
"""
from __future__ import annotations

import unicodedata

import pytest

from yazses.postprocess.persian_text import ZWNJ, normalise_persian

LRE, PDI = "‪", "⁩"
HAMZA_ABOVE = "ٔ"
ALEF = "ا"


@pytest.mark.parametrize(
    "text",
    [
        LRE + ZWNJ + "سلام",            # control shields a leading ZWNJ
        "سلام" + ZWNJ + PDI,            # control shields a trailing ZWNJ
        ZWNJ + LRE + ZWNJ + "کتاب",     # ZWNJ, control, ZWNJ at the start
        ALEF + LRE + HAMZA_ABOVE,       # control blocks NFC composition
    ],
)
def test_bidi_control_does_not_break_idempotence(text: str) -> None:
    once = normalise_persian(text)
    assert normalise_persian(once) == once


@pytest.mark.parametrize(
    "text", [LRE + ZWNJ + "سلام", "سلام" + ZWNJ + PDI]
)
def test_boundary_zwnj_removed_even_behind_a_bidi_control(text: str) -> None:
    out = normalise_persian(text)
    assert out == "سلام"
    assert not out.startswith(ZWNJ) and not out.endswith(ZWNJ)


def test_output_is_nfc_after_control_removal() -> None:
    out = normalise_persian(ALEF + LRE + HAMZA_ABOVE)
    assert out == unicodedata.normalize("NFC", out) == "أ"


def test_control_only_and_zwnj_only_inputs_become_empty() -> None:
    assert normalise_persian(LRE + ZWNJ + PDI) == ""
    assert normalise_persian(ZWNJ + ZWNJ) == ""
