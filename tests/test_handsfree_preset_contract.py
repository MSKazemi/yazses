"""The hands-free preset keeps its promises when the machine, the file or the order is awkward (#410).

``tests/test_handsfree_preset.py`` pins the headline gate (the preset equals the hand-written
config). This file pins the properties a composition gets wrong without any test noticing:

1. **Idempotence.** Expanding twice is expanding once, for every subset of roles and for files that
   already carry some of the keys -- not just the one subset a test happened to pick.
2. **Ownership.** A key the user wrote is never rewritten, and the preset adds exactly the keys it
   reports as its own, nothing else.
3. **Reversibility.** Enable then disable returns the user's file to itself plus one table, and the
   *resolved* config to what it was before -- including a file full of comments and settings that
   are none of the preset's business.
4. **A default install is untouched.** No ``[handsfree]``, or ``enabled = false`` with every role
   chosen, resolves byte-for-byte to the config an install without the feature has.
5. **Degradation is stated, not half-done.** With no camera, no pointer backend, a backend that
   cannot move relatively, or no overlay, the composed pieces say why they are not running, the
   pointer receives nothing, and the global gate cannot be re-armed from a signal that never came.
6. **Nothing from this machine is echoed** by ``explain`` or by a refusal: a stop phrase, a path or a
   table the user wrote is described by kind and size, never printed.

No camera, no display, no pointer, no daemon: a config file, the loader, the real builders, and
fakes. Time is a list the test advances.
"""
from __future__ import annotations

import dataclasses
import itertools
import types

import pytest
from typer.testing import CliRunner

from tests.pointer_fake import FakePointerSink, PointerActionKind
from yazses import cli
from yazses.cli import app
from yazses.config import Config, load_config_checked
from yazses.handsfree import preset
from yazses.handsfree.safety import SafetyState, gate_from_config
from yazses.headpointer.controller import SOURCE_NAME
from yazses.headpointer.runtime import build_headpointer
from yazses.ipc.client import IpcUnreachableError
from yazses.perception.signals import HeadPoseSignal, PerceptionSample
from yazses.pointer.base import PointerCapabilities

runner = CliRunner()

ROLES = ("gaze", "pointer", "dwell", "switch", "chords", "voice_stop")

#: Every subset of roles the preset can be asked to compose: 2**6 files, derived, not listed.
ALL_SUBSETS = [dict(zip(ROLES, flags, strict=True)) for flags in itertools.product((True, False), repeat=len(ROLES))]


def _subset_id(roles: dict[str, bool]) -> str:
    return "+".join(name for name, on in roles.items() if on) or "no-roles"


SUBSET_PARAMS = [pytest.param(roles, id=_subset_id(roles)) for roles in ALL_SUBSETS]


def _raw(roles: dict[str, bool], **extra: dict) -> dict:
    return {"handsfree": {"enabled": True, **roles}, **extra}


# --------------------------------------------------------------------------- 1. idempotence


def test_the_subset_grid_is_not_vacuous() -> None:
    assert len(ALL_SUBSETS) == 64 and len({_subset_id(r) for r in ALL_SUBSETS}) == 64


@pytest.mark.parametrize("roles", SUBSET_PARAMS)
def test_expanding_the_output_again_changes_nothing_for_every_subset_of_roles(roles: dict[str, bool]) -> None:
    once, first = preset.resolve_raw(_raw(roles))
    twice, second = preset.resolve_raw(once)
    assert twice == once
    # Second time round every key is already the user's own, so the preset has nothing left to add.
    assert not [r for r in second.resolved if r.source == "preset"]
    assert second.refusal == "" and first.refusal == ""
    assert [(r.setting.section, r.setting.key, r.effective) for r in second.resolved] == [
        (r.setting.section, r.setting.key, r.effective) for r in first.resolved
    ]


