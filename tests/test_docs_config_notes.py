"""The configuration reference must say what a key *means*, not just its type.

`docs/configuration.md` is the page a user reads before editing `config.toml` by
hand. It listed 449 keys as name, type and default, which is exactly enough to write
a syntactically valid line and not nearly enough to write a correct one — and for
keys whose *name* misleads, the page was actively harmful.

`[recimport] max_speakers` is the case that forced this. On the shipped sherpa
backend it becomes `FastClusteringConfig(num_clusters=N)`: an **exact** cluster
count, not a cap, so a cautious "at most 6" splits three real speakers into six.
`config.py` had said so beside the field for a long time. The reference page had an
empty cell.

So the Notes column is derived from each field's trailing comment in `config.py`,
which makes documenting a key the same act as commenting it. Derived rather than
curated on purpose: a hand-maintained list of "interesting" keys can only describe
the traps somebody remembered, and this repo has been bitten by hand-written sets
more than once.

What is guarded here is everything about that derivation that can go wrong quietly:
notes filed under the wrong section, a `#` inside a string default published as
documentation, a wrapped comment truncated at the line break, and a pipe inside a
note ending its table cell early.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "configuration.md"


@pytest.fixture(scope="module")
def gen():
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "src"))
    spec = importlib.util.spec_from_file_location("gen_docs", ROOT / "scripts" / "gen-docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_notes_are_scoped_to_the_class_not_the_bare_field_name(gen):
    """`enabled`, `engine` and `model_path` recur across sections with different
    meanings; a global name->comment map would file one section's note under
    another's key, and every such note reads plausibly."""
    notes = gen._field_notes()
    keys = list(notes)
    assert all(isinstance(k, tuple) and len(k) == 2 for k in keys)
    names = [field for _, field in keys]
    assert len(set(names)) < len(names), (
        "no field name repeats across classes, so this guard is not testing anything "
        "— re-check the extraction rather than deleting the assertion"
    )
    # `backend` is annotated in ten config dataclasses and names a different set of
    # choices in most of them; a global map would print the gaze backends under
    # `[denoise]`. Distinctness is not the property to assert, though: `[recimport]`
    # and `[meeting]` document their sherpa/pyannote choice in the same words on
    # purpose, and requiring every note to differ would make a correct extraction
    # fail. What must hold is that each class's note came from *that class's* source.
    backends = {cls: note for (cls, field), note in notes.items() if field == "backend"}
    assert len(backends) >= 4, backends
    assert len(set(backends.values())) > 1, (
        "every `backend` note is identical, which is exactly what a name-keyed lookup "
        f"would produce:\n  {backends}"
    )
    for cls, note in backends.items():
        segment = _class_source(cls)
        assert _strip_comment_marks(note[:60]) in _strip_comment_marks(segment), (
            f"{cls}'s `backend` note is not written anywhere in {cls}'s own source, so "
            f"it was taken from another section:\n  {note}"
        )


def _class_source(name: str) -> str:
    """The source text of one dataclass in `config.py`, header to header."""
    src = (ROOT / "src" / "yazses" / "config.py").read_text(encoding="utf-8")
    start = src.index(f"class {name}")
    nxt = src.find("\nclass ", start)
    return src[start:] if nxt < 0 else src[start:nxt]


def _strip_comment_marks(text: str) -> str:
    """Comment punctuation and line breaks removed, so a wrapped note can be looked
    for in the source it was joined from."""
    return re.sub(r"\s+", " ", re.sub(r"#:?", " ", text)).strip()


def test_a_hash_inside_a_string_default_is_not_published_as_documentation(gen):
    assert gen._trailing_comment('    key: str = "#"') == ""
    assert gen._trailing_comment('    key: str = "# no"  # yes') == "yes"
    assert gen._trailing_comment("    key: int = 1") == ""


def test_a_wrapped_comment_is_joined_rather_than_truncated(gen):
    """Truncation is silent and the dropped half is the part that did not fit — which
    is where the unusual value gets explained. `[recimport] language` lost the half
    naming `"translate"`, leaving that magic value documented nowhere on the page."""
    lines = [
        '    language: str = "en"               # Whisper code ("en"); "" auto-detects;',
        '                                       # "translate" renders English',
        '    other: int = 0',
    ]
    assert gen._with_continuations(lines, 0) == (
        'Whisper code ("en"); "" auto-detects; "translate" renders English'
    )


