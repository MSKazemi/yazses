"""The Android command grammar must be the same ordered rule table as the desktop's.

`commands/grammar.py` and `android/.../commands/Grammar.kt` are two copies of one
grammar, and they drifted the way copies do: `37997ae` widened the desktop's
`comment` rule so "comment this line" -- the phrasing people actually use -- stopped
being typed into the file, three days after `c5bd487` ported the narrow form to
Kotlin. Nothing carried the fix across, and nothing could notice:

* **No contract vector names `comment` at all.** The 228-vector corpus is the stated
  mechanism for keeping the ports in step (ADR-MOB-008) and it does not exercise this
  rule in either direction, so the Android leg was green on a rule it got wrong.
* **The failure is silent by construction.** An utterance that matches no rule is
  discarded in command mode, so "comment this line" did not comment, did not type,
  and produced nothing to report.

So this compares the *tables*, not examples -- the lesson of the disfluency port,
where a corpus of examples named 1 of 33 missing words. Both sides are derived from
their own source (the Kotlin is parsed; the Python is imported), because a list
restated here would agree with whichever side it was copied from.

**Order is semantics, not style.** Both classifiers take the first match, and the
table deliberately puts `run tests` ahead of the catch-all `run (.+)`. A port that
holds the same rules in a different order is a different grammar, so the comparison
is sequence-wise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yazses.commands.grammar import _RULES

ROOT = Path(__file__).resolve().parent.parent
KOTLIN = (
    ROOT / "android/core/commands/src/main/kotlin/com/yazses/core/commands/Grammar.kt"
)

#: `rule("""<pattern>""", IntentType.<INTENT>, "<action>"[, "<arg>"...])`, spread
#: over any number of lines: a rule long enough to need wrapping is exactly the
#: kind that drifts, so the parser must not be defeated by a line break.
_RULE_CALL = re.compile(
    r'rule\(\s*"""(?P<pattern>.*?)"""\s*,'
    r'\s*IntentType\.(?P<intent>\w+)\s*,'
    r'\s*"(?P<action>\w+)"'
    r'(?P<args>(?:\s*,\s*"\w+")*)'
    r"\s*,?\s*\)",
    re.DOTALL,
)


def _kotlin_rules() -> list[tuple[str, str, str, tuple[str, ...]]]:
    source = KOTLIN.read_text(encoding="utf-8")
    body = source[source.index("private val RULES"):]
    out = []
    for match in _RULE_CALL.finditer(body):
        args = tuple(re.findall(r'"(\w+)"', match.group("args")))
        out.append(
            (match.group("pattern"), match.group("intent"), match.group("action"), args)
        )
    return out


def _python_rules() -> list[tuple[str, str, str, tuple[str, ...]]]:
    return [
        (pattern.pattern, intent.name, action, tuple(arg_names))
        for pattern, intent, action, arg_names in _RULES
    ]


KOTLIN_RULES = _kotlin_rules()
PYTHON_RULES = _python_rules()


def test_the_parser_found_the_kotlin_table() -> None:
    """Guards against every test below passing on a corpus of nothing -- a renamed
    helper or a reformatted call would otherwise read as perfect agreement."""
    assert len(KOTLIN_RULES) > 30, (
        f"only {len(KOTLIN_RULES)} rules parsed out of {KOTLIN.name}; the `rule(...)` "
        "form has changed and this guard is blind. Fix the parser, not the count."
    )


def test_neither_port_has_a_rule_the_other_lacks() -> None:
    """Set comparison first: it names the missing rule, where the sequence
    comparison below would only point at the position where the two diverge."""
    kotlin = {(p, i, a) for p, i, a, _ in KOTLIN_RULES}
    python = {(p, i, a) for p, i, a, _ in PYTHON_RULES}
    only_kotlin = sorted(kotlin - python)
    only_python = sorted(python - kotlin)
    assert not (only_kotlin or only_python), (
        "the desktop and Android command grammars have drifted.\n"
        f"  only in Grammar.kt: {only_kotlin}\n"
        f"  only in grammar.py: {only_python}\n"
        "A rule present on one side only means that phrase does one thing on the "
        "desktop and, in command mode, nothing at all on Android -- it matches no "
        "rule, so it is discarded rather than typed."
    )


def test_the_rules_are_in_the_same_order() -> None:
    """First match wins on both sides, so `run tests` must stay ahead of `run (.+)`."""
    assert [(a, i) for _, i, a, _ in KOTLIN_RULES] == [
        (a, i) for _, i, a, _ in PYTHON_RULES
    ], (
        "the two grammars hold the same rules in a different order. Both classifiers "
        "return the first match, so order decides which rule wins: with the catch-all "
        "`^run (.+)$` moved ahead of `^run the tests$`, 'run the tests' becomes a "
        "shell command whose text is 'the tests'."
    )


@pytest.mark.parametrize(
    "index", range(max(len(KOTLIN_RULES), len(PYTHON_RULES))),
)
def test_each_rule_matches_its_counterpart_exactly(index: int) -> None:
    """Pattern *text* is compared, not behaviour: the dialects agree on this subset
    of syntax, and any textual difference is a divergence worth a human look."""
    kotlin = KOTLIN_RULES[index] if index < len(KOTLIN_RULES) else None
    python = PYTHON_RULES[index] if index < len(PYTHON_RULES) else None
    assert kotlin == python, (
        f"rule {index} differs between the ports.\n"
        f"  Grammar.kt: {kotlin}\n"
        f"  grammar.py: {python}"
    )


@pytest.mark.parametrize(
    "phrase",
    ["comment this line", "comment the line", "comment this selection", "comment out"],
)
def test_the_phrasings_that_were_only_ported_late_are_present_on_both_sides(
    phrase: str,
) -> None:
    """The specific regression, held by name. `comment this line` is what a person
    says; `comment` alone is what the narrow rule accepted."""
    from yazses.commands.grammar import classify

    assert classify(phrase).action == "comment", f"the desktop lost {phrase!r}"
    kotlin_comment = [p for p, _, a, _ in KOTLIN_RULES if a == "comment"]
    assert kotlin_comment, "Grammar.kt no longer has a `comment` rule"
    assert re.fullmatch(kotlin_comment[0], phrase, re.IGNORECASE), (
        f"Grammar.kt's comment rule does not accept {phrase!r}. In command mode an "
        "unmatched utterance is discarded, so the phrase does nothing at all -- no "
        "comment, no text, no error."
    )
