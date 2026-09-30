"""Conservative Persian/RTL normalisation (`[stt] language = "fa"`) — FA-02.

Arabic-script ASR output is script-contaminated by construction: Whisper decodes
Persian speech into a mix of Arabic and Persian code points, because the training
corpora for both languages share an alphabet. The two Yehs (ي U+064A vs ی U+06CC),
the two Kafs (ك U+0643 vs ک U+06A9) and Alef Maksura (ى U+0649) are *distinct
characters* to every search, spell-checker and copy-paste downstream, and a user
dictating Persian gets them interleaved mid-word. The recognition was usually
right; the renderer handed back the wrong code point.

This module canonicalises those letters and does the two pieces of zero-width
hygiene the spec allows — nothing more. It is deliberately *not* a language model:
no morphology-based half-space insertion (§5), no digit conversion (§7), no
punctuation conversion (§8), no dictionary. `design/specs/persian-text-and-rtl.md`
is the contract; section numbers in comments cite it.

Pure and deterministic. `normalise_persian` is idempotent, the mapping table is
data on purpose (§3 asks for exactly that, and the tests read it instead of
repeating it), and the bidi strip is a small audited function (§6) because that
is the rule with a security face.

Off by default: `build_persian_normaliser` returns ``None`` unless ``[stt]
language`` is Persian, so English output is byte-for-byte unaffected. FA-01
(#509) later swaps the predicate for the language-profile lookup; the core
above it does not change.
"""
from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yazses.config import SttConfig

# ── §3 Canonical character mappings (data, tested in both contexts) ─────────
ARABIC_YEH = "\u064A"        # ي Arabic Yeh            -> ی Farsi Yeh
ALEF_MAKSURA = "\u0649"      # ى Alef Maksura          -> ی Farsi Yeh
ARABIC_KAF = "\u0643"        # ك Arabic Kaf            -> ک Keheh
PERSIAN_YEH = "\u06CC"       # ی Farsi Yeh
PERSIAN_KEHEH = "\u06A9"     # ک Keheh

CANONICAL_MAPPINGS: dict[str, str] = {
    ARABIC_YEH: PERSIAN_YEH,
    ALEF_MAKSURA: PERSIAN_YEH,
    ARABIC_KAF: PERSIAN_KEHEH,
}

ZWNJ = "\u200C"  # §5 zero-width non-joiner: meaningful orthography

# §6 bidi embedding/override controls (U+202A–U+202E) and isolates
# (U+2066–U+2069). Stripped *everywhere*, including inside protected spans and
# URLs: a control hidden in a URL is exactly the adversarial case §6 names,
# and a stripped control cannot render hidden text. ZWNJ/ZWJ are not here —
# zero-width is never the test (§6).
_BIDI_CONTROLS_RE = re.compile("[\u202A-\u202E\u2066-\u2069]")

# §9 protected spans: letter canonicalisation and ZWNJ surgery must not reach
# into URLs, emails, paths, dotted versions, or Latin/digit identifier runs —
# an identifier that changes bytes is a broken identifier. Alternation order
# matters: URL/`www` first so their greedy `\S+` consumes the whole thing
# before a later alternative can match inside it; email before bare identifier
# so `[\w.+-]+@` wins at the local-part's first character (`\w` is Unicode, so
# an Arabic-script local part is protected too — §9 keeps addresses intact).
_PROTECTED_SPAN_RE = re.compile(
    r"""https?://\S+                       # URL
      | www\.\S+                           # bare www host
      | [\w.+-]+@[\w-]+\.[\w.-]+           # email address
      | (?:/[\w.\-]+)+                     # absolute POSIX path
      | [A-Za-z]:[\\/](?:[\w.\-]+[\\/]?)*  # Windows drive path
      | \b\d+(?:\.\d+)+\b                  # dotted version: 3.13, 1.2.3
      | [A-Za-z0-9][A-Za-z0-9_.+\-]*       # Latin/digit identifier run
    """,
    re.VERBOSE,
)

# §2 fast path: Arabic block + supplement + presentation forms, so an English
# burst never pays for a normalisation that cannot change it.
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def contains_arabic(text: str) -> bool:
    """True when *text* holds at least one Arabic-script character."""
    return any(
        any(lo <= ord(ch) <= hi for lo, hi in _ARABIC_RANGES) for ch in text
    )


def strip_bidi_controls(text: str) -> str:
    """Remove every Unicode bidi embedding/override/isolate control (§6).

    Its own small audited function because it carries the security property:
    an RLO/PDF pair can make hidden text render as its mirror, so controls are
    removed from the *whole* string, protected spans included. ZWNJ/ZWJ are
    deliberately not stripped (§6).
    """
    return _BIDI_CONTROLS_RE.sub("", text)


def _normalise_gap(gap: str) -> str:
    """Canonicalise letters and ZWNJ inside one unprotected gap (§3, §5)."""
    for source, target in CANONICAL_MAPPINGS.items():
        gap = gap.replace(source, target)
    return re.sub(f"{ZWNJ}{{2,}}", ZWNJ, gap)


def normalise_persian(text: str) -> str:
    """Apply the §2 pipeline to *text*. Pure; idempotent; never raises.

    Order: NFC (§4), boundary-ZWNJ removal and bidi strip over the whole
    string (§5/§6), then letter canonicalisation and interior-ZWNJ collapse
    in the gaps between §9 protected spans, which are replayed byte-for-byte.
    Generic YazSes cleaners and command-safety classification stay downstream,
    exactly where the spec's processing-order diagram puts them.
    """
    if not text:
        return text

    # §4 NFC only — never NFKC/NFKD: compatibility normalisation rewrites
    # characters far outside Persian scope. Canonical composition can still
    # fuse a base+mark pair (alef + hamza -> U+0623); marks Unicode has no
    # composed form for survive untouched.
    text = unicodedata.normalize("NFC", text)

    # §5 boundary rule and §6 controls apply to the string as a whole. Doing
    # them before span detection means no span can smuggle a boundary ZWNJ or
    # an override past either rule (the span regex cannot start on ZWNJ, and
    # `\S+` only *keeps* controls that this step has already removed).
    text = text.strip(ZWNJ)
    text = strip_bidi_controls(text)

    out: list[str] = []
    last = 0
    for match in _PROTECTED_SPAN_RE.finditer(text):
        out.append(_normalise_gap(text[last:match.start()]))
        out.append(match.group(0))  # byte-for-byte (§9)
        last = match.end()
    out.append(_normalise_gap(text[last:]))
    return "".join(out)


def build_persian_normaliser(stt: "SttConfig") -> Callable[[str], str] | None:
    """Return a text→text gate for Persian output, or ``None`` when inactive.

    ``None`` means "leave the model's output exactly as it came" and is
    returned for every configuration this normaliser does not own — so English
    (and every other language) is untouched, which is the acceptance criterion
    the gate exists for. The active set is Whisper's own codes plus the two
    spellings a config is likely to carry.
    """
    language = (getattr(stt, "language", "") or "").strip().lower()
    if language not in ("fa", "fas", "fa-ir", "persian"):
        return None

    def normalise(text: str) -> str:
        if not text:
            return text
        if not contains_arabic(text):
            # English fast path — but bidi controls still come out. An override
            # control in model output is adversarial regardless of script, and
            # this is the Persian-profile gate: when the profile is *off* the
            # engine is untouched, which is what the acceptance criterion asks.
            return strip_bidi_controls(text)
        return normalise_persian(text)

    return normalise