@pytest.mark.parametrize("roles", SUBSET_PARAMS)
def test_the_preset_only_adds_keys_and_adds_exactly_the_ones_it_reports(roles: dict[str, bool]) -> None:
    user = {"stt": {"model": "tiny"}, "headpointer": {"x_gain": -300.0}, "gaze": {"deixis": False}}
    raw = _raw(roles, **{k: dict(v) for k, v in user.items()})
    expansion = preset.expand(raw)
    out = preset.apply(raw, expansion)
    assert raw["headpointer"] == {"x_gain": -300.0}, "apply must not edit its input"
    for section, table in raw.items():  # nothing the user wrote is gone or changed
        for key, value in table.items():
            assert out[section][key] == value
    added = {
        (section, key)
        for section, table in out.items()
        for key in table
        if key not in raw.get(section, {})
    }
    reported = {(r.setting.section, r.setting.key) for r in expansion.resolved if r.source == "preset"}
    assert added == reported
    assert ("headpointer", "x_gain") not in added and ("gaze", "deixis") not in added


@pytest.mark.parametrize("roles", SUBSET_PARAMS)
def test_a_user_value_that_differs_from_the_preset_is_never_rewritten(roles: dict[str, bool]) -> None:
    """Flip every non-floor key the preset would set; none of them may change."""
    probe = preset.expand(_raw(roles))
    flipped: dict[str, dict] = {}
    for item in probe.resolved:
        s = item.setting
        if s.protected or not isinstance(s.value, bool):
            continue
        flipped.setdefault(s.section, {})[s.key] = not s.value
    raw = _raw(roles, **flipped)
    expansion = preset.expand(raw)
    assert expansion.refusal == ""
    out = preset.apply(raw, expansion)
    for section, table in flipped.items():
        for key, value in table.items():
            assert out[section][key] is value, (section, key)


# --------------------------------------------------------------------------- 4. a default install


