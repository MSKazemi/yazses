"""Persian-English code-switch scorer (protocol ``fa-en-cs-v1``), text only.

Part of FA-09 / #518. The protocol this implements -- the six prompt categories, the
sourcing and consent rules, the held-out split and the exact metric definitions -- is
``design/specs/persian-code-switch-evaluation.md``. It was written before any model
output was scored under it; a change to a definition below is a new protocol version,
never an edit to ``fa-en-cs-v1``.

The scorer reads **text only**: a reference transcript and a hypothesis per prompt. It
never loads audio, a model or anything from ``yazses``, so a contributor can score a
local run on their own machine and submit the aggregate block alone (``--aggregate-only``
is the only output mode the CLI has). Stdlib only, beside ``persian_metrics.py``, whose
``fa-eval-v1`` normalizer it reuses so Persian text is normalized identically in both
benches.

Tokens and script tags (spec §7)
--------------------------------
Text is normalized with ``fa-eval-v1`` and split on whitespace (ZWNJ stays inside a
word). Each token is tagged from the Unicode names of its *letters*:

- ``fa``      -- at least one ARABIC-script letter and no LATIN letter;
- ``en``      -- at least one LATIN letter and no ARABIC-script letter;
- ``mixed``   -- letters from both scripts in one token (``PRها``);
- ``neutral`` -- no letter at all (digits, ``3.12``, punctuation).

The tag is a *script* tag, not a language identification: an English word written in
Persian script (``پایتون``) is tagged ``fa``. That is deliberate -- transliterating an
English term into Persian script is exactly the failure the protocol has to see.

Metrics (spec §8)
-----------------
- **MER** -- token edit distance / reference tokens, over the mixed stream. Persian and
  English are both whitespace-delimited, so the mixed unit is the word for both. Reported
  raw (whitespace split only) and ``fa-eval-v1``-normalized.
- **Language-boundary error rate (BER)** -- (missed + spurious boundaries) / reference
  boundaries. A boundary is a script change between consecutive ``fa``/``en`` tokens
  (``mixed`` and ``neutral`` tokens neither make nor break one). A hypothesis boundary
  matches a reference boundary of the same direction when its two flanking tokens are
  aligned to reference tokens that bracket it; each reference boundary is claimed once.
  Precision and recall are reported beside it. Like MER, BER can exceed 1.
- **English-token preservation** -- reference ``en`` tokens whose aligned hypothesis
  token is identical after stripping leading/trailing punctuation; a case-folded variant
  and the count transliterated into Persian script are reported beside it.
- **Persian CER** -- character edit distance between the ``fa``-tagged tokens of the
  reference and of the hypothesis (each joined by single spaces), over the reference's
  characters. English inserted into the Persian stream in Persian script therefore costs
  Persian characters.
- **Token-language accuracy** -- over reference ``fa``/``en`` tokens aligned to a
  hypothesis token, the share whose script tag agrees. It is the text-observable part of
  the spec's span-language accuracy; a decoder's own span labels are not scored here.

A rate whose denominator is zero is ``None``, never ``0`` -- a set with no English token
has no English-preservation rate, not a perfect one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path

from persian_metrics import EVAL_NORMALIZER_VERSION, normalize_fa_eval_v1

PROTOCOL_VERSION = "fa-en-cs-v1"
SCHEMA = "yazses.bench.codeswitch/1"

#: The six content categories of the protocol (spec §3). A row with any other value is
#: refused: a category invented at scoring time is a category nobody wrote prompts for.
CATEGORIES = (
    "fa_with_en_term",   # Persian sentence carrying an English technical noun
    "product_names",     # product / package / service names
    "numbers_versions",  # numbers, versions, units next to either script
    "en_clause_in_fa",   # an English clause embedded in a Persian sentence
    "fa_clause_in_en",   # a Persian clause embedded in an English sentence
    "rapid_switch",      # two or more switches within a few words
)

#: Frozen with the protocol (spec §6). Changing either is ``fa-en-cs-v2``.
SPLIT_SEED = "yazses-fa-en-cs-v1"
HELDOUT_FRACTION = 0.5

#: Prompt ids are opaque: they name a prompt, never a speaker, session or person.
PROMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

FA, EN, MIXED, NEUTRAL = "fa", "en", "mixed", "neutral"
_LANGS = (FA, EN)


# --------------------------------------------------------------------------- split


def split_of(
    prompt_id: str, *, seed: str = SPLIT_SEED, heldout_fraction: float = HELDOUT_FRACTION
) -> str:
    """``"heldout"`` or ``"dev"`` for *prompt_id*, from a seeded SHA-256 of the id alone.

    The assignment depends on nothing but the seed and the id, so adding, removing or
    reordering prompts never moves an existing one, and every recording of one prompt
    lands on the same side.
    """
    if not PROMPT_ID_RE.match(prompt_id or ""):
        raise ValueError(f"prompt id {prompt_id!r} must match {PROMPT_ID_RE.pattern}")
    if not 0.0 < heldout_fraction < 1.0:
        raise ValueError("heldout_fraction must be strictly between 0 and 1")
    digest = hashlib.sha256(f"{seed}\x00{prompt_id}".encode()).digest()
    point = int.from_bytes(digest[:8], "big") / 2**64
    return "heldout" if point < heldout_fraction else "dev"


def split_digest(prompt_ids: Iterable[str]) -> str:
    """SHA-256 over the sorted, de-duplicated ids -- published so a reader can confirm a
    result was scored on the same prompts without seeing any of them."""
    joined = "\n".join(sorted(set(prompt_ids)))
    return hashlib.sha256(joined.encode()).hexdigest()


# ------------------------------------------------------------------ tokens and tags


def tokens(text: str, *, normalize: bool = True) -> list[str]:
    """Whitespace tokens, after ``fa-eval-v1`` unless *normalize* is False (raw)."""
    return (normalize_fa_eval_v1(text) if normalize else (text or "")).split()


def script_tag(token: str) -> str:
    """``fa`` / ``en`` / ``mixed`` / ``neutral`` from the token's letters (module doc)."""
    arabic = latin = False
    for ch in token:
        if not unicodedata.category(ch).startswith("L"):
            continue
        name = unicodedata.name(ch, "")
        if name.startswith("ARABIC"):
            arabic = True
        elif name.startswith("LATIN"):
            latin = True
    if arabic and latin:
        return MIXED
    if arabic:
        return FA
    if latin:
        return EN
    return NEUTRAL


