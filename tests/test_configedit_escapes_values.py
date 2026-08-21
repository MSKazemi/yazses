"""`yazses audio use 'My "Best" Mic'` wrote a config.toml that does not parse.

`set_config_key` had **two** renderings of a value and only one escaped anything.
`_render_toml_value` (the inferred path) escaped backslashes and quotes;
the explicit ``quote=True`` branch interpolated raw:

    rendered = f'"{value}"' if quote else str(value)

That is the branch `yazses audio use` and the settings window take, so a microphone
named ``My "Best" Mic`` produced:

    device = "My "Best" Mic"

An unparseable `config.toml` is not a contained failure here. `configcheck` falls back
to *"could not be read; using defaults throughout"* — so **every** setting the user had
is silently reset by an unrelated one-word command. Neither renderer handled a newline,
which is illegal inside a TOML basic string and does exactly the same thing.

Found by writing thirteen adversarial values through the real function and re-parsing
the file with `tomllib` each time: five corrupted it or lost data. A backslash was the
quiet one — ``path\\to\\thing`` round-tripped with a real tab in it, because `\\t` was
read back as an escape.

Both paths now go through one `quote_toml_string`.

## Note on the settings window

`settingsui` collapses newlines in `[stt] initial_prompt` before calling here, precisely
because a literal newline reset the whole `[stt]` section. That stays — defence in depth
— but it is no longer the only thing standing between a pasted two-line prompt and a
wiped section.
"""

from __future__ import annotations

import tomllib

import pytest

from yazses.system.configedit import quote_toml_string, set_config_key

BASE = """# a comment that must survive
[stt]
model = "base.en"   # trailing comment
language = "en"

[audio]
device = ""
"""

#: Values that broke the writer, plus ones that always worked and must keep working.
VALUES = [
    pytest.param('say "hi" now', id="double-quote"),
    pytest.param('My "Best" Mic', id="quoted-device-name"),
    pytest.param("line one\nline two", id="newline"),
    pytest.param('a"""b', id="triple-quote"),
    pytest.param("path\\to\\thing", id="backslash"),
    pytest.param("a\tb", id="tab"),
    pytest.param("carriage\rreturn", id="carriage-return"),
    pytest.param("bell\x07and\x00nul", id="control-chars"),
    pytest.param("héllo — ünïcode ✓", id="unicode"),
    pytest.param("value # not a comment", id="hash"),
    pytest.param("[stt]", id="looks-like-a-section"),
    pytest.param("a = b", id="looks-like-an-assignment"),
    pytest.param("", id="empty"),
    pytest.param("plain text", id="plain"),
]


def _write_and_reparse(tmp_path, section, key, value, **kw):
    path = tmp_path / "config.toml"
    path.write_text(BASE, encoding="utf-8")
    set_config_key(path, section, key, value, **kw)
    text = path.read_text(encoding="utf-8")
    return tomllib.loads(text), text  # raises if the file was corrupted


@pytest.mark.parametrize("value", VALUES)
def test_the_explicit_quote_path_round_trips(tmp_path, value) -> None:
    """`quote=True` — the branch `audio use` and the settings window use."""
    parsed, text = _write_and_reparse(tmp_path, "stt", "initial_prompt", value, quote=True)
    assert parsed["stt"]["initial_prompt"] == value
    assert "# a comment that must survive" in text
    assert parsed["stt"]["model"] == "base.en", "a neighbouring setting was lost"


@pytest.mark.parametrize("value", VALUES)
def test_the_inferred_path_round_trips(tmp_path, value) -> None:
    """`quote=None` — the type-inferred branch. It escaped less than it needed to."""
    parsed, _text = _write_and_reparse(tmp_path, "stt", "initial_prompt", value)
    assert parsed["stt"]["initial_prompt"] == value


def test_the_reported_case(tmp_path) -> None:
    """The exact call that started this: a microphone name containing quotes."""
    parsed, _ = _write_and_reparse(tmp_path, "audio", "device", 'My "Best" Mic', quote=True)
    assert parsed["audio"]["device"] == 'My "Best" Mic'


def test_both_paths_agree(tmp_path) -> None:
    """Two renderings of one rule is how they came to disagree."""
    for value in ('a "quoted" thing', "back\\slash", "new\nline"):
        explicit, _ = _write_and_reparse(tmp_path, "stt", "initial_prompt", value, quote=True)
        inferred, _ = _write_and_reparse(tmp_path, "stt", "initial_prompt", value)
        assert explicit["stt"]["initial_prompt"] == inferred["stt"]["initial_prompt"] == value


def test_non_strings_are_not_quoted(tmp_path) -> None:
    """The escaper must not swallow the bool/number rendering."""
    parsed, _ = _write_and_reparse(tmp_path, "stt", "language", True)
    assert parsed["stt"]["language"] is True
    parsed, _ = _write_and_reparse(tmp_path, "accessibility", "vad_threshold", 0.02)
    assert parsed["accessibility"]["vad_threshold"] == 0.02


def test_the_escaper_is_pure_and_produces_a_quoted_scalar() -> None:
    assert quote_toml_string("plain") == '"plain"'
    assert quote_toml_string('a"b') == '"a\\"b"'
    assert quote_toml_string("a\\b") == '"a\\\\b"'
    assert quote_toml_string("a\nb") == '"a\\nb"'
    assert quote_toml_string("\x07") == '"\\u0007"'


def test_a_control_character_never_reaches_the_file_literally(tmp_path) -> None:
    """TOML has no literal form for these; unescaped they end the string."""
    _parsed, text = _write_and_reparse(
        tmp_path, "stt", "initial_prompt", "a\x00b\x1fc", quote=True
    )
    assert "\x00" not in text and "\x1f" not in text
