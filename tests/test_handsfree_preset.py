"""The hands-free preset expands to ordinary feature configs -- Phase 6 exit gate, part one (#410).

The roadmap's gate: ``[handsfree] enabled = true`` "expands to the same feature configs a user
could have written by hand -- asserted by a test that enables the preset, dumps the resolved
config and compares it to the hand-written equivalent". The oracle below is **written out
literally**, not derived from `handsfree/preset.py`: a test that asked the module what it sets
and compared that to itself would pass for any table.

Everything here is a config file and the loader. No camera, no daemon, no pointer.
"""
from __future__ import annotations

import dataclasses
import textwrap
from pathlib import Path

import pytest

from yazses.config import Config, HandsfreeConfig, load_config_checked
from yazses.gesture.engine import parse_chords
from yazses.handsfree import preset

# What a person would write by hand to get the same composition. Literal on purpose.
HAND_WRITTEN = """
[handsfree_safety]
enabled = true
stop_phrase = "pause hands free"

[cmdsafety]
enabled = true

[perception]
enabled = true

[gaze]
enabled = true
route_dictation = true
deixis = true
confirm_destructive = true
refuse_destructive_fallback = true

[headpointer]
enabled = true
dwell_enabled = true

[facegesture]
enabled = true
use_baseline = true
confidence_floor = 0.5

[gesture]
enabled = true

[gesture.chords]
"brow_raise+nod" = "recenter"
"brow_raise+shake" = "pause_pointer"
"""


def _load(tmp_path: Path, text: str, name: str = "config.toml"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return load_config_checked(path)


def _dump(cfg: Config) -> dict:
    """The resolved config as plain data, minus the preset's own section."""
    data = dataclasses.asdict(cfg)
    data.pop("handsfree")
    return data


# --------------------------------------------------------------------------- exit gate


def test_the_preset_resolves_to_exactly_the_hand_written_config(tmp_path):
    preset_cfg = _load(tmp_path, "[handsfree]\nenabled = true\n", "preset.toml")
    by_hand = _load(tmp_path, HAND_WRITTEN, "hand.toml")
    assert preset_cfg.problems == [] and by_hand.problems == []
    assert _dump(preset_cfg.config) == _dump(by_hand.config)


def test_the_comparison_is_not_vacuous(tmp_path):
    # The hand-written file really differs from a default install in every section it names,
    # so equality above means the preset set those, not that nothing was set.
    default = _dump(Config())
    by_hand = _dump(_load(tmp_path, HAND_WRITTEN).config)
    differing = {k for k in default if default[k] != by_hand[k]}
    assert differing == {
        "handsfree_safety", "cmdsafety", "perception", "gaze", "headpointer", "facegesture", "gesture",
    }


def test_off_by_default_changes_nothing(tmp_path):
    assert Config().handsfree.enabled is False
    plain = _load(tmp_path, "[stt]\nmodel = 'tiny'\n", "a.toml")
    same_plus_off = _load(tmp_path, "[stt]\nmodel = 'tiny'\n[handsfree]\nenabled = false\n", "b.toml")
    assert _dump(plain.config) == _dump(same_plus_off.config)
    assert _dump(plain.config) == _dump(dataclasses.replace(Config(), stt=plain.config.stt))
    assert preset.expand({}).active is False
    raw = {"headpointer": {"x_gain": -1.0}}
    assert preset.apply(raw, preset.expand(raw)) == raw


def test_the_resolved_config_is_what_the_file_loader_sees_everywhere(tmp_path):
    # The preset reaches every consumer of load_config -- features, status, doctor -- because it
    # is applied to the file's data, not to one daemon's copy.
    from yazses.system.features import feature_status

    cfg = _load(tmp_path, "[handsfree]\nenabled = true\n").config
    on = {f.slug for f in feature_status(cfg) if f.on}
    assert {"headpointer", "gaze", "facegesture", "gesture", "cmdsafety"} <= on


# --------------------------------------------------------------------------- ownership


def test_a_key_you_wrote_wins_and_explain_says_so(tmp_path):
    loaded = _load(
        tmp_path,
        """
        [handsfree]
        enabled = true
        [headpointer]
        dwell_enabled = false
        x_gain = -300.0
        """,
    )
    assert loaded.problems == []
    assert loaded.config.headpointer.dwell_enabled is False
    assert loaded.config.headpointer.x_gain == -300.0
    assert loaded.config.headpointer.enabled is True  # the rest of the section is still filled in
    expansion = preset.expand({
        "handsfree": {"enabled": True}, "headpointer": {"dwell_enabled": False, "x_gain": -300.0},
    })
    dwell = next(r for r in expansion.resolved if r.setting.key == "dwell_enabled")
    assert dwell.source == "yours" and dwell.overridden
    text = "\n".join(preset.render(expansion, enabled_in_file=True))
    assert "YOURS (preset would set true)" in text
    # A user value equal to the preset's is reported as theirs, not as an override.
    same = preset.expand({"handsfree": {"enabled": True}, "headpointer": {"enabled": True}})
    enabled = next(r for r in same.resolved if (r.setting.section, r.setting.key) == ("headpointer", "enabled"))
    assert enabled.source == "yours" and not enabled.overridden


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("handsfree_safety", "enabled", "false"),
        ("cmdsafety", "enabled", "false"),
        ("gaze", "confirm_destructive", "false"),
        ("gaze", "refuse_destructive_fallback", "false"),
    ],
)
def test_weakening_the_safety_floor_refuses_the_whole_preset_and_names_the_key(
    tmp_path, section, key, value
):
    loaded = _load(tmp_path, f"[handsfree]\nenabled = true\n[{section}]\n{key} = {value}\n")
    cfg = loaded.config
    assert cfg.headpointer.enabled is False and cfg.gaze.enabled is False  # nothing half-applied
    assert cfg.gesture.enabled is False and cfg.facegesture.enabled is False
    messages = [str(p) for p in loaded.problems]
    assert any(f"[{section}] {key} = false" in m and "[handsfree] [" not in m for m in messages)
    assert any(m.startswith("[handsfree] enabled: preset not applied") for m in messages)