def _core(token: str) -> str:
    """*token* without leading/trailing punctuation (``GitHub،`` -> ``GitHub``)."""
    start, end = 0, len(token)
    while start < end and unicodedata.category(token[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(token[end - 1]).startswith("P"):
        end -= 1
    return token[start:end]


# ---------------------------------------------------------------------- alignment


def align(ref: Sequence[str], hyp: Sequence[str]) -> list[tuple[int | None, int | None]]:
    """Minimum-edit alignment as ``(ref_index, hyp_index)`` pairs.

    ``(i, j)`` is a match or substitution, ``(i, None)`` a deletion, ``(None, j)`` an
    insertion. Ties prefer the diagonal, then deletion, so the result is deterministic.
    """
    n, m = len(ref), len(hyp)
    dist = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dist[i][0] = i
    for j in range(m + 1):
        dist[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dist[i][j] = min(dist[i - 1][j - 1] + cost, dist[i - 1][j] + 1, dist[i][j - 1] + 1)
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            if dist[i][j] == dist[i - 1][j - 1] + cost:
                pairs.append((i - 1, j - 1))
                i, j = i - 1, j - 1
                continue
        if i > 0 and dist[i][j] == dist[i - 1][j] + 1:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


def edit_distance(ref: Sequence[str], hyp: Sequence[str]) -> int:
    """Levenshtein distance between two sequences (tokens or characters)."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j - 1] + (r != h), prev[j] + 1, cur[j - 1] + 1)
        prev = cur
    return prev[-1]


def boundaries(tags: Sequence[str]) -> list[tuple[int, int, str, str]]:
    """``(left_index, right_index, left_lang, right_lang)`` for each script change
    between consecutive ``fa``/``en`` tokens; ``mixed``/``neutral`` are skipped."""
    lang_positions = [i for i, t in enumerate(tags) if t in _LANGS]
    out = []
    for p, k in zip(lang_positions, lang_positions[1:]):
        if tags[p] != tags[k]:
            out.append((p, k, tags[p], tags[k]))
    return out


# ------------------------------------------------------------------------ scoring


@dataclass(frozen=True)
class UtteranceScore:
    """Counts for one prompt. Rates are only ever computed from summed counts."""

    category: str
    ref_tokens: int
    token_errors: int
    raw_ref_tokens: int
    raw_token_errors: int
    ref_boundaries: int
    hyp_boundaries: int
    matched_boundaries: int
    en_ref_tokens: int
    en_preserved: int
    en_preserved_casefold: int
    en_transliterated: int
    fa_ref_chars: int
    fa_char_errors: int
    lang_aligned: int
    lang_agree: int
    mixed_ref_tokens: int


def score_utterance(reference: str, hypothesis: str, category: str = "") -> UtteranceScore:
    """Score one hypothesis against its reference under ``fa-en-cs-v1``."""
    raw_ref, raw_hyp = tokens(reference, normalize=False), tokens(hypothesis, normalize=False)
    ref, hyp = tokens(reference), tokens(hypothesis)
    ref_tags = [script_tag(t) for t in ref]
    hyp_tags = [script_tag(t) for t in hyp]
    pairs = align(ref, hyp)

    hyp_to_ref = {j: i for i, j in pairs if i is not None and j is not None}
    ref_to_hyp = {i: j for i, j in pairs if i is not None and j is not None}

    # Boundaries: claim each reference boundary at most once, in hypothesis order.
    ref_b = boundaries(ref_tags)
    hyp_b = boundaries(hyp_tags)
    claimed: set[int] = set()
    for hp, hk, a, b in hyp_b:
        rp, rk = hyp_to_ref.get(hp), hyp_to_ref.get(hk)
        if rp is None or rk is None or rp >= rk:
            continue
        for idx, (p, k, ra, rb) in enumerate(ref_b):
            if idx not in claimed and (ra, rb) == (a, b) and rp <= p and k <= rk:
                claimed.add(idx)
                break

    en_ref = en_ok = en_fold = en_translit = 0
    lang_aligned = lang_agree = 0
    for i, tag in enumerate(ref_tags):
        j = ref_to_hyp.get(i)
        if tag in _LANGS and j is not None:
            lang_aligned += 1
            lang_agree += hyp_tags[j] == tag
        if tag != EN:
            continue
        en_ref += 1
        if j is None:
            continue
        r_core, h_core = _core(ref[i]), _core(hyp[j])
        en_ok += r_core == h_core
        en_fold += r_core.casefold() == h_core.casefold()
        en_translit += hyp_tags[j] == FA

    fa_ref = " ".join(t for t, tag in zip(ref, ref_tags) if tag == FA)
    fa_hyp = " ".join(t for t, tag in zip(hyp, hyp_tags) if tag == FA)

    return UtteranceScore(
        category=category,
        ref_tokens=len(ref),
        token_errors=edit_distance(ref, hyp),
        raw_ref_tokens=len(raw_ref),
        raw_token_errors=edit_distance(raw_ref, raw_hyp),
        ref_boundaries=len(ref_b),
        hyp_boundaries=len(hyp_b),
        matched_boundaries=len(claimed),
        en_ref_tokens=en_ref,
        en_preserved=en_ok,
        en_preserved_casefold=en_fold,
        en_transliterated=en_translit,
        fa_ref_chars=len(fa_ref),
        fa_char_errors=edit_distance(fa_ref, fa_hyp),
        lang_aligned=lang_aligned,
        lang_agree=lang_agree,
        mixed_ref_tokens=sum(t == MIXED for t in ref_tags),
    )


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def summarize(scores: Iterable[UtteranceScore]) -> dict:
    """Counts and rates for a group of utterances -- no text, no ids."""
    scores = list(scores)
    counts = {
        f.name: sum(getattr(s, f.name) for s in scores)
        for f in fields(UtteranceScore)
        if f.name != "category"
    }
    c = counts
    missed = c["ref_boundaries"] - c["matched_boundaries"]
    spurious = c["hyp_boundaries"] - c["matched_boundaries"]
    return {
        "n": len(scores),
        "counts": counts,
        "mer": _rate(c["token_errors"], c["ref_tokens"]),
        "mer_raw": _rate(c["raw_token_errors"], c["raw_ref_tokens"]),
        "boundary_error_rate": _rate(missed + spurious, c["ref_boundaries"]),
        "boundary_recall": _rate(c["matched_boundaries"], c["ref_boundaries"]),
        "boundary_precision": _rate(c["matched_boundaries"], c["hyp_boundaries"]),
        "en_preservation": _rate(c["en_preserved"], c["en_ref_tokens"]),
        "en_preservation_casefold": _rate(c["en_preserved_casefold"], c["en_ref_tokens"]),
        "en_transliteration_rate": _rate(c["en_transliterated"], c["en_ref_tokens"]),
        "fa_cer": _rate(c["fa_char_errors"], c["fa_ref_chars"]),
        "token_language_accuracy": _rate(c["lang_agree"], c["lang_aligned"]),
    }


def aggregate_report(scores: Sequence[UtteranceScore], prompt_ids: Sequence[str], split: str) -> dict:
    """The submission block (spec §9): overall + per category, counts and rates only."""
    by_category = {
        cat: summarize(s for s in scores if s.category == cat) for cat in CATEGORIES
    }
    return {
        "schema": SCHEMA,
        "protocol": PROTOCOL_VERSION,
        "normalizer": EVAL_NORMALIZER_VERSION,
        "split": {
            "name": split,
            "seed": SPLIT_SEED,
            "heldout_fraction": HELDOUT_FRACTION,
            "n_prompts": len(set(prompt_ids)),
            "prompt_digest": split_digest(prompt_ids),
        },
        "overall": summarize(scores),
        "by_category": by_category,
    }


# ---------------------------------------------------------------------------- CLI


def load_rows(path: Path) -> list[dict]:
    """Read ``{id, category, reference, hypothesis}`` JSONL; refuse a malformed row."""
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        for key in ("id", "category", "reference", "hypothesis"):
            if not isinstance(row.get(key), str):
                raise ValueError(f"{path}:{lineno}: missing string field {key!r}")
        if not PROMPT_ID_RE.match(row["id"]):
            raise ValueError(f"{path}:{lineno}: prompt id {row['id']!r} is not opaque")
        if row["category"] not in CATEGORIES:
            raise ValueError(f"{path}:{lineno}: unknown category {row['category']!r}")
        rows.append(row)
    return rows


def run(rows: Sequence[dict], split: str = "heldout") -> dict:
    """Score the rows on *split* (``heldout``, ``dev`` or ``all``) and aggregate."""
    chosen = [r for r in rows if split == "all" or split_of(r["id"]) == split]
    scores = [score_utterance(r["reference"], r["hypothesis"], r["category"]) for r in chosen]
    return aggregate_report(scores, [r["id"] for r in chosen], split)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score fa-en code-switch hypotheses (text only) and print the "
        "aggregate-only submission block. No text or prompt id is ever written."
    )
    parser.add_argument("rows", type=Path, help="JSONL of id/category/reference/hypothesis")
    parser.add_argument("--split", choices=("heldout", "dev", "all"), default="heldout")
    parser.add_argument("--out", type=Path, help="write the JSON here instead of stdout")
    parser.add_argument(
        "--aggregate-only", action="store_true",
        help="accepted for clarity; aggregate-only is the only output mode",
    )
    args = parser.parse_args(argv)
    report = run(load_rows(args.rows), args.split)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


__all__ = [
    "CATEGORIES", "HELDOUT_FRACTION", "PROTOCOL_VERSION", "SCHEMA", "SPLIT_SEED",
    "UtteranceScore", "aggregate_report", "align", "boundaries", "edit_distance",
    "load_rows", "run", "score_utterance", "script_tag", "split_digest", "split_of",
    "summarize", "tokens",
]

if __name__ == "__main__":
    raise SystemExit(main())
