"""`mic-level --set` said "updated" and left the threshold exactly as it was.

`update_threshold_in_config` replaced a `vad_threshold` assignment **anywhere in the
file**:

    re.subn(r"(?m)^[ \\t]*vad_threshold[ \\t]*=.*$", line, text)

So a key a user had put under the wrong section was rewritten instead of the real one, and
the function returned ``updated vad_threshold = …`` while
`[accessibility] vad_threshold` kept its previous value:

    [audio]
    vad_threshold = 0.09          <- rewritten, and dead: configcheck ignores it
    [accessibility]
    pre_speech_padding_ms = 300   <- the real setting, never touched

`configcheck` already prints *"[audio] vad_threshold: is not a known setting; ignored"*
about that very line, so the mistake was visible to the system and edited anyway.

It lands where it hurts most. `yazses mic-level --set` is what the documentation
recommends when words are being dropped — so the user is already stuck, runs the
suggested fix, is told it worked, and dictation still fails. The adaptive retuner writes
through the same function.

## Scope

`accessibility.vad_threshold` is the only key in the whole config with that name, so no
*correct* config could hit this — it needed the key to be misplaced. The fix also removes
the latent version: `[meeting]` already has `vad_backend` and `silero_threshold`, and a
`[meeting] vad_threshold` would have been silently clobbered by any `mic-level --set`.
"""

from __future__ import annotations

import pytest

from yazses.config import load_config
from yazses.system.miclevel import _section_span, update_threshold_in_config

NEW = 0.0012


def _write(tmp_path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.mark.parametrize(
    "name,body",
    [
        pytest.param(
            "wrong-section",
            "[audio]\nvad_threshold = 0.09\n\n[accessibility]\npre_speech_padding_ms = 300\n",
            id="key-under-the-wrong-section",
        ),
        pytest.param("right-section", "[accessibility]\nvad_threshold = 0.09\n", id="normal"),
        pytest.param(
            "no-key", "[accessibility]\npre_speech_padding_ms = 300\n", id="section-but-no-key"
        ),
        pytest.param("no-section", '[stt]\nmodel = "base.en"\n', id="no-section"),
        pytest.param("empty", "", id="empty-file"),
    ],
)
def test_the_setting_actually_changes(tmp_path, name: str, body: str) -> None:
    """Whatever the file looks like, the value the daemon reads must be the new one."""
    path = _write(tmp_path, body)
    update_threshold_in_config(path, NEW)
    assert load_config(path).accessibility.vad_threshold == NEW


def test_a_misplaced_key_is_not_the_one_edited(tmp_path) -> None:
    """The defect: the dead line was rewritten and the real one left alone."""
    path = _write(
        tmp_path,
        "[audio]\nvad_threshold = 0.09\n\n[accessibility]\npre_speech_padding_ms = 300\n",
    )
    update_threshold_in_config(path, NEW)
    text = path.read_text(encoding="utf-8")

    audio_block = text.split("[accessibility]")[0]
    assert "0.09" in audio_block, "the stray key under [audio] was rewritten"
    assert str(NEW) in text.split("[accessibility]")[1], "[accessibility] never got it"


def test_neighbouring_settings_survive(tmp_path) -> None:
    """A section-scoped edit must not disturb what is around it."""
    path = _write(
        tmp_path,
        "# my config\n[stt]\nmodel = \"small.en\"\n\n"
        "[accessibility]\n# keep me\nvad_threshold = 0.09\npre_speech_padding_ms = 400\n",
    )
    update_threshold_in_config(path, NEW)
    cfg = load_config(path)
    assert cfg.stt.model == "small.en"
    assert cfg.accessibility.pre_speech_padding_ms == 400
    assert "# my config" in path.read_text(encoding="utf-8")
    assert "# keep me" in path.read_text(encoding="utf-8")


def test_the_section_span_stops_at_the_next_header() -> None:
    """The mechanism, so an edit can never reach a neighbouring section."""
    text = "[accessibility]\na = 1\n[audio]\nb = 2\n"
    start, end = _section_span(text, "accessibility")
    body = text[start:end]
    assert "a = 1" in body
    assert "b = 2" not in body
    assert "[audio]" not in body


def test_a_missing_section_reports_nothing_found() -> None:
    assert _section_span("[stt]\nmodel = \"x\"\n", "accessibility") == (None, None)


def test_the_key_name_is_unique_today(tmp_path) -> None:
    """Why no *correct* config could hit this — and why the fix is still worth it.

    Only `accessibility.vad_threshold` carries the name now, but `[meeting]` already has
    `vad_backend` and `silero_threshold`; a `[meeting] vad_threshold` would have been
    clobbered by every `mic-level --set`.
    """
    import dataclasses

    from yazses.config import Config

    names = []

    def walk(obj, path=""):
        for f in dataclasses.fields(obj):
            v = getattr(obj, f.name)
            if dataclasses.is_dataclass(v):
                walk(v, f"{path}{f.name}.")
            elif f.name == "vad_threshold":
                names.append(f"{path}{f.name}")

    walk(Config())
    assert names == ["accessibility.vad_threshold"], names