def test_refusal_does_not_apply_to_a_floor_key_the_preset_does_not_use(tmp_path):
    # Gaze is switched off, so its confirmation keys are not part of the preset and a user
    # value there is simply theirs.
    loaded = _load(
        tmp_path,
        "[handsfree]\nenabled = true\ngaze = false\n[gaze]\nconfirm_destructive = false\n",
    )
    assert not any("preset not applied" in str(p) for p in loaded.problems)
    assert loaded.config.headpointer.enabled is True and loaded.config.gaze.enabled is False


def test_a_section_that_is_not_a_table_is_left_alone_and_reported(tmp_path):
    expansion = preset.expand({"handsfree": {"enabled": True}, "headpointer": "yes"})
    assert any("[headpointer] is not a table" in n for n in expansion.notes)
    assert all(r.setting.section != "headpointer" for r in expansion.resolved)
    # ...and the loader survives it the way it survives it without a preset.
    loaded = _load(tmp_path, 'headpointer = "yes"\n[handsfree]\nenabled = true\n')
    assert loaded.config.headpointer.enabled is False


def test_applying_twice_is_the_same_as_applying_once():
    raw = {"handsfree": {"enabled": True}, "headpointer": {"x_gain": -5.0}}
    once, _ = preset.resolve_raw(raw)
    twice, _ = preset.resolve_raw(once)
    assert once == twice


# --------------------------------------------------------------------------- subsets


def test_a_subset_composes_only_what_was_asked_for(tmp_path):
    loaded = _load(
        tmp_path,
        "[handsfree]\nenabled = true\ngaze = false\nswitch = false\nchords = false\ndwell = false\n",
    )
    cfg = loaded.config
    assert cfg.headpointer.enabled is True and cfg.headpointer.dwell_enabled is False
    assert (cfg.gaze.enabled, cfg.facegesture.enabled, cfg.gesture.enabled) == (False, False, False)
    assert cfg.gesture.chords == {}
    assert cfg.handsfree_safety.enabled is True, "the stop path is not optional"
    assert cfg.perception.enabled is True


def test_no_camera_role_means_no_camera_key(tmp_path):
    cfg = _load(
        tmp_path,
        "[handsfree]\nenabled = true\ngaze = false\npointer = false\nswitch = false\nchords = false\n",
    ).config
    assert cfg.perception.enabled is False
    assert cfg.handsfree_safety.enabled is True


def test_the_recenter_chord_is_only_bound_when_there_is_a_pointer_to_recenter(tmp_path):
    cfg = _load(tmp_path, "[handsfree]\nenabled = true\npointer = false\n").config
    assert cfg.gesture.chords == {"brow_raise+shake": "pause_pointer"}


# --------------------------------------------------------------------------- the values


