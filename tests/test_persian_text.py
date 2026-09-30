"""Conservative Persian Unicode normalisation (FA-02, `design/specs/persian-text-and-rtl.md`).

The pure module is tested directly; the factory wiring is tested through
`_with_persian_normaliser` with a stub engine, so nothing here needs a model.
Every minimum unit case from spec §12 is represented, plus the two properties
the spec demands of the whole pipeline: idempotence, and that Latin runs and
technical spans survive byte-for-byte.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from yazses.config import SttConfig
from yazses.postprocess.persian_text import (
    ALEF_MAKSURA,
    ARABIC_KAF,
    ARABIC_YEH,
    CANONICAL_MAPPINGS,
    PERSIAN_KEHEH,
    PERSIAN_YEH,
    ZWNJ,
    build_persian_normaliser,
    contains_arabic,
    normalise_persian,
    strip_bidi_controls,
)
from yazses.stt.factory import _with_persian_normaliser

RLE, PDF, LRO, RLO = "\u202B", "\u202C", "\u202D", "\u202E"
LRI, PDI = "\u2066", "\u2069"


class _Stub:
    """Engine stub recording what the pipeline fed it."""

    name = "stub"

    def __init__(self) -> None:
        self.transcript = "كتاب علي"

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return self.transcript

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None,
                         task=None):
        @dataclasses.dataclass
        class _W:
            text: str

        return self.transcript, [_W("كتاب"), _W("علي")]

    def decode_window(self, audio):
        return "ك ي ى"


# ── §3 canonical mappings: data table, isolated + sentence context ──────────


def test_table_is_data_and_covers_the_spec():
    assert CANONICAL_MAPPINGS == {
        ARABIC_YEH: PERSIAN_YEH,
        ALEF_MAKSURA: PERSIAN_YEH,
        ARABIC_KAF: PERSIAN_KEHEH,
    }


@pytest.mark.parametrize("src,dst", sorted(CANONICAL_MAPPINGS.items()))
def test_mapping_isolated(src, dst):
    assert normalise_persian(src) == dst


@pytest.mark.parametrize(
    ("word", "want"),
    [
        ("كتاب", "کتاب"),   # Arabic Kaf mid-word
        ("علي", "علی"),     # Arabic Yeh final position
        ("مي", "می"),       # Arabic Yeh after prefix m-
        ("ى", "ی"),         # Alef Maksura standalone
    ],
)
def test_mapping_in_sentence_context(word, want):
    sentence = f"من {word} را خواندم"
    assert normalise_persian(sentence) == f"من {want} را خواندم"


# ── §4 Unicode normalisation ────────────────────────────────────────────────


def test_nfc_composes_alef_hamza():
    # alef + combining hamza above has a composed form; NFC may fuse it.
    assert normalise_persian("\u0627\u0654") == "\u0623"


def test_combining_mark_without_composed_form_survives():
    # alef + fatha has no composed form; the mark must still be there.
    out = normalise_persian("\u0627\u064E")
    assert "\u064E" in out


def test_nfkc_never_applied():
    # U+FDFA (SALLALLAHOU ALAYHE WASALLAM ligature) would explode under NFKC;
    # NFC-only leaves it as the single code point it is.
    lig = "\uFDFA"
    assert normalise_persian(lig) == lig and len(normalise_persian(lig)) == 1


# ── §5 ZWNJ ─────────────────────────────────────────────────────────────────


def test_meaningful_zwnj_preserved():
    assert normalise_persian("می\u200cخواهم خانه\u200cها") == "می\u200cخواهم خانه\u200cها"


@pytest.mark.parametrize("repeat", [2, 3, 5])
def test_repeated_zwnj_collapses_to_one(repeat):
    assert normalise_persian("می" + ZWNJ * repeat + "خواهم") == "می\u200cخواهم"


def test_boundary_zwnj_removed():
    assert normalise_persian(ZWNJ + "سلام" + ZWNJ) == "سلام"


def test_spaces_never_become_zwnj():
    assert normalise_persian("می خواهم") == "می خواهم"


# ── §6 bidi controls ────────────────────────────────────────────────────────


@pytest.mark.parametrize("control", [RLE, PDF, LRO, RLO, LRI, PDI])
def test_bidi_controls_stripped(control):
    assert strip_bidi_controls(f"a{control}b") == "ab"


def test_rlo_hidden_text_is_defused():
    # An RLO/PDF pair can render hidden bytes as their mirror; the whole
    # control family comes out, including around command-looking text.
    assert normalise_persian(f"{RLO}--evil{PDF}") == "--evil"


def test_zwnj_is_not_a_bidi_control():
    assert strip_bidi_controls(f"a{ZWNJ}b") == f"a{ZWNJ}b"


def test_control_hidden_inside_url_is_still_stripped():
    # §6's security note: overrides around URLs must not survive just because
    # the URL is a protected span. Spans are protected from *normalisation*,
    # never from the audited control strip.
    assert normalise_persian(f"https://ex.com/{RLE}x{PDF}") == "https://ex.com/x"


# ── §7 digits, §8 punctuation: preserve what the model emitted ──────────────


def test_digit_blocks_untouched():
    mixed = "۱۲۳ 456 ٤٥٦"
    assert normalise_persian(mixed) == mixed


def test_persian_punctuation_untouched():
    mixed = "، ؛ ؟ » «"
    assert normalise_persian(mixed) == mixed


# ── §9 mixed Persian/English: protected spans stay byte-for-byte ────────────


@pytest.mark.parametrize(
    "fixture",
    [
        "من از VS Code استفاده میکنم.",
        "ایمیل من name@example.com است.",
        "فایل در /home/user/project قرار دارد.",
        "نسخه Python 3.13 را نصب کن.",
        "برو به https://example.com/actually مراجعه کنید",
        "سایت www.example.com را ببین",
        "فایل C:\\Users\\ali\\doc.txt را باز کن",
    ],
)
def test_spec9_fixtures_survive(fixture):
    assert normalise_persian(fixture) == fixture


def test_contaminated_letter_inside_url_is_documentedly_untouched():
    # The mapping cannot reach into a URL — fixing it there would rewrite an
    # identifier. This is the spec's own trade-off (§3/§9) and it is pinned so
    # a future "smarter" version has to argue against a failing test first.
    url = "https://example.com/كتاب"
    assert normalise_persian(url) == url


def test_mixed_line_letters_fixed_but_identifiers_intact():
    src = "كتاب Python و نسخه 3.13"
    out = normalise_persian(src)
    assert out == "کتاب Python و نسخه 3.13"


def test_no_latin_run_deletion_property():
    corpus = ("كتاب و qepd و کتاب و VS Code و name@example.com و 1.2.3. " * 20)
    out = normalise_persian(corpus)
    assert re.findall(r"[A-Za-z]{2,}", out) == re.findall(r"[A-Za-z]{2,}", corpus)


# ── §12: emoji, empty/whitespace, 5,000+ character text ────────────────────


def test_emoji_run_preserved():
    assert normalise_persian("سلام 🙏 دنیا 🚀") == "سلام 🙏 دنیا 🚀"


@pytest.mark.parametrize("empty", ["", "   ", "\n\t "])
def test_empty_and_whitespace_passthrough(empty):
    assert normalise_persian(empty) == empty


def test_long_text_idempotent_and_stable():
    text = ("این یک متن طولانی است؛ كتاب و قلم و VS Code و name@example.com. "
            "همه\u200cچیز سالم است. ") * 65
    assert len(text) >= 5000
    once = normalise_persian(text)
    assert normalise_persian(once) == once          # idempotence
    assert len(once) == len(text)                   # nothing dropped
    assert "كتاب" not in once and "کتاب" in once    # the mapping did run


# ── the gate: inactive profile is passthrough, active is scoped ────────────


class _Cfg:
    def __init__(self, language):
        self.language = language


@pytest.mark.parametrize("lang", ["fa", "FA", "fas", "fa-ir", "persian"])
def test_gate_active_for_persian_codes(lang):
    assert build_persian_normaliser(_Cfg(lang)) is not None


@pytest.mark.parametrize("lang", ["en", "de", "zh", "", None])
def test_gate_inactive_is_none(lang):
    assert build_persian_normaliser(_Cfg(lang)) is None


def test_gate_on_english_burst_is_unchanged():
    assert build_persian_normaliser(_Cfg("fa"))("hello world") == "hello world"


def test_gate_strips_hidden_control_even_in_english_burst():
    # Policy §6 is global once the profile is on: a control in model output is
    # adversarial regardless of which script surrounds it.
    assert build_persian_normaliser(_Cfg("fa"))(f"hello {RLE}world") == "hello world"


def test_gate_fast_path_skips_normalisation_without_arabic():
    # A Latin burst must not be reshaped: ZWNJ rules are Persian orthography
    # (§5) and do not apply to English text under an active profile.
    assert build_persian_normaliser(_Cfg("fa"))("a" + ZWNJ + "b") == "a" + ZWNJ + "b"


def test_contains_arabic_fast_path():
    assert contains_arabic("سلام")
    assert not contains_arabic("hello world")


# ── factory wiring: one chokepoint, zero wrapper when off ──────────────────


def test_factory_returns_engine_untouched_for_english_default():
    engine = _Stub()
    assert _with_persian_normaliser(engine, SttConfig()) is engine


def test_factory_wraps_for_fa_and_normalises_all_surfaces():
    stub = _Stub()
    wrapped = _with_persian_normaliser(stub, SttConfig(language="fa"))
    assert wrapped is not stub
    assert wrapped.transcribe(None) == "کتاب علی"
    text, words = wrapped.transcribe_words(None)
    assert text == "کتاب علی"
    assert [w.text for w in words] == ["کتاب", "علی"]
    assert wrapped.decode_window(None) == "ک ی ی"


def test_wrapper_delegates_unknown_attributes():
    assert _with_persian_normaliser(_Stub(), SttConfig(language="fa")).name == "stub"


def test_stack_with_han_script_does_not_interfere():
    # fa language + a (nonsensical but possible) chinese_script setting: the
    # Han wrapper passes Persian text through its own fast path untouched.
    from yazses.stt.factory import _with_han_script

    cfg = SttConfig(language="fa", chinese_script="simplified")
    engine = _with_persian_normaliser(_with_han_script(_Stub(), cfg), cfg)
    assert engine.transcribe(None) == "کتاب علی"