def test_a_leading_comment_is_not_stolen_by_the_field_above(gen):
    """Leading comments are the commoner shape in `config.py`; attaching one to the
    preceding field would misfile it *and* leave its own field undocumented."""
    lines = [
        "    first: int = 0                     # belongs to first",
        "    # this documents `second`, not `first`",
        "    second: int = 0",
    ]
    assert gen._with_continuations(lines, 0) == "belongs to first"


def test_a_pipe_in_a_note_is_escaped_so_the_table_keeps_its_shape(gen):
    assert gen._md_cell("txt | md | srt") == r"txt \| md \| srt"


def test_the_max_speakers_trap_reaches_the_page_a_user_edits():
    """The whole point. `max_speakers` names a cap and is an exact count, and the
    reference is the surface where that has to be said."""
    text = REFERENCE.read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if re.match(r"\|\s*`max_speakers`", ln)]
    assert rows, "no max_speakers row in the configuration reference"
    described = [ln for ln in rows if "EXACT" in ln or "exact" in ln]
    assert len(described) >= 2, (
        "[recimport] and [meeting] both take max_speakers and both feed the sherpa "
        "backend, so both rows must warn:\n  " + "\n  ".join(rows)
    )


def test_the_reference_carries_notes_for_a_substantial_share_of_keys():
    """A guard that only checks one row passes on a page where the column was dropped
    everywhere else."""
    text = REFERENCE.read_text(encoding="utf-8")
    assert "| Key | Type | Default | Status | Notes |" in text
    key_rows = re.findall(r"^\|\s*`[a-z][a-z0-9_.]*`\s*\|", text, re.MULTILINE)
    noted = [
        ln for ln in text.splitlines()
        if re.match(r"\|\s*`[a-z][a-z0-9_.]*`\s*\|", ln)
        and ln.rstrip().rstrip("|").rsplit("|", 1)[-1].strip()
    ]
    assert len(key_rows) > 400
    assert len(noted) > 100, (
        f"only {len(noted)} of {len(key_rows)} keys carry a note; the column is "
        "derived from config.py's trailing comments, so this dropping means the "
        "extraction broke rather than that the comments went away"
    )


def test_a_leading_comment_block_documents_the_field_below_it(gen):
    """The keys most worth documenting are the ones whose explanation does not fit
    after the field. Reading only trailing comments left `[stt] engine`, `model`,
    `language`, `initial_prompt` and 51 others with an empty Notes cell — the exact
    keys a user is most likely to edit by hand."""
    lines = [
        "    # Which backend decodes audio. Two sentences, because one",
        "    # would not have been enough to say it.",
        '    engine: str = "faster-whisper"',
    ]
    assert gen._leading_block(lines, 2) == (
        "Which backend decodes audio. Two sentences, because one would not have been "
        "enough to say it."
    )


def test_a_wrapped_trailing_comment_is_not_taken_as_the_next_fields_leading_block(gen):
    """The one way reading leading comments can go wrong. A continuation sits in the
    column of the `#` that opened the trailing comment; a leading block sits at the
    field indent. Confuse them and the note lands on the wrong key — and the key it
    was written for is left blank."""
    lines = [
        '    first: int = 0                     # belongs to first, and wraps',
        "                                       # onto this line",
        "    second: int = 0",
    ]
    assert gen._leading_block(lines, 2) == ""
    assert gen._with_continuations(lines, 0) == "belongs to first, and wraps onto this line"


def test_the_sphinx_colon_spelling_does_not_reach_the_page(gen):
    """`config.py` writes `#:` in two sections. Publishing the marker put a stray
    `": "` at the head of five notes."""
    lines = [
        "    #: Spoken questions allowed per rolling hour.",
        "    ask_human_per_hour: int = 3",
    ]
    assert gen._leading_block(lines, 1) == "Spoken questions allowed per rolling hour."


def test_the_stt_section_a_user_edits_first_is_documented_end_to_end():
    """`[stt]` is the section people change, and every key in it had an empty Notes
    cell while `config.py` explained all of them at length."""
    text = REFERENCE.read_text(encoding="utf-8")
    section = text.split("## `[stt]`", 1)[1].split("\n## ", 1)[0]
    rows = [ln for ln in section.splitlines() if ln.startswith("| `")]
    assert len(rows) >= 8, section
    blank = [ln.split("|")[1].strip() for ln in rows if ln.rstrip().endswith("|  |")]
    assert not blank, f"[stt] keys still undocumented on the reference page: {blank}"
