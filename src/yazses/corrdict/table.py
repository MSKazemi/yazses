"""Turn the learning corpus into a correction table (pure) — ADR-v2-079.

:mod:`yazses.corrdict.mine` owns the two pure steps — diff an utterance against its
correction, then count the results until a substitution has earned its place. This module
is the join between them and the corpus, and it is deliberately duck-typed over the event:
it reads five attributes off whatever it is handed, so it can be tested with a namespace
and never imports the encrypted store.

**Which text is "wrong" and which is "right".** The corpus carries several versions of one
utterance. The right one is what the user ended up with — an explicit correction from
``yazses mark-wrong -c "what you actually said"``, or the inferred correction a
re-dictation produces
(``learning/analysis.py::_augment_with_inferred_corrections``). The wrong one is what was
typed. An event with no correction contributes nothing, which is why an ordinary corpus of
successful dictation mines an empty table rather than a noisy one.
"""
from __future__ import annotations

from yazses.corrdict.mine import mine_substitutions, pairs_from_texts


def _typed(event) -> str:
    """What was actually put on screen for this event."""
    for attr in ("final_text", "filtered_text", "cleaned_text", "raw_text"):
        value = (getattr(event, attr, "") or "").strip()
        if value:
            return value
    return ""


def build_table(events, min_support: int = 3, max_entries: int = 200) -> dict[str, str]:
    """Mine a ``{wrong: right}`` table from corpus events. Pure.

    ``max_entries`` bounds what lands on the dictation hot path: every entry is a regex
    substitution run over every burst, and a table that grows without limit turns a
    correction aid into a latency cost. The most-supported entries survive.
    """
    pairs: list[tuple[str, str]] = []
    for event in events or ():
        correction = (getattr(event, "correction_text", "") or "").strip()
        if not correction:
            continue
        typed = _typed(event)
        if not typed or typed == correction:
            continue
        pairs.extend(pairs_from_texts(typed, correction))

    table = mine_substitutions(pairs, min_support=min_support)
    if len(table) <= max_entries:
        return table

    from collections import Counter

    support = Counter(pair for pair in pairs if pair[0] in table and table[pair[0]] == pair[1])
    keep = [wrong for (wrong, _), _ in support.most_common(max_entries)]
    return {wrong: table[wrong] for wrong in keep}
