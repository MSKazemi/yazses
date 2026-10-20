"""No contributor-facing page may promise the test suite runs in seconds.

It is a large offline suite, and a full run takes minutes. Ten places said "about
30 seconds" anyway -- README.md twice, `docs/contributing.md`,
`docs/try-without-installing.md`, `.github/CONTRIBUTING.md`, the
`first-interaction` bot that greets every first-time contributor, and the Hindi,
Russian (twice) and Chinese translations. One sentence was written once, then
copied outward until a wrong number was the first thing a newcomer read.

That is the same failure `test_docs_current_version_claims.py` was written for --
a stale fact reaching three pages because nothing checked the copies -- so this
follows its lesson and **globs** the translations rather than listing them. A new
`docs/<lang>/index.md` inherits the guard the day it lands.

The number mattered more than an ordinary doc typo. It is what a prospective
contributor uses to decide whether to try, and being wrong by one to two orders of
magnitude makes a correct first run look hung. The pages now describe the scale
("minutes, not seconds") and point at a narrower run, which is both true and
durable -- a wall-clock figure would rot at the next release and is in any case
machine- and load-dependent.

**What this does not check.** Not the accuracy of any duration -- only that a
*seconds*-scale promise is not attached to the test suite. It reads prose only:
fenced code blocks are skipped, because `yazses enroll  # ~30 seconds` is a
different and accurate claim about microphone enrolment (`voiceprint.enroll_seconds`
is 25.0). And its anchors are a vocabulary, not a rule: they cover the phrasings the
shipped pages actually use, so a future translation saying "Testsuite" or "suite de
tests" needs its wording added to ``_SUITE`` below. The check is therefore strongest
on the English pages -- which is where the sentence originates and gets copied from.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Pages that tell a newcomer what contributing costs them. Globbed where a family
#: exists, so a new translation is covered without editing this list.
SURFACE_GLOBS = (
    "README.md",
    "docs/contributing.md",
    "docs/try-without-installing.md",
    "docs/*/index.md",
    ".github/CONTRIBUTING.md",
    ".github/workflows/first-interaction.yml",
)

#: Running the suite, in the scripts the shipped translations are written in. A bare
#: "test" is too loose -- it matches the corpus name "test-clean", which appears beside
#: real sub-second decode latencies on the benchmark paragraphs of these same pages.
_SUITE = (
    r"(?:test suite|tests? run|tests? take|run the tests?|suite of tests|pytest"
    r"|make check|набор тестов|тесты (?:работа|занима|проход)|测试套件|測試套件"
    r"|テストスイート|테스트 스위트|टेस्ट सूट)"
)

#: A seconds-scale duration: a number under two minutes, then a *spelled-out* unit.
#: A bare "s" is deliberately not a unit here -- "a 1.56 s median decode" is a true
#: statement about the speech model, not a promise about the suite.
_SECONDS = (
    r"\b(?:[1-9][0-9]?|1[01][0-9]|120)\s*"
    r"(?:seconds?|secs?|секунд\w*|秒|Sekunden|segundos|secondes|"
    r"saniye|ثانية|초|วินาที)"
)

_FENCE = re.compile(r"^\s*(?:```|~~~)")


def _prose_paragraphs(text: str) -> list[str]:
    """The file's prose, split into paragraphs, with fenced code removed.

    Paragraphs rather than lines because Markdown wraps: `docs/contributing.md`
    puts "The test suite is fully offline," on one line and "runs in about 30
    seconds." on the next, so a line-at-a-time check sees neither half.
    """
    kept: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            kept.append("")
            continue
        kept.append("" if in_fence else line)
    return [
        " ".join(block.split())
        for block in "\n".join(kept).split("\n\n")
        if block.strip()
    ]


def _surfaces() -> list[Path]:
    found: list[Path] = []
    for pattern in SURFACE_GLOBS:
        found.extend(sorted(ROOT.glob(pattern)))
    return found


def _offending(text: str) -> list[str]:
    """Paragraphs that attach a seconds-scale duration to the test suite."""
    hits = []
    for para in _prose_paragraphs(text):
        if re.search(_SUITE, para, re.I) and re.search(_SECONDS, para, re.I):
            hits.append(para)
    return hits


def test_the_sweep_actually_reads_files():
    """A guard that iterates is green over an empty set -- so prove the set is not.

    The globs are the part most likely to rot (a renamed page, a moved
    translation), and a zero-file sweep would pass every assertion below while
    checking nothing at all.
    """
    surfaces = _surfaces()
    assert len(surfaces) >= 6, (
        f"Only {len(surfaces)} contributor surface(s) matched {SURFACE_GLOBS}. "
        f"A page was renamed or moved and this guard is now checking almost "
        f"nothing -- fix the globs rather than lowering this floor."
    )
    assert any(p.name == "index.md" for p in surfaces), (
        "No translated index page matched, so the translations -- which is where "
        "the stale number survived longest -- are unguarded."
    )


def test_the_guard_fires_on_the_sentence_it_was_written_for():
    """The probe is wrong before the code is, often enough to check it first.

    Both halves matter: the exact English sentence that was removed, and a
    translated one, because the anchors for those are what a future translation
    will lean on.
    """
    english = (
        "The test suite is fully offline and takes about 30 seconds, so you "
        "need no microphone, model or GPU to contribute."
    )
    chinese = "测试套件完全离线，约 30 秒跑完，所以你不需要麦克风、模型或 GPU。"
    russian = "Набор тестов работает полностью локально и занимает около 30 секунд."
    for sentence in (english, chinese, russian):
        assert _offending(sentence), f"guard blind to: {sentence}"

    # And it stays quiet on the enrolment claim, which is accurate and fenced.
    fenced = "```sh\nyazses enroll   # calibrate your microphone (~30 seconds)\n```"
    assert not _offending(fenced), "guard fires on the accurate enrolment claim"


@pytest.mark.parametrize(
    "surface", _surfaces(), ids=lambda p: p.relative_to(ROOT).as_posix()
)
def test_no_surface_promises_a_suite_that_runs_in_seconds(surface: Path):
    hits = _offending(surface.read_text(encoding="utf-8"))
    assert not hits, (
        f"{surface.relative_to(ROOT).as_posix()} tells a contributor the suite runs in "
        f"seconds. A full run takes minutes; say that, or say nothing about the "
        f"duration, and point at a narrower run instead:\n\n  "
        + "\n\n  ".join(hits)
    )
