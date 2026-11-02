"""Persian text survives every pure text stage between the decoder and the injector.

The contract, for ``[stt] language = "fa"``: a sentence that needs no change comes out of
each stage with the same code points it went in with (compared by ``==`` on ``str``, which
is code-point equality, never a visual comparison). The only stage allowed to rewrite
Persian letters is the opt-in normaliser (``[stt] persian_normalisation``), and it is
tested on its own below.

Stages are the pure functions the dictation path in ``core/daemon.py`` (``_on_hold_end``)
calls, in the order it calls them. Each one is called directly; no daemon is started.
Vectors are written as real Unicode in this file and need no external data.

Where a stage is *designed* to act on some input (a Latin email gets redacted, a URL gets
autolinked, a sentence break gets a newline), that input is tagged and excluded from that
stage's no-change check, so the check only asserts what the stage is supposed to leave alone.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest

from yazses.autopair.balance import balance_delimiters
from yazses.compute.evaluate import evaluate
from yazses.config import DisfluencyConfig, HallucinationConfig, SttConfig
from yazses.convert.units import apply_conversions
from yazses.corrdict.mine import apply_corrections
from yazses.diacritize.restore import restore_diacritics
from yazses.gec.guard import fix_articles
from yazses.itn.normalize import normalize_entities
from yazses.postprocess import phonetic, vocab_correct
from yazses.postprocess.cleaner import clean_text
from yazses.postprocess.hallucination import drop_reason
from yazses.postprocess.output_profile import profile_for
from yazses.postprocess.persian_text import build_persian_normaliser
from yazses.postprocess.spacing import continuation_prefix
from yazses.postprocess.voice_punctuation import apply_voice_punctuation
from yazses.redaction.scrub import redact
from yazses.safeglyph.confusables import scan_confusables
from yazses.selfrepair.repair import apply_self_repair
from yazses.sembr.breaks import semantic_breaks
from yazses.smartpaste.adapt import adapt
from yazses.stt.filters.disfluency import filter_transcript
from yazses.symbols.lookup import apply_symbols
from yazses.temporal.resolve import resolve_temporal
from yazses.translit.scheme import detect_scheme, transliterate

ZWNJ = "\u200c"
_NOW = datetime(2026, 11, 2, 12, 0)
_DISFLUENCY = DisfluencyConfig(enabled=True)
_HALLUCINATION = HallucinationConfig(enabled=True)
_CORRECTIONS = {"yaz says": "YazSes"}
_HOTWORD_VOCAB = ["Kubernetes", "Kianoush", "Sara", "خانم", "کتابی", "علیرضا", "Python", "GitHub", "Docker"]


def _cp(text: str) -> str:
    """Code points of *text*, for failure messages (``U+0628 U+0627 ...``)."""
    return " ".join(f"U+{ord(ch):04X}" for ch in text)


# ── Vectors ──────────────────────────────────────────────────────────────────
# Each vector is (text, tags). Tags name the one behaviour a stage is designed to act on.

Vector = tuple[str, frozenset[str]]


def _v(text: str, *tags: str) -> Vector:
    return (text, frozenset(tags))


PLAIN: list[Vector] = [
    _v("سلام، حال شما چطور است؟"),
    _v("من امروز به کتابخانه رفتم."),
    _v("این کتاب خیلی جالب است؛ حتماً بخوانید."),
    _v("خانه بزرگ است."),
    _v("فردا باران می‌آید، پس چتر بردار."),
]

DIGITS: list[Vector] = [
    _v("امروز ۱۴ آبان ۱۴۰۵ است."),
    _v("قیمت ۱۲۳۴۵ ریال است."),
    _v("عدد ۰ و ۹ را بگو."),
    _v("۱۰+۲"),                      # Persian digits and an operator: no arithmetic answer
    _v("۲۰۲۴-۲۰۲۵"),                # a span of years written in Persian digits
]

ARABIC_INDIC_DIGITS: list[Vector] = [
    _v("قیمت ١٢٣ تومان است."),
    _v("امروز ١٤ آبان ١٤٠٥ است."),
]

PERSIAN_PUNCTUATION: list[Vector] = [
    _v("سلام، دوست من؛ آیا آماده‌ای؟"),
    _v("«کتاب» را بخوان…"),
    _v("یک، دو، سه؛ چهار؟"),
    _v("می‌گوید: «فردا می‌آیم»."),
]

ZWNJ_WORDS: list[Vector] = [
    _v("می‌خواهم کتاب‌ها را بخوانم."),
    _v("نمی‌دانم، شاید فردا بروم."),
    _v("خانه‌ها بزرگ‌اند."),
    _v("کتاب‌خانه‌های شهر را دیدم."),
]

# Arabic-block letters (U+064A Yeh, U+0643 Kaf). Only the opt-in normaliser may change these.
ARABIC_LETTERS: list[Vector] = [
    _v("اين كتاب را بخوان"),
    _v("كتاب‌ها و كتابخانه‌ها"),
]

MIXED_ENGLISH: list[Vector] = [
    _v("من از Python و GitHub استفاده می‌کنم."),
    _v("با Kubernetes و Docker کار می‌کنم."),
    _v("قرار است Ali فردا بیاید."),
    _v("ایمیل من john.doe@example.com است.", "email"),
    _v("آدرس https://example.com/fa را ببین.", "url"),
    _v("فایل را در /home/user/notes.txt ذخیره کن.", "path"),
    _v("در ویندوز C:\\Users\\me\\notes.txt را باز کن.", "path"),
    _v("نسخه ۲.۱.۰ را نصب کن."),
    _v("و/یا را هم بنویس."),                    # the slash is Persian prose, not a path
]

# Reduplication: a legitimate Persian repetition, not a stutter.
REDUPLICATION: list[Vector] = [
    _v("تا تا رسیدم خانه."),
    _v("آرام آرام راه برو."),
    _v("خیلی خیلی خوب است."),
    _v("من خیلی خیلی خوشحالم."),
    _v("آهسته آهسته برو، آرام آرام."),
]

# Proper nouns that a vocabulary corrector could mistake for a neighbouring word.
HOTWORDS: list[Vector] = [
    _v("کیانوش در تهران است."),
    _v("علی و مریم به خانه رفتند."),
    _v("خانم کیانوش، لطفاً بیا."),
    _v("خانه بزرگ است."),
    _v("کتاب را خواندم."),
    _v("سارا و نیما آمدند."),
    _v("مهسا گفت: Kubernetes را نصب کن."),
]

CLOSING_MARKS = ["، بعداً", "؟ بله", "؛ و", "» بعد"]

NO_CHANGE: list[Vector] = (
    PLAIN + DIGITS + ARABIC_INDIC_DIGITS + PERSIAN_PUNCTUATION + ZWNJ_WORDS
    + ARABIC_LETTERS + MIXED_ENGLISH + REDUPLICATION + HOTWORDS
)


# ── Stage table ──────────────────────────────────────────────────────────────


def _compute_stage(text: str) -> str:
    answer = evaluate(text)
    return text if answer is None else answer


def _translit_stage(text: str) -> str:
    scheme = detect_scheme(text, "finglish")
    return text if scheme is None else transliterate(text, scheme)


def _halluc_stage(text: str) -> str:
    rule = drop_reason(text, _HALLUCINATION)
    return text if rule is None else f"<dropped:{rule}>"


def _same_words(out: str, text: str) -> bool:
    """Same code points once whitespace runs are collapsed (for stages that add line breaks)."""
    return " ".join(out.split()) == " ".join(text.split())


# name -> (stage, tags the stage is designed to act on, equivalence check)
Equivalence = Callable[[str, str], bool]
_EXACT: Equivalence = lambda out, text: out == text  # noqa: E731
STAGES: dict[str, tuple[Callable[[str], str], frozenset[str], Equivalence]] = {
    "clean_text": (clean_text, frozenset(), _EXACT),
    "vocab_correct": (lambda s: vocab_correct.correct(s, _HOTWORD_VOCAB)[0], frozenset(), _EXACT),
    # Path segments are rewritten by the phonetic corrector for English too; that case has its
    # own strict xfail below, so it is excluded from the shared table.
    "phonetic_correct": (
        lambda s: phonetic.correct_text(s, _HOTWORD_VOCAB), frozenset({"path"}), _EXACT,
    ),
    "hallucination_guard": (_halluc_stage, frozenset(), _EXACT),
    "disfluency": (lambda s: filter_transcript(s, _DISFLUENCY).text, frozenset(), _EXACT),
    "self_repair": (apply_self_repair, frozenset(), _EXACT),
    "compute": (_compute_stage, frozenset(), _EXACT),
    "corrdict": (lambda s: apply_corrections(s, _CORRECTIONS), frozenset(), _EXACT),
    "voice_punctuation": (apply_voice_punctuation, frozenset(), _EXACT),
    "itn": (normalize_entities, frozenset(), _EXACT),
    "redaction": (lambda s: redact(s, mode="mask").text, frozenset({"email"}), _EXACT),
    "symbols": (apply_symbols, frozenset(), _EXACT),
    "convert": (apply_conversions, frozenset(), _EXACT),
    "temporal": (lambda s: resolve_temporal(s, _NOW), frozenset(), _EXACT),
    "gec": (fix_articles, frozenset(), _EXACT),
    "diacritize": (restore_diacritics, frozenset(), _EXACT),
    "translit": (_translit_stage, frozenset(), _EXACT),
    # Semantic breaks are designed to add line breaks; the contract is that no word changes.
    "sembr": (semantic_breaks, frozenset(), _same_words),
    "autopair": (balance_delimiters, frozenset(), _EXACT),
    "smartpaste": (lambda s: adapt(s, "markdown"), frozenset({"url"}), _EXACT),
}


def _is_checked(stage: str, vector: Vector) -> bool:
    _, designed_for, _ = STAGES[stage]
    return not (vector[1] & designed_for)


_CASES = [
    pytest.param(stage, text, id=f"{stage}-{i}")
    for stage in STAGES
    for i, (text, tags) in enumerate(NO_CHANGE)
    if _is_checked(stage, (text, tags))
]


@pytest.mark.parametrize(("stage", "text"), _CASES)
def test_stage_leaves_persian_that_needs_no_change_untouched(stage: str, text: str) -> None:
    fn, _, equivalent = STAGES[stage]
    out = fn(text)
    assert equivalent(out, text), (
        f"{stage}: input {text!r}\n  -> {out!r}\n  in code points: {_cp(out)}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "src/yazses/postprocess/phonetic.py::correct_text rewrites a path segment "
        "('user' -> 'Sara'). This is English-shaped, not Persian-specific, and fixing it "
        "would change English output, so it is reported rather than fixed in this change."
    ),
)
def test_phonetic_corrector_leaves_a_path_inside_persian_prose_alone() -> None:
    text = "فایل را در /home/user/notes.txt ذخیره کن."
    assert phonetic.correct_text(text, _HOTWORD_VOCAB) == text


# ── Stages that need their own expectation ───────────────────────────────────


@pytest.mark.parametrize("text", CLOSING_MARKS)
def test_persian_closing_marks_hug_the_previous_word(text: str) -> None:
    assert continuation_prefix(text, had_recent_injection=True, previous_tail="ه") == ""


@pytest.mark.parametrize("text", ["می‌خواهم بروم", "کتاب‌ها", "سلام"])
def test_persian_words_keep_their_space_on_continuation(text: str) -> None:
    assert continuation_prefix(text, had_recent_injection=True, previous_tail="ه") == " "


def test_persian_without_zwnj_is_not_flagged_as_confusable() -> None:
    assert scan_confusables("سلام، حال شما چطور است؟") == []


def test_zwnj_between_persian_letters_is_not_flagged_as_confusable() -> None:
    # A ZWNJ between two Persian letters is orthography, not a hidden character.
    assert scan_confusables("می‌خواهم کتاب‌ها را بخوانم.") == []


def test_hallucination_guard_keeps_persian_text_with_an_english_ghost_phrase() -> None:
    # The guard judges a normalised copy with every non-Latin letter removed, so the
    # Persian words vanish and the English tail reads as a whole-transcript ghost phrase.
    text = "این ویدیو را ببین thanks for watching"
    assert drop_reason(text, _HALLUCINATION) is None


def test_hallucination_guard_keeps_persian_text_with_an_english_loop() -> None:
    text = "no no no no روز"
    assert drop_reason(text, _HALLUCINATION) is None


def test_english_ghost_phrase_is_still_dropped() -> None:
    # The English behaviour the guard exists for must not change.
    assert drop_reason("Thanks for watching", _HALLUCINATION) == "ghost_phrase"


def test_english_repetition_loop_is_still_dropped() -> None:
    assert drop_reason("the the the the", _HALLUCINATION) == "repetition_loop"


def test_corrections_do_not_rewrite_part_of_a_zwnj_compound() -> None:
    # "کتاب" is a whole word in "کتاب را" but only the first half of "کتاب‌ها".
    table = {"کتاب": "دفتر"}
    assert apply_corrections("کتاب را بخوان", table) == "دفتر را بخوان"
    assert apply_corrections("کتاب‌ها را بخوان", table) == "کتاب‌ها را بخوان"


def test_corrections_still_match_whole_english_words_only() -> None:
    table = {"cat": "dog"}
    assert apply_corrections("a cat and cats", table) == "a dog and cats"


def test_vocabulary_does_not_rewrite_a_persian_word_to_a_latin_term() -> None:
    assert vocab_correct.correct("خانه بزرگ است", ["Kubernetes", "خانم"])[0] == "خانه بزرگ است"


def test_vocabulary_does_not_rewrite_a_persian_word_to_a_persian_term() -> None:
    assert vocab_correct.correct("کتاب را خواندم", ["کتابی"])[0] == "کتاب را خواندم"


def test_vocabulary_still_recovers_a_latin_term_inside_persian_prose() -> None:
    fixed = vocab_correct.correct("مهسا گفت Kubernetis را نصب کن", ["Kubernetes"])[0]
    assert fixed == "مهسا گفت Kubernetes را نصب کن"


def test_phonetic_corrector_still_recovers_a_latin_term_inside_persian_prose() -> None:
    fixed = phonetic.correct_text("مهسا گفت Kubernetis را نصب کن", ["Kubernetes"])
    assert fixed == "مهسا گفت Kubernetes را نصب کن"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "src/yazses/stt/filters/disfluency.py::_dedup_2grams removes a repeated 2-gram that is "
        "legitimate Persian. That file is owned by the STT change set, so it is reported, "
        "not fixed here."
    ),
)
def test_disfluency_keeps_a_legitimate_persian_repeated_phrase() -> None:
    text = "خیلی خوب خیلی خوب است."
    assert filter_transcript(text, _DISFLUENCY).text == text


# ── Opt-in normaliser (`[stt] persian_normalisation`) ────────────────────────


def _normaliser(*, opt_in: bool):
    return build_persian_normaliser(
        SttConfig(language="fa", persian_normalisation=opt_in)
    )


def test_normaliser_is_off_by_default() -> None:
    assert _normaliser(opt_in=False) is None
    assert profile_for("fa").build_normaliser(SttConfig(language="fa")) is None


@pytest.mark.parametrize(("text", "tags"), NO_CHANGE)
def test_opt_in_normaliser_changes_only_arabic_letters(text: str, tags: frozenset[str]) -> None:
    normalise = _normaliser(opt_in=True)
    assert normalise is not None
    out = normalise(text)
    if any(ch in "\u064a\u0643\u0649" for ch in text):
        assert out != text  # Yeh / Kaf / Alef Maksura are canonicalised
    elif "email" in tags or "url" in tags:
        assert out == text
    else:
        assert out == text, f"input {text!r}\n  -> {out!r}\n  in code points: {_cp(out)}"


def test_opt_in_normaliser_canonicalises_arabic_yeh_and_kaf() -> None:
    normalise = _normaliser(opt_in=True)
    assert normalise is not None
    assert normalise("اين كتاب را بخوان") == "این کتاب را بخوان"
    assert normalise("كتاب‌ها و كتابخانه‌ها") == "کتاب‌ها و کتابخانه‌ها"


def test_opt_in_normaliser_keeps_zwnj_byte_for_byte() -> None:
    normalise = _normaliser(opt_in=True)
    assert normalise is not None
    assert normalise("می‌خواهم کتاب‌ها را بخوانم.") == "می‌خواهم کتاب‌ها را بخوانم."
    assert normalise("می‌خواهم").count(ZWNJ) == 1


def test_opt_in_normaliser_keeps_a_url_and_an_email_byte_for_byte() -> None:
    normalise = _normaliser(opt_in=True)
    assert normalise is not None
    text = "ایمیل john.doe@example.com و آدرس https://example.com/fa/ی را ببین"
    out = normalise(text)
    assert "john.doe@example.com" in out
    assert "https://example.com/fa/ی" in out


# ── Pure-function contracts for the stage table itself ───────────────────────


def test_stage_table_is_not_accidentally_empty() -> None:
    # A bad tag or an empty vector list would silently skip every stage check.
    assert len(_CASES) == sum(
        1 for stage in STAGES for text, tags in NO_CHANGE if not (tags & STAGES[stage][1])
    )
    assert len(_CASES) > 100