def _dump(cfg: Config) -> dict:
    data = dataclasses.asdict(cfg)
    data.pop("handsfree")
    return data


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty-file"),
        pytest.param("[stt]\nmodel = 'tiny'\n", id="no-handsfree-table"),
        pytest.param("[handsfree]\nenabled = false\n", id="disabled"),
        pytest.param(
            "[handsfree]\nenabled = false\ngaze = true\npointer = true\nswitch = true\n", id="disabled-with-every-role"
        ),
        pytest.param("[handsfree]\n", id="table-without-the-key"),
    ],
)
def test_a_config_that_does_not_ask_for_the_preset_resolves_with_no_preset_key(text: str, tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    loaded = load_config_checked(path)
    assert loaded.problems == []
    baseline = dataclasses.replace(Config(), stt=loaded.config.stt)
    assert _dump(loaded.config) == _dump(baseline)
    for feature in ("headpointer", "gaze", "facegesture", "gesture", "perception", "handsfree_safety", "cmdsafety"):
        assert dataclasses.asdict(getattr(loaded.config, feature)) == dataclasses.asdict(getattr(Config(), feature))


def test_the_raw_file_is_returned_unchanged_when_the_preset_is_off_or_refused() -> None:
    off = {"stt": {"model": "tiny"}, "handsfree": {"enabled": False}}
    assert preset.resolve_raw(off)[0] == off
    refused = {"handsfree": {"enabled": True}, "cmdsafety": {"enabled": False}}
    out, expansion = preset.resolve_raw(refused)
    assert expansion.refusal and out == refused, "a refused preset applies nothing, not half of itself"


def test_a_default_config_object_has_the_preset_off_and_every_camera_feature_off() -> None:
    cfg = Config()
    assert cfg.handsfree.enabled is False
    for feature in ("headpointer", "gaze", "facegesture", "gesture", "perception"):
        assert getattr(cfg, feature).enabled is False, feature


# --------------------------------------------------------------------------- 3. reversibility


USER_FILE = """\
# my own notes about this machine
[stt]
model = "tiny"   # small is too slow here

[headpointer]
x_gain = -300.0
# I turned dwell off on purpose
dwell_enabled = false

[gaze]
confidence_min = 0.8
"""


@pytest.fixture
def rig(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"

    class Platform:
        name = "linux"

        def __init__(self):
            self.paths = types.SimpleNamespace(
                ipc_socket=str(tmp_path / "sock"), data_dir=str(tmp_path), config_file=config,
            )

        def ipc_client_factory(self, _path):
            class _Down:
                def call(self, *a, **k):
                    raise IpcUnreachableError("no daemon")

            return _Down()

    monkeypatch.setattr(cli, "get_platform", lambda: Platform())
    monkeypatch.setattr(cli, "_feature_deps_blocked", lambda _f: None)
    config.write_text(USER_FILE, encoding="utf-8")
    return config


def _handsfree_free(text: str) -> str:
    """The file with the ``[handsfree]`` table and nothing else taken out."""
    out, skipping = [], False
    for line in text.splitlines():
        if line.strip() == "[handsfree]":
            skipping = True
            continue
        if skipping and line.startswith("["):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def test_disable_after_enable_gives_back_the_users_file_and_the_users_resolved_config(rig) -> None:
    config = rig
    before_text = config.read_text(encoding="utf-8")
    before = load_config_checked(config).config

    enabled = runner.invoke(app, ["handsfree", "enable", "--force", "--no-install"])
    assert enabled.exit_code == 0, enabled.output
    on = load_config_checked(config).config
    assert on.headpointer.enabled is True, "the preset really changed the resolved config"
    assert on.headpointer.dwell_enabled is False and on.headpointer.x_gain == -300.0, "yours still wins"
    assert on.stt.model == "tiny" and on.gaze.confidence_min == 0.8

    disabled = runner.invoke(app, ["handsfree", "disable"])
    assert disabled.exit_code == 0, disabled.output
    after_text = config.read_text(encoding="utf-8")
    assert _handsfree_free(after_text) == before_text, "only the [handsfree] table may differ"
    assert "# my own notes about this machine" in after_text and "# I turned dwell off on purpose" in after_text
    assert _dump(load_config_checked(config).config) == _dump(before)
    assert load_config_checked(config).config.handsfree.enabled is False


def test_enable_twice_and_disable_twice_change_nothing_more_than_once(rig) -> None:
    config = rig
    runner.invoke(app, ["handsfree", "enable", "--force", "--no-install"])
    once = config.read_text(encoding="utf-8")
    runner.invoke(app, ["handsfree", "enable", "--force", "--no-install"])
    assert config.read_text(encoding="utf-8") == once
    runner.invoke(app, ["handsfree", "disable"])
    off = config.read_text(encoding="utf-8")
    runner.invoke(app, ["handsfree", "disable"])
    assert config.read_text(encoding="utf-8") == off


def test_disable_keeps_a_role_choice_the_user_made(rig) -> None:
    config = rig
    config.write_text(USER_FILE + "\n[handsfree]\nenabled = true\nswitch = false\n", encoding="utf-8")
    runner.invoke(app, ["handsfree", "disable"])
    cfg = load_config_checked(config).config
    assert cfg.handsfree.enabled is False and cfg.handsfree.switch is False


# --------------------------------------------------------------------------- 5. degradation is stated


class _Camera:
    """A shared camera that has a lease and hands out whatever it was last shown."""

    def __init__(self) -> None:
        self.sample: PerceptionSample | None = None

    def consumer(self, name):
        camera = self

        class Lease:
            def start(self):
                pass

            def stop(self):
                pass

            def latest(self):
                return camera.sample

        return Lease()

    def show(self, t: float, yaw: float) -> None:
        self.sample = PerceptionSample(t, head_pose=HeadPoseSignal(t, yaw, 0.0, 0.0, 1.0))


def _preset_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[handsfree]\nenabled = true\n", encoding="utf-8")
    return load_config_checked(path).config


def _gate(cfg, clock):
    gate = gate_from_config(cfg, [SOURCE_NAME], clock=lambda: clock[0])
    assert gate is not None
    return gate


def _no_relative_motion() -> PointerCapabilities:
    return PointerCapabilities(backend="fake-absolute-only", relative_motion=False, absolute_motion=True)


@pytest.mark.parametrize(
    ("perception", "factory", "fragment"),
    [
        pytest.param(None, "sink", "no shared camera source", id="no-camera"),
        pytest.param("camera", None, "no pointer backend", id="platform-has-no-pointer-backend"),
        pytest.param("camera", "raises", "no pointer output", id="pointer-backend-refuses-to-open"),
        pytest.param("camera", "absolute-only", "cannot move the pointer relatively", id="pointer-cannot-move-relatively"),
    ],
)
def test_a_missing_camera_or_pointer_leaves_a_stated_reason_and_a_pointer_that_never_moved(
    tmp_path, perception, factory, fragment
) -> None:
    cfg = _preset_config(tmp_path)
    assert cfg.headpointer.enabled and cfg.handsfree_safety.enabled
    clock = [1000.0]
    gate = _gate(cfg, clock)
    sink = FakePointerSink(_no_relative_motion()) if factory == "absolute-only" else FakePointerSink()

    def raising():
        raise PermissionError("the portal dialog was declined")

    pointer_factory = {"sink": lambda: sink, "raises": raising, "absolute-only": lambda: sink, None: None}[factory]
    camera = _Camera() if perception == "camera" else None
    runtime = build_headpointer(
        cfg.headpointer, perception=camera, pointer_factory=pointer_factory, safety=gate,
        dwell_feedback_available=True, clock=lambda: clock[0] / 1000.0, thread=False,
    )
    assert runtime.active is False and runtime.runner is None
    assert fragment in runtime.reason, runtime.reason
    assert runtime.command("status") == {"ok": True, "active": False, "reason": runtime.reason}
    for action in ("resume", "recenter", "dwell"):  # a command to something not running says so, never "ok"
        answer = runtime.command(action, {"enabled": True})
        assert answer["ok"] is False and answer["reason"] == runtime.reason, action
    assert [a for a in sink.actions if a.kind is not PointerActionKind.CLOSE] == []
    # The failed backend, if it opened at all, was released rather than left open.
    if factory == "absolute-only":
        assert sink.actions[-1].kind is PointerActionKind.CLOSE


def test_with_no_signal_ever_the_gate_stays_paused_and_will_not_be_re_armed(tmp_path) -> None:
    """No camera: nothing ever samples the gate, so `resume` cannot declare hands-free ACTIVE."""
    cfg = _preset_config(tmp_path)
    clock = [1000.0]
    gate = _gate(cfg, clock)
    for _ in range(50):
        clock[0] += 33.0
        gate.poll()
    assert gate.status().state is SafetyState.PAUSED
    result = gate.resume()
    assert result.ok is False and result.reason
    assert gate.status().state is not SafetyState.ACTIVE


def test_without_the_overlay_the_head_still_moves_the_pointer_and_nothing_ever_clicks(tmp_path) -> None:
    """The preset leaves the overlay off (it is opt-in), and dwell only clicks while its ring is shown."""
    from yazses.core.daemon import should_launch_overlay

    cfg = _preset_config(tmp_path)
    assert cfg.headpointer.dwell_enabled is True, "the preset asks for dwell"
    assert cfg.overlay.enabled is False, "...and does not turn the overlay on to show it"
    feedback_available = should_launch_overlay(cfg, {}, platform="linux")
    assert feedback_available is False

    clock = [1000.0]
    gate, camera, sink = _gate(cfg, clock), _Camera(), FakePointerSink()
    runtime = build_headpointer(
        cfg.headpointer, perception=camera, pointer_factory=lambda: sink, safety=gate,
        dwell_feedback_available=feedback_available, clock=lambda: clock[0] / 1000.0, thread=False,
    )
    assert runtime.active and "overlay" in runtime.notice and "overlay" in runtime.dwell_refusal
    assert runtime.runner is not None
    runtime.runner.start()

    def tick(yaw: float) -> None:
        clock[0] += 33.0
        camera.show(clock[0] / 1000.0, yaw)
        gate.sample(SOURCE_NAME, at_ms=clock[0])
        assert runtime.runner is not None
        runtime.runner.pump()

    tick(0.0)
    assert gate.resume().ok
    tick(0.0)
    for _ in range(3):
        tick(0.2)
    assert any(a.kind is PointerActionKind.MOVE_RELATIVE for a in sink.actions), "the pointer does move"
    for _ in range(cfg.headpointer.dwell_ms // 33 * 4):  # four times the dwell time, held perfectly still
        tick(0.0)
    assert not [a for a in sink.actions if a.kind is PointerActionKind.BUTTON_PRESS]


@pytest.mark.parametrize("roles", SUBSET_PARAMS)
def test_no_subset_of_the_preset_turns_on_the_overlay_or_a_second_pointer_source(roles: dict[str, bool]) -> None:
    """The preset's whole reach is the sections below; a new one must be a deliberate addition here."""
    sections = {r.setting.section for r in preset.expand(_raw(roles)).resolved}
    assert sections <= {
        "handsfree_safety", "cmdsafety", "perception", "gaze", "headpointer", "facegesture", "gesture",
    }
    for r in preset.expand(_raw(roles)).resolved:
        if r.setting.section == "headpointer" and r.setting.key == "dwell_enabled":
            assert roles["pointer"] and roles["dwell"], "dwell is only asked for with the pointer it commits for"


# --------------------------------------------------------------------------- 6. explain echoes nothing of yours


SECRET_PHRASE = "my-bank-pin-is-4417-zq"
SECRET_PATH = "C:/Users/someone-private/Documents/voice.toml"


def test_explain_describes_a_value_you_wrote_without_printing_it() -> None:
    raw = {
        "handsfree": {"enabled": True},
        "handsfree_safety": {"stop_phrase": SECRET_PHRASE},
        "gesture": {"chords": {"nod+shake": SECRET_PATH}},
        "gaze": {"route_dictation": SECRET_PATH},
        "headpointer": {"x_gain": -312.5, "dwell_enabled": False},
    }
    expansion = preset.expand(raw)
    text = "\n".join(preset.render(expansion, enabled_in_file=True))
    for secret in (SECRET_PHRASE, SECRET_PATH, "someone-private", "4417"):
        assert secret not in text
    assert f"<your text, {len(SECRET_PHRASE)} characters>" in text
    assert "<your table, 1 entries>" in text
    assert "[headpointer] dwell_enabled = false" in text, "a boolean setting is a setting, not a secret"
    assert "[headpointer] x_gain" not in text, "a key the preset does not set is not echoed at all"
    assert "YOURS" in text


def test_a_value_equal_to_the_presets_prints_because_it_is_public() -> None:
    raw = {"handsfree": {"enabled": True}, "handsfree_safety": {"stop_phrase": preset.DEFAULT_STOP_PHRASE}}
    text = "\n".join(preset.render(preset.expand(raw), enabled_in_file=True))
    assert f'stop_phrase = "{preset.DEFAULT_STOP_PHRASE}"' in text and "yours (same as preset)" in text


def test_a_refusal_names_the_key_and_not_the_odd_value_you_put_in_it() -> None:
    raw = {"handsfree": {"enabled": True}, "cmdsafety": {"enabled": SECRET_PHRASE}}
    expansion = preset.expand(raw)
    assert "[cmdsafety] enabled" in expansion.refusal and SECRET_PHRASE not in expansion.refusal
    assert "\n".join(preset.render(expansion, enabled_in_file=True)).count(SECRET_PHRASE) == 0


def test_the_explain_command_prints_nothing_from_the_users_file(rig) -> None:
    config = rig
    config.write_text(
        f'[handsfree_safety]\nstop_phrase = "{SECRET_PHRASE}"\n[gaze]\nroute_dictation = "{SECRET_PATH}"\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["handsfree", "explain"])
    assert result.exit_code == 0, result.output
    assert SECRET_PHRASE not in result.output and "someone-private" not in result.output
    assert str(config) not in result.output and str(config.parent) not in result.output
    assert "YOURS" in result.output
