"""Mine + apply a self-learning correction table (pure) — ADR-v2-079.

Turn repeated (wrong→right) edit pairs into a high-precision substitution table and apply it,
longest-match and word-boundary-guarded. Pure and deterministic; the corpus supplies the events.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from collections.abc import Callable


def _literal(value: str) -> Callable[[re.Match[str]], str]:
    """A ``re.sub`` replacement that emits ``value`` verbatim.

    Binding the value in a factory rather than a lambda default argument keeps the
    per-iteration capture correct *and* stays inferable, and it preserves the reason
    a function replacement is used at all: literal backslashes in a correction must
    not be re-interpreted as group references.
    """
    return lambda _m: value


def _shape(value: str) -> str:
    """Letters and digits only, lowercased — the form similarity is judged on.

    Case and spacing are exactly what a recognition error gets wrong ("yaz says" for
    "YazSes"), so comparing the raw strings would score the clearest true positives
    lowest.
    """
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def similarity(wrong: str, right: str) -> float:
    """How alike two spellings are, 0.0-1.0. Pure.

    This is the test for *did the recogniser mishear this*, as opposed to *did the user
    reword it*. Measured on the pairs this feature is meant to catch and the ones it must
    not:

        yaz says     -> YazSes        0.77   mis-heard      keep
        cubernetties -> Kubernetes    0.82   mis-heard      keep
        affect       -> effect        0.83   mis-heard      keep
        there        -> their         0.80   mis-heard      keep
        week         -> weak          0.75   mis-heard      keep
        to the team  -> across to ...  0.32  reworded       drop
        send         -> forward       0.18   reworded       drop
        document ... -> file across   0.09   reworded       drop

    The two classes separate at 0.75/0.32, so :data:`MIN_SIMILARITY` sits between them
    rather than on either edge.
    """
    return difflib.SequenceMatcher(None, _shape(wrong), _shape(right)).ratio()


#: Below this, a pair is a rewrite rather than a misrecognition. See :func:`similarity`.
MIN_SIMILARITY = 0.6


def pairs_from_texts(
    wrong_text: str,
    right_text: str,
    max_span: int = 3,
    min_similarity: float = MIN_SIMILARITY,
) -> list[tuple[str, str]]:
    """Diff two versions of one utterance into ``(wrong, right)`` phrase pairs. Pure.

    :func:`mine_substitutions` counts pairs, so it needs the part that changed, not the
    whole sentence: two corrections of "yaz says" -> "YazSes" in different sentences are
    the same substitution and must be counted together, which whole-utterance pairs can
    never do.

    Three things are dropped, and the third was found by a test rather than by design:

    * Pure insertions and deletions — there is no "wrong" side to key a substitution on,
      and a table entry mapping "" to anything would fire everywhere.
    * Spans longer than ``max_span`` words on either side, which are clause rewrites.
    * Pairs that do not *sound like* each other (:func:`similarity`). Without this,
      rewording one sentence ("send" -> "forward", "the document over" -> "the file
      across") mined as cleanly as a misrecognition, because difflib breaks a whole-
      sentence rewrite into exactly the short spans the length guard allows. The table is
      applied to every future burst, so a mined rewrite replays somebody's one-off word
      choice into unrelated sentences forever.
    """
    left, right = (wrong_text or "").split(), (right_text or "").split()
    if not left or not right:
        return []
    pairs: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, left, right).get_opcodes():
        if tag != "replace":
            continue
        if (i2 - i1) > max_span or (j2 - j1) > max_span:
            continue
        wrong, correct = " ".join(left[i1:i2]), " ".join(right[j1:j2])
        if similarity(wrong, correct) < min_similarity:
            continue
        pairs.append((wrong, correct))
    return pairs


def mine_substitutions(events, min_support: int = 3) -> dict:
    """Build a ``{wrong: right}`` table from (wrong, right) edit pairs. Pure.

    Keeps a substitution only when its dominant correction reaches ``min_support`` and no rival
    correction ties it (so ambiguous edits are dropped).
    """
    counts: Counter = Counter()
    for pair in events or ():
        wrong, right = (pair[0] or "").strip(), (pair[1] or "").strip()
        if wrong and right and wrong != right:
            counts[(wrong, right)] += 1

    by_wrong = defaultdict(list)
    for (wrong, right), c in counts.items():
        by_wrong[wrong].append((right, c))

    table: dict = {}
    for wrong, rights in by_wrong.items():
        rights.sort(key=lambda rc: rc[1], reverse=True)
        top_right, top_count = rights[0]
        if top_count >= min_support and (len(rights) == 1 or top_count > rights[1][1]):
            table[wrong] = top_right
    return table


def apply_corrections(text: str, table: dict) -> str:
    """Apply a correction ``table`` to ``text``, longest key first, boundary-guarded. Pure."""
    if not table or not text:
        return text or ""
    out = text
    for key in sorted(table, key=len, reverse=True):
        repl = table[key]
        # \b only helps when the key edges are word chars; fall back to a plain replace otherwise.
        left = r"\b" if key[:1].isalnum() else ""
        right = r"\b" if key[-1:].isalnum() else ""
        out = re.sub(f"{left}{re.escape(key)}{right}", _literal(repl), out)
    return out
