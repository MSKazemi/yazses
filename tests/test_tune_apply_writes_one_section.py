"""Approving one `tune` proposal must change one setting.

`set_toml_key` substituted the key **anywhere in the file**, with no section scope and no
``count``:

    re.subn(rf"(?m)^[ \\t]*{re.escape(key)}[ \\t]*=.*$", line, text)

Both `[stt]` and `[meeting]` carry a key called ``model``. So approving `yazses tune`'s
top proposal — *"Upgrade the STT model"*, `[stt] model` — also rewrote `[meeting] model`:

    [stt]
    model = "base.en"     ->  "small.en"     approved
    [meeting]
    model = "tiny.en"     ->  "small.en"     not approved, not mentioned

The user approves one change and gets two, in a feature they were not looking at. It is
the top proposal on a real corpus, so this is the most likely `--apply` to be run.

## Two writers, each missing what the other had

`set_toml_key` rendered arrays correctly and could not scope a section.
`configedit.set_config_key` scoped the section and rendered a list as a quoted Python
repr — ``filler_words = "['um', 'uh']"`` — which parses as a *string*, so `configcheck`
reports "should be a list" and falls back to the default, silently discarding an approved
change. Nothing passed it a list today, so that half was latent; the section blindness was
live.

There is now one writer and it does both. The list rendering is covered here because
`filler_words` is the one proposal whose value *is* a list, and it would have hit the
latent half the moment the two were merged the other way round.
"""

from __future__ import annotations

import tomllib

import pytest

from yazses.learning.analysis import set_toml_key

TWO_MODELS = """# my config
[stt]
model = "base.en"
language = "en"

[meeting]
model = "tiny.en"
notes = false
"""


@pytest.fixture
def config(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(TWO_MODELS, encoding="utf-8")
    return p


def _load(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_only_the_named_section_changes(config) -> None:
    """The defect: a key of the same name in another section was rewritten too."""
    set_toml_key(config, "stt", "model", "small.en")
    data = _load(config)
    assert data["stt"]["model"] == "small.en"
    assert data["meeting"]["model"] == "tiny.en", (
        "approving the STT model upgrade also changed the meeting transcription model"
    )


def test_the_other_section_can_still_be_targeted(config) -> None:
    """A fix that simply never matched would pass the test above."""
    set_toml_key(config, "meeting", "model", "medium.en")
    data = _load(config)
    assert data["meeting"]["model"] == "medium.en"
    assert data["stt"]["model"] == "base.en"


def test_neighbours_and_comments_survive(config) -> None:
    set_toml_key(config, "stt", "model", "small.en")
    assert _load(config)["stt"]["language"] == "en"
    assert _load(config)["meeting"]["notes"] is False
    assert "# my config" in config.read_text(encoding="utf-8")


def test_a_list_value_writes_a_toml_array(tmp_path) -> None:
    """`filler_words` is the one proposal whose value is a list.

    Written as `str(list)` it becomes a quoted Python repr, which parses as a *string* —
    `configcheck` then reports "should be a list" and falls back to the default, throwing
    away the change the user just approved.
    """
    p = tmp_path / "config.toml"
    p.write_text("[filters.disfluency]\nenabled = true\n", encoding="utf-8")
    set_toml_key(p, "filters.disfluency", "filler_words", ["um", "uh", "okay"])

    value = _load(p)["filters"]["disfluency"]["filler_words"]
    assert value == ["um", "uh", "okay"], f"not a TOML array: {value!r}"


def test_the_written_value_is_what_the_config_loads(tmp_path) -> None:
    """The only assertion that matters: what the daemon reads back."""
    from yazses.config import load_config

    p = tmp_path / "config.toml"
    p.write_text(TWO_MODELS, encoding="utf-8")
    set_toml_key(p, "accessibility", "vad_threshold", 0.0012)
    cfg = load_config(p)
    assert cfg.accessibility.vad_threshold == 0.0012
    assert cfg.stt.model == "base.en", "an unrelated section moved"


def test_both_sections_really_have_that_key_name() -> None:
    """The premise. If they diverge, this file stops demonstrating anything."""
    import dataclasses

    from yazses.config import Config

    cfg = Config()
    assert any(f.name == "model" for f in dataclasses.fields(cfg.stt))
    assert any(f.name == "model" for f in dataclasses.fields(cfg.meeting))
