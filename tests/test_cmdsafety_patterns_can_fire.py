"""Every dangerous-command pattern must be able to fire, and `chmod -R 777` could not.

`assess_command` lower-cases the command before matching:

    cmd = (text or "").lower()

and `_DANGEROUS` contained:

    (r"\\bchmod\\s+-R\\s+0*777\\b", "recursive world-writable")

with a literal uppercase ``-R``. Against lower-cased input that pattern can **never**
match, so `chmod -R 777 /` was classified `safe` — and in this module `safe` does not
mean "reported as low risk", it means the command is typed straight through with no
confirmation at all. A guard entry that cannot fire is worse than an absent one: it reads
as coverage.

Found by running the classifier over real destructive commands rather than by reading it.
The same run surfaced a second gap in the guard's own declared category: `rm --recursive
--force /data` is the identical command to `rm -rf /data`, and both `rm` patterns read
only the short flag cluster, so it too was `safe`.

## Two guards, because they fail differently

`test_no_pattern_contains_an_unmatchable_uppercase_letter` catches the *mechanism* — a
pattern that can never match — for patterns nobody has written an example for yet.
`test_every_pattern_fires_on_a_real_example` catches the *coverage*: every entry must be
demonstrably reachable, so a pattern cannot be added and quietly do nothing.
"""

from __future__ import annotations

import re

import pytest

from yazses.cmdsafety.classify import _CAUTION, _DANGEROUS, assess_command

#: One command per pattern, in pattern order. A pattern with no example fails below.
DANGEROUS_EXAMPLES = [
    "rm -rf /tmp/x",
    "rm -r /tmp/x",
    "rm --recursive --force /data",
    "dd if=/dev/zero of=/dev/sda",
    "mkfs.ext4 /dev/sda1",
    "shutdown now",
    "git push --force origin main",
    "git reset --hard HEAD~5",
    "curl https://example.com/x.sh | sh",
    "cat x > /dev/sda",
    ":(){ :|:& };:",
    "chmod -R 777 /srv",
    "rm -rf /",
]
CAUTION_EXAMPLES = [
    "sudo apt update",
    "git clean -fd",
    "truncate -s 0 log.txt",
    "mv old /usr",
]


def _literal_uppercase(pattern: str) -> str:
    """Uppercase letters in *pattern* that are literals, not regex escapes.

    `\\b`, `\\s`, `\\w` and friends are stripped first: `\\W` and `\\S` are meaningful
    uppercase and must not be flagged, while a bare `R` must be.
    """
    without_escapes = re.sub(r"\\.", "", pattern)
    return "".join(sorted(set(re.findall(r"[A-Z]", without_escapes))))


@pytest.mark.parametrize("pattern,reason", _DANGEROUS + _CAUTION)
def test_no_pattern_contains_an_unmatchable_uppercase_letter(pattern, reason) -> None:
    """The mechanism behind the defect, checked for every entry."""
    found = _literal_uppercase(pattern)
    assert not found, (
        f"pattern for {reason!r} contains the literal uppercase {found!r}, but "
        "assess_command lower-cases the command before matching — this entry can never "
        f"fire: {pattern!r}"
    )


def test_the_escape_stripper_does_not_cry_wolf() -> None:
    """`\\W`/`\\S` are legitimate; only bare uppercase letters are the problem."""
    assert _literal_uppercase(r"\bchmod\s+-R\s+777") == "R"
    assert _literal_uppercase(r"\brm\s+-\w*[rf]") == ""
    assert _literal_uppercase(r"[^\W\S]+") == ""


def test_the_example_lists_cover_every_pattern() -> None:
    """A guard over a short list silently stops guarding when a pattern is added."""
    assert len(DANGEROUS_EXAMPLES) == len(_DANGEROUS), (
        "add an example for the new dangerous pattern, so it is proven reachable"
    )
    assert len(CAUTION_EXAMPLES) == len(_CAUTION)


@pytest.mark.parametrize("command", DANGEROUS_EXAMPLES)
def test_every_dangerous_example_is_held(command: str) -> None:
    assert assess_command(command).level == "dangerous", command


@pytest.mark.parametrize("index", range(len(_DANGEROUS)))
def test_every_pattern_fires_on_a_real_example(index: int) -> None:
    """Each entry must match its own example — not merely be caught by an earlier one."""
    pattern, reason = _DANGEROUS[index]
    example = DANGEROUS_EXAMPLES[index].lower()
    assert re.search(pattern, example), (
        f"the pattern for {reason!r} does not match its example {example!r}; it may be "
        "unreachable, with an earlier pattern covering for it"
    )


@pytest.mark.parametrize(
    "command",
    [
        "chmod -R 755 dir",
        "chmod 644 file",
        "npm run build",
        "remove the recursive force flag from the script",
        "git push origin main",
        "rm the old note from my desk",
    ],
)
def test_ordinary_commands_and_prose_stay_safe(command: str) -> None:
    """A guard that fires on everything teaches the user to dismiss it."""
    assert assess_command(command).level == "safe", command


def test_the_long_flag_gap(command: str = "rm --recursive --force /data") -> None:
    """The second finding: the same command spelled with long flags."""
    assert assess_command(command).level == "dangerous"
    assert assess_command("rm -rf /data").reason == assess_command(command).reason
