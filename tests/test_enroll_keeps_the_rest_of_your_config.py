"""`yazses enroll` must not reset the accessibility settings it did not measure.

The wizard computes two values (`vad_threshold`, `min_silence_ms`) and used to write them
by deleting the whole `[accessibility]` section and appending a fresh one. That silently
reset every other key in it to its default, and the file it did this to is the user's
hand-edited `config.toml`.

`dysfluency_friendly` is the sharp end of it: that is the setting a disfluent speaker
turns on deliberately, and this is the wizard written for that user. Losing it as a side
effect of calibrating a microphone inverts the purpose of the command.

The other branch of the old writer round-tripped through `tomllib` + `tomli_w`, which
keeps the keys and destroys every comment in the file instead. It never ran: `tomli_w` is
declared by no extra and appears in `pyproject.toml` only inside a mypy override list, so
the destructive fallback was always the live path.

The survivor set is read off `AccessibilityConfig` rather than typed out here, so a field
added to that dataclass is covered the day it is added.
"""

from __future__ import annotations

import dataclasses

import pytest

from yazses.accessibility.enroll import _write_config
from yazses.config import AccessibilityConfig

#: What the wizard measures. Everything else in the section must be left alone.
MEASURED = {"vad_threshold", "min_silence_ms"}

UNTOUCHED_FIELDS = sorted(
    f.name for f in dataclasses.fields(AccessibilityConfig) if f.name not in MEASURED
)


def _toml_value(field) -> str:
    """Render a field's default as TOML so the fixture is a real, loadable file."""
    default = field.default
    if isinstance(default, bool):
        return "true" if not default else "false"  # deliberately NOT the default
    if isinstance(default, str):
        return '"calibrated"' if default != "calibrated" else '"default"'
    if isinstance(default, int):
        return str(default + 7)
    if isinstance(default, float):
        return str(default + 1.5)
    raise AssertionError(f"unhandled default type for {field.name}: {default!r}")


@pytest.fixture
def config_file(tmp_path):
    """A config whose every accessibility key is set to a NON-default value.

    Non-default on purpose: if the fixture used defaults, a writer that wiped the section
    would produce a file that still loads with the same values, and the test would pass
    while the user's settings were being destroyed.
    """
    lines = ["# hand-tuned, do not lose this", "", "[stt]", 'model = "small.en"  # bumped',
             "", "[accessibility]", "# measured in the quiet room"]
    for f in dataclasses.fields(AccessibilityConfig):
        if f.name not in MEASURED:
            lines.append(f"{f.name} = {_toml_value(f)}")
    lines += ["vad_threshold = 0.004", "", "[hotkey]", 'key = "KEY_RIGHTCTRL"  # WM clash']
    path = tmp_path / "config.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_fixture_actually_covers_the_section():
    """A parametrised survivor test over an empty list passes vacuously."""
    assert len(UNTOUCHED_FIELDS) >= 4, UNTOUCHED_FIELDS
    assert "dysfluency_friendly" in UNTOUCHED_FIELDS


@pytest.mark.parametrize("field_name", UNTOUCHED_FIELDS)
def test_every_unmeasured_accessibility_key_survives(config_file, field_name):
    before = config_file.read_text(encoding="utf-8")
    expected = next(
        line for line in before.splitlines() if line.startswith(f"{field_name} =")
    )

    _write_config(config_file, {"vad_threshold": 0.0081, "min_silence_ms": 700},
                  output_fn=lambda *a: None)

    after = config_file.read_text(encoding="utf-8")
    assert expected in after, f"{field_name} was reset; wanted {expected!r}"


def test_the_measured_values_are_actually_written(config_file):
    _write_config(config_file, {"vad_threshold": 0.0081, "min_silence_ms": 700},
                  output_fn=lambda *a: None)
    after = config_file.read_text(encoding="utf-8")
    assert "vad_threshold = 0.0081" in after
    assert "min_silence_ms = 700" in after
    assert "vad_threshold = 0.004" not in after, "the old value must be replaced, not kept"


def test_comments_and_other_sections_survive(config_file):
    _write_config(config_file, {"vad_threshold": 0.0081, "min_silence_ms": 700},
                  output_fn=lambda *a: None)
    after = config_file.read_text(encoding="utf-8")
    assert "# hand-tuned, do not lose this" in after
    assert "# measured in the quiet room" in after
    assert "# WM clash" in after
    assert 'model = "small.en"  # bumped' in after