def test_every_key_the_preset_writes_is_a_real_setting_with_a_valid_value(tmp_path):
    # An unknown key or a rejected value is reported by the loader as a problem; none appear.
    loaded = _load(tmp_path, "[handsfree]\nenabled = true\n")
    assert loaded.problems == []
    for setting in preset.settings_for(HandsfreeConfig(enabled=True)):
        section = getattr(loaded.config, setting.section)
        assert getattr(section, setting.key) == setting.value, (setting.section, setting.key)


def test_the_chords_it_binds_are_accepted_by_the_chord_parser():
    bindings, problems = parse_chords(
        next(s for s in preset.settings_for(HandsfreeConfig(enabled=True)) if s.key == "chords").value
    )
    assert problems == []
    assert bindings == {"brow_raise+nod": "recenter", "brow_raise+shake": "pause_pointer"}


def test_the_preset_does_not_restate_any_tuned_number():
    # Gains, dead zone, speed caps, dwell radius/hold and the staleness window keep the defaults
    # of the feature that owns them; the preset adds exactly one number of its own.
    numbers = [
        s for s in preset.settings_for(HandsfreeConfig(enabled=True))
        if isinstance(s.value, (int, float)) and not isinstance(s.value, bool)
    ]
    assert [(s.section, s.key) for s in numbers] == [("facegesture", "confidence_floor")]
    assert numbers[0].value == preset.SWITCH_CONFIDENCE_FLOOR


def test_explain_says_provisional_and_what_it_leaves_out():
    text = "\n".join(preset.render(preset.expand({}, assume_enabled=True), enabled_in_file=False))
    assert "PROVISIONAL" in text
    assert "OFF in your config" in text and "`yazses handsfree enable` would set" in text
    assert "mousegrid" in text and "not wired" in text
    assert "[safety floor]" in text
    assert "yazses handsfree pause" in text, "a stop path that needs no pointer must be listed"
    assert "overlay" in text, "dwell needs the overlay and explain must say so"


def test_explain_prints_no_sample_values():
    text = "\n".join(preset.render(preset.expand({}, assume_enabled=True), enabled_in_file=False))
    for word in ("yaw", "pitch", "landmark", "blendshape score"):
        assert word not in text.lower()


# --------------------------------------------------------------------------- doctor


def test_doctor_explains_the_preset_prerequisites_with_no_camera_and_no_pointer(tmp_path, monkeypatch):
    """The preset resolves to ordinary config, so the existing doctor rows already see it."""
    from yazses.handsfree import probe as probe_mod
    from yazses.system import doctor as doctor_mod
    from yazses.system.doctor import _handsfree_checks

    # "No pointer" is a property of this machine's session, not of the config: on macOS and Windows
    # the backend is known, so the row is rightly OK there. Pin a session with no pointer backend,
    # as test_doctor_handsfree_rows.py does, so the test means the same on every OS.
    headless = probe_mod.PointerEnvironment("headless", None, None, False)
    monkeypatch.setattr(probe_mod, "read_pointer_environment", lambda cfg, **kw: headless)
    monkeypatch.setattr(doctor_mod, "_headpointer_daemon_view", lambda platform: (False, None))

    class _Platform:
        name = "linux"

        class paths:
            data_dir = tmp_path

    cfg = _load(tmp_path, "[handsfree]\nenabled = true\n").config
    rows = _handsfree_checks(
        cfg, _Platform(), ("Camera", "FAIL", "no camera device"),
        unwired=frozenset(), read_context=lambda: None,
    )
    by_label = {label: (status, detail) for label, status, detail in rows}
    assert {"Hands-free safety", "Hands-free perception", "Pointer output"} <= set(by_label)
    assert by_label["Hands-free perception"][0] == "SKIP"
    assert "Camera row" in by_label["Hands-free perception"][1]
    assert by_label["Pointer output"][0] != "OK", "an unknown pointer backend must not read as OK"


# --------------------------------------------------------------------------- a subset must still work


def test_a_preset_without_the_pointer_does_not_leave_the_gate_waiting_for_a_pointer(tmp_path):
    """`pointer = false` left a never-sampling `headpointer` source in the gate, so the global state
    stayed PAUSED for ever and every `handsfree resume` was refused for it. A source is registered
    only when the thing that feeds it can run."""
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = _load(tmp_path, "[handsfree]\nenabled = true\npointer = false\n").config
    gate = Daemon(config=cfg, platform=get_platform())._build_handsfree_safety(cfg)
    assert [s.name for s in gate.status().sources] == ["gesture"]
    gate.sample("gesture")
    assert gate.resume().ok is True
