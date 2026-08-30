"""Config keys that are inert but look read, because another section shares the name.

`scripts/config_status.py` decides which keys are live by searching the tree for
`[."']<field>`. The match is by **name alone**, so a field name used by two sections
is reported read in both the moment either one reads it — and `docs/configuration.md`
then tells the user a dead knob works. 32 names are shared across sections and 216
(class, field) pairs rest on that match.

It is the third appearance of one collision, and the first that cannot be fixed in
the detector. A comment naming a key made it look read, and `without_comments` fixed
that; a dotted module path spelled like an attribute did the same, and `_IMPORT` fixed
that. Both were fixable because the noise is structural — a comment and an import can
be recognised without knowing any types. A sibling section's read cannot:
`config.format` in `postprocess/prosody.py` is a real read of `[prosody] format` and
is character-identical to what a read of `[outline] format` would look like.

Requiring a section-qualified `cfg.<section>.<key>` instead was measured and is worse.
It reports `[macros] path` and `[styleguard] path` as dead, and both are genuinely
read — through a short local (`mc.path`, `sg.path`) that no pattern predicts. A false
*inert* is the more damaging of the two errors: it tells someone a working setting
does nothing, which is exactly the harm this whole mechanism exists to prevent.

So `AMBIGUOUS_UNREAD` enumerates the blind spot, and this file keeps the enumeration
honest: every entry is re-checked for an attributable read, so wiring one turns the
suite red until its entry is removed.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_status = _load("config_status")
AMBIGUOUS_UNREAD = _status.AMBIGUOUS_UNREAD
KNOWN_UNREAD = _status.KNOWN_UNREAD


def _code() -> str:
    src = ROOT / "src" / "yazses"
    return "\n".join(
        _status.without_comments(p.read_text(encoding="utf-8", errors="ignore"))
        for p in sorted(src.rglob("*.py"))
        if p.name not in ("config.py", "configcheck.py")
    )


def _sections() -> dict[str, str]:
    """`ClassName` → the TOML section name it is mounted under."""
    from yazses.config import Config

    cfg = Config()
    return {
        type(getattr(cfg, f.name)).__name__: f.name
        for f in dataclasses.fields(cfg)
        if dataclasses.is_dataclass(getattr(cfg, f.name))
    }


def _attributable_reads(section: str, field: str, code: str) -> list[str]:
    """Lines that could only be a read of *this* section's *field*.

    Two shapes, both unambiguous: the section-qualified path, and a `getattr` naming
    the key inside the subsystem the section configures. Anything looser would match
    the sibling read that caused the problem in the first place.
    """
    pats = [
        re.compile(rf"\.{re.escape(section)}\.{re.escape(field)}\b"),
        re.compile(
            rf"getattr\(\s*[A-Za-z_][\w.]*\s*,\s*[\"']{re.escape(field)}[\"']"
        ),
    ]
    package = f"src/yazses/{section}/"
    hits = []
    for path in sorted((ROOT / "src" / "yazses").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        text = _status.without_comments(path.read_text(encoding="utf-8", errors="ignore"))
        for i, line in enumerate(text.splitlines(), 1):
            if pats[0].search(line):
                hits.append(f"{rel}:{i}: {line.strip()}")
            elif package in rel and pats[1].search(line):
                hits.append(f"{rel}:{i}: {line.strip()}")
    return hits


def test_the_two_ledgers_do_not_overlap():
    """An entry in both would be removed from one and stay inert via the other."""
    both = sorted(AMBIGUOUS_UNREAD & KNOWN_UNREAD)
    assert not both, f"listed in both ledgers: {both}"


def test_every_ambiguous_entry_names_a_real_field():
    """A renamed or deleted field must not leave a silent entry marking nothing."""
    known = {f"{cls}.{name}" for cls, name in _status.config_fields()}
    missing = sorted(AMBIGUOUS_UNREAD - known)
    assert not missing, f"no such config field: {missing}"


def test_no_ambiguous_entry_has_since_been_wired():
    """The reason this file exists: the entries must leave when they stop being true."""
    sections = _sections()
    code = _code()
    wired = {}
    for entry in sorted(AMBIGUOUS_UNREAD):
        cls, field = entry.split(".", 1)
        section = sections.get(cls)
        assert section, f"{cls} is not mounted on Config as a section"
        hits = _attributable_reads(section, field, code)
        if hits:
            wired[entry] = hits
    assert not wired, (
        "these are read by real code now and must leave AMBIGUOUS_UNREAD:\n"
        + "\n".join(f"  {k}\n      " + "\n      ".join(v) for k, v in wired.items())
    )


def test_the_wiring_check_can_return_a_positive():
    """A search that finds nothing reports compliance, so prove it finds something.

    `[audio] sample_rate` is read on the dictation hot path and shares its name with
    the inert `[tts] sample_rate` — the exact pair that motivated the ledger.
    """
    assert _attributable_reads("audio", "sample_rate", _code()), (
        "the check found no read of a key that is read everywhere"
    )
    assert not _attributable_reads("tts", "sample_rate", _code())


def test_the_kokoro_sample_rate_is_still_assigned_and_never_read():
    """`[tts] sample_rate` is the one entry the detector sees a *read* for.

    `KokoroTtsBackend.__init__` assigns `self._sample_rate = config.sample_rate` and
    nothing ever reads that attribute, which no name-based detector can distinguish
    from a setting that works. If a second occurrence appears the key may have been
    wired, and its ledger entry has to be re-judged by hand rather than left standing.
    """
    text = (ROOT / "src/yazses/tts/kokoro.py").read_text(encoding="utf-8")
    assert text.count("_sample_rate") == 1, (
        "`_sample_rate` is referenced more than once in the Kokoro backend; if it is "
        "now used, remove TtsConfig.sample_rate from AMBIGUOUS_UNREAD"
    )


def test_the_reference_page_marks_them_inert():
    """The whole point: the page the user edits must not present these as live."""
    from yazses.config import Config

    page = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    sections = _sections()
    for entry in sorted(AMBIGUOUS_UNREAD):
        cls, field = entry.split(".", 1)
        section = sections[cls]
        block = page.split(f"## `[{section}]`", 1)
        assert len(block) == 2, f"no section `[{section}]` on the reference page"
        body = block[1].split("\n## ", 1)[0]
        row = [ln for ln in body.splitlines() if ln.strip().startswith(f"| `{field}`")]
        assert row, f"no row for `{field}` under `[{section}]`"
        assert "⚠️ inert" in row[0], f"[{section}] {field} is still presented as live"
    assert Config() is not None
