"""Config keys the loader accepts, validates, documents — and no code ever reads.

`[injection] fallback_to_clipboard` was one of these until v2.24.0: it appeared in
seventeen places across the docs and the example configs people copy, defaulted to
`true`, and nothing read it — so anyone who turned it off was silently overruled.
It was found by hand. This is the mechanical version of that search.

Two confirmed by reading the code that should have used them:

* `[audio] channels` — documented with default `1`; `audio/recorder.py` passes a
  literal `channels=1` to sounddevice. Setting `2` gets you mono.
* `[tray] poll_interval_s` — documented with default `1.0`; `tray/app.py` polls on
  a module-level `_FAST_POLL_INTERVAL_S = 0.15`.

**A ledger, not a gate**, following `test_orphan_modules.py` and for the same
reason it gives: listing the known set means the suite passes today and fails the
moment a 64th appears, or when one is finally wired and its entry goes stale.
Demanding 63 fixes in one commit would just get the test deleted. Many of these
belong to features honestly registered as not-yet-wired, where an unread key is
the expected state rather than a defect; the point is that the pile stops growing
silently.

The detector and the ledger now live in `scripts/config_status.py`, because they had
a second reader all along and did not know it. This docstring used to end *"whether
the documentation should mark them is a separate question, and a real one: today a
reader cannot tell which knobs do anything."* It was real: `docs/configuration.md`
listed all 447 keys in one `Key | Type | Default` table with `sample_rate` read and
`channels` — the row directly beneath it — not, and nothing to separate them. The
generator now reads the same ledger and renders a Status column from it, so the page
cannot describe a different set of inert keys than this test gates on.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    """Load a `scripts/` module by path — `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_status = _load("config_status")
KNOWN_UNREAD = _status.KNOWN_UNREAD
_unread = _status.unread_fields
_without_comments = _status.without_comments

REFERENCE = ROOT / "docs" / "configuration.md"
INERT_MARK = "⚠️ inert"


# --- the pile itself ----------------------------------------------------------


def test_no_new_config_key_joins_the_unread_pile():
    new = sorted(_unread() - KNOWN_UNREAD)
    assert not new, (
        "config keys the loader accepts and documents but nothing reads:\n  "
        + "\n  ".join(new)
        + "\n\nWire it, or add it to KNOWN_UNREAD with the reason."
    )


def test_the_ledger_has_no_stale_entries():
    """A key that has since been wired must leave, or the ledger stops meaning anything."""
    fixed = sorted(KNOWN_UNREAD - _unread())
    assert not fixed, (
        "these are now read by code and should be removed from KNOWN_UNREAD:\n  "
        + "\n  ".join(fixed)
    )


def test_the_detector_finds_a_key_that_is_genuinely_read():
    """Proves the sweep can return a negative, rather than flagging everything.

    `[accessibility] vad_threshold` is read on the dictation hot path, so it must
    never appear as unread. Without this the two tests above would still pass if
    the regex silently matched nothing.
    """
    unread = _unread()
    for live in ("AccessibilityConfig.vad_threshold", "SttConfig.model", "HotkeyConfig.key"):
        assert live not in unread, f"{live} is read by real code but was called unread"


def test_a_comment_cannot_make_an_unread_key_look_wired():
    """The flaw this guard had, and the reason it was worth fixing here.

    The match ran over raw file text, so a comment naming a key registered it as
    read — in a guard whose entire job is to notice keys nothing reads. Hit for
    real: a comment in `system/report.py` saying the snippets table is *unwired*
    was itself enough to mark that field as wired.
    """
    stripped = _without_comments(
        "x = cfg.audio.device  # also mentions .max_record_seconds\n"
    )
    assert ".max_record_seconds" not in stripped
    assert "cfg.audio.device" in stripped, "the attribute access must survive intact"


def test_stripping_comments_does_not_damage_code_or_strings():
    """Rebuilding from token strings tore `cfg.audio.device` into three lines, so
    `.device` stopped matching and forty genuinely-read keys were reported unread.

    A `#` inside a string literal is not a comment, and cutting there would remove
    real references.
    """
    stripped = _without_comments('y = "a # not a comment"\nz = obj.real_attr\n')
    assert 'a # not a comment' in stripped
    assert "obj.real_attr" in stripped


# --- the ledger reaches the page the user actually edits ----------------------
#
# ⚠ `test_gen_docs.py::test_generated_doc_is_in_sync` cannot cover any of this. It
# compares the committed page against what the generator produces *now*, so dropping
# the Status column from the generator keeps it perfectly green — both sides change
# together. Only an assertion against the rendered page can notice.


def _reference_rows() -> dict[str, str]:
    """`section.key` → its Status cell, read out of the committed reference page."""
    rows: dict[str, str] = {}
    section = ""
    for line in REFERENCE.read_text(encoding="utf-8").splitlines():
        if m := re.fullmatch(r"## `\[([a-z][a-z0-9_.]*)\]`", line.strip()):
            section = m.group(1)
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if section and len(cells) == 4 and (m := re.fullmatch(r"`([a-z][a-z0-9_.]*)`", cells[0])):
            rows[f"{section}.{m.group(1)}"] = cells[3]
    return rows


def test_the_reference_page_is_actually_being_parsed():
    """A guard over an empty set passes on everything — this repo's most repeated
    self-inflicted wound, and the reason the parse is asserted before it is used."""
    rows = _reference_rows()
    assert len(rows) > 400, f"only parsed {len(rows)} key rows out of the reference"
    assert rows["stt.model"] == "", "a read key must carry an empty Status cell"
    assert rows["audio.channels"] == INERT_MARK


def test_the_reference_marks_exactly_the_keys_the_ledger_knows_are_inert():
    """The defect this closes: `sample_rate` is read, `channels` is the next row down
    and is not, and the page rendered them identically.

    Asserted in both directions. A missing mark leaves a reader turning a knob that
    does nothing; a spurious one tells them a working setting is dead, which is worse
    — they would stop using it.
    """
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from yazses.config import Config

    expected = _status.inert_dotted_keys(Config())
    marked = {k for k, status in _reference_rows().items() if INERT_MARK in status}

    assert not (expected - marked), (
        "inert keys the reference does not mark:\n  " + "\n  ".join(sorted(expected - marked))
    )
    assert not (marked - expected), (
        "keys the reference calls inert that the ledger says are read:\n  "
        + "\n  ".join(sorted(marked - expected))
    )


def test_every_ledger_entry_survives_the_translation_to_section_names():
    """The ledger is keyed by class, the page by TOML section. A mapping that resolved
    nothing would mark nothing and both directions of the test above would still pass,
    because an empty set is a subset of everything."""
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from yazses.config import Config

    dotted = _status.inert_dotted_keys(Config())
    assert len(dotted) == len(KNOWN_UNREAD), (
        f"{len(KNOWN_UNREAD)} ledger entries resolved to only {len(dotted)} section keys"
    )


def test_the_page_says_what_inert_means_and_counts_it_from_the_ledger():
    """A marker no one has defined is decoration. The legend must define it, and its
    count must be the ledger's — a hand-typed number is the drift this whole change
    is about (ADR-019 carried a hand-written 'seven' that had been five for months).
    """
    text = REFERENCE.read_text(encoding="utf-8")
    assert f"**{len(KNOWN_UNREAD)} of these" in text, "the legend's count is not the ledger's"
    assert "no code reads them" in text
    assert "changes nothing" in text


# --- the other copyable surface ----------------------------------------------


def test_no_example_config_offers_a_knob_that_does_nothing():
    """`examples/` is what people copy, and `build-deb.sh` ships
    `config.example.toml` into `/usr/share/yazses/`.

    `test_app_example_configs.py` already rejects a key that does not **exist** —
    `load_config_checked` reports it as a dropped unknown. An inert key passes that
    check perfectly: it exists, it validates, it has a default. `[audio] channels`
    sat in the hand-written example on the line after `sample_rate`, and copying it
    taught a reader that stereo capture was a setting. It is not.
    """
    import re
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from yazses.config import Config

    inert = _status.inert_dotted_keys(Config())
    offenders: list[str] = []
    examples = sorted((ROOT / "examples").glob("*.toml"))
    assert examples, "no example configs found — an empty sweep proves nothing"

    for path in examples:
        text = path.read_text(encoding="utf-8")
        section = ""
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if m := re.fullmatch(r"\[([a-z][a-z0-9_.]*)\]", line):
                section = m.group(1)
                continue
            if not section or not (m := re.match(r"([a-z][a-z0-9_]*)\s*=", line)):
                continue
            key = m.group(1)
            if f"{section}.{key}" in inert and not _discloses(text, key):
                offenders.append(f"{path.name}: [{section}] {key}")

    assert not offenders, (
        "example configs offering settings nothing reads:\n  "
        + "\n  ".join(offenders)
        + "\n\nRemove the line, wire the key, or say `inert` next to its name in a "
        "comment. A copied setting that does nothing is worse than an absent one — "
        "the reader believes they configured something."
    )


_DISCLOSURE_WINDOW = 200


def _discloses(text: str, key: str) -> bool:
    """True when the file names *key* within `_DISCLOSURE_WINDOW` chars of "inert".

    Deletion is not always the right fix. `config.vscode.toml` sets
    `lsp_enabled = false` under a header that spends five lines saying the key is
    INERT in this build and why — that file is *more* honest than one where the key
    is simply absent, because a VS Code user who has read about the LSP bridge is
    told directly that it does nothing yet.

    Proximity rather than a file-wide search for the word: one disclosure paragraph
    would otherwise excuse every inert key anywhere else in the same file, which is
    the blanket exemption this guard exists to prevent.
    """
    lowered = text.lower()
    for mark in re.finditer(r"inert", lowered):
        window = lowered[
            max(0, mark.start() - _DISCLOSURE_WINDOW) : mark.end() + _DISCLOSURE_WINDOW
        ]
        if re.search(r"\b" + re.escape(key) + r"\b", window):
            return True
    return False


def test_a_disclosed_inert_key_is_accepted_and_an_undisclosed_one_is_not():
    """The exemption has to be narrow or it is not an exemption.

    Both directions, plus the distance rule — a disclosure about one key must not
    cover a different key far away in the same file.
    """
    assert _discloses("# [commands] lsp_enabled is INERT in this build\n", "lsp_enabled")
    assert not _discloses("# lsp_enabled turns on the bridge\n", "lsp_enabled")
    assert not _discloses(
        "# channels is INERT\n" + "# filler\n" * 60 + "# note about max_speed\n",
        "max_speed",
    ), "a disclosure must not reach across the whole file"


def test_the_example_sweep_can_actually_fail(tmp_path: Path):
    """Proves the parse finds keys at all. The sweep passed trivially at one point
    because `channels` had already been removed everywhere — a green that meant
    nothing until it was shown it could go red."""
    import re as _re
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from yazses.config import Config

    inert = _status.inert_dotted_keys(Config())
    assert "audio.channels" in inert, "the fixture below relies on this being inert"

    bad = tmp_path / "config.bad.toml"
    bad.write_text("[audio]\nchannels = 2\n", encoding="utf-8")

    section, found = "", []
    for raw in bad.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if m := _re.fullmatch(r"\[([a-z][a-z0-9_.]*)\]", line):
            section = m.group(1)
        elif section and (m := _re.match(r"([a-z][a-z0-9_]*)\s*=", line)):
            if f"{section}.{m.group(1)}" in inert:
                found.append(m.group(1))
    assert found == ["channels"]
