"""The overlay must be able to stop moving.

The default overlay expands rings outward from near the pointer, sixty times a
second, for as long as you speak. Every desktop already carries a setting where a
motion-sensitive user has said they do not want that, and YazSes read none of them
— while `docs/assets/extra.css` has honoured `prefers-reduced-motion` on the
marketing site for months. The site respected the preference; the accessibility
product did not.

These tests pin the two halves that are easy to get wrong: that the reduced form
genuinely does not move, and that it still says what the overlay exists to say.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from yazses.config import OverlayConfig
from yazses.overlay import motion
from yazses.overlay.animation import SonarModel
from yazses.overlay.app import compute_frame
from yazses.overlay.envelope import EnvelopeFollower
from yazses.overlay.poller import StatusSnapshot

SCREEN = (0, 0, 1920, 1080)
LOUD = StatusSnapshot(state="recording", audio_level=0.4, vad_threshold=0.01)


def _runtime():
    return EnvelopeFollower(), SonarModel()


def _frames(reduced: bool, times: list[float]):
    env, model = _runtime()
    return [
        compute_frame(
            LOUD, OverlayConfig(), env, model,
            now=t, cursor=(500, 400), screen=SCREEN, reduced_motion=reduced,
        )
        for t in times
    ], model


# --------------------------------------------------------------------------
# resolve_reduced_motion
# --------------------------------------------------------------------------

def test_an_explicit_setting_overrides_the_desktop_in_both_directions():
    """The probe cannot read every desktop, so the user must be able to be believed."""
    for os_pref in (True, False, None):
        assert motion.resolve_reduced_motion("on", os_pref) is True
        assert motion.resolve_reduced_motion("off", os_pref) is False


def test_auto_follows_the_desktop():
    assert motion.resolve_reduced_motion("auto", True) is True
    assert motion.resolve_reduced_motion("auto", False) is False


def test_an_unreadable_desktop_keeps_the_behaviour_the_overlay_already_had():
    """`None` is "cannot tell", and it must not silently restyle everyone's overlay.

    Most desktops are not GNOME, macOS or Windows-with-a-readable-flag, so erring
    toward reduced here would change the look for the majority on the strength of
    a failed probe.
    """
    assert motion.resolve_reduced_motion("auto", None) is False


def test_a_typo_degrades_to_auto_rather_than_to_a_silent_choice(caplog):
    """Config loading is total (#52), so a bad value reaches here rather than raising."""
    assert motion.resolve_reduced_motion("reduced", True) is True
    assert motion.resolve_reduced_motion("REDUCED", False) is False
    assert any("reduced_motion" in r.getMessage() for r in caplog.records), (
        "a misspelt setting was accepted in silence"
    )


def test_case_and_whitespace_do_not_defeat_the_setting():
    assert motion.resolve_reduced_motion("  ON  ", None) is True
    assert motion.resolve_reduced_motion("Off", True) is False


# --------------------------------------------------------------------------
# steady_ripples — motion removed, information kept
# --------------------------------------------------------------------------

def test_a_silent_microphone_still_shows_a_ring_while_recording():
    """Otherwise reduced motion deletes the answer to "am I recording?".

    The animated form draws nothing during silence, which is tolerable only
    because rings are about to appear. Here none ever will.
    """
    (ripple,) = motion.steady_ripples(0.0)
    assert ripple.alpha == motion.MIN_ALPHA
    assert ripple.alpha > 0


def test_brightness_still_tracks_the_voice():
    quiet = motion.steady_ripples(0.1)[0].alpha
    loud = motion.steady_ripples(1.0)[0].alpha
    assert loud > quiet, "the ring stopped answering 'how loudly'"


def test_brightness_is_banded_so_the_ring_cannot_shimmer():
    """A level recomputed per frame from a live mic flickers, and flicker at 60 Hz
    is its own accessibility problem rather than a fix for one. Two intensities in
    the same band must be pixel-identical."""
    assert motion.steady_ripples(0.50)[0].alpha == motion.steady_ripples(0.51)[0].alpha
    distinct = {motion.steady_ripples(i / 100)[0].alpha for i in range(101)}
    assert len(distinct) <= motion.ALPHA_STEPS + 1, (
        f"{len(distinct)} distinct brightnesses across the range -- the banding is not "
        "quantising, so the ring will flicker with microphone noise"
    )


def test_intensity_is_clamped():
    assert motion.steady_ripples(-5.0)[0].alpha == motion.MIN_ALPHA
    assert motion.steady_ripples(99.0)[0].alpha == 1.0


# --------------------------------------------------------------------------
# compute_frame — the property that matters
# --------------------------------------------------------------------------

def test_the_reduced_ring_does_not_travel():
    frames, model = _frames(True, [0.0, 0.2, 0.5, 0.9, 1.3])
    radii = {f.ripples[0].radius_frac for f in frames}
    assert radii == {motion.STEADY_RADIUS_FRAC}, f"the ring moved: {sorted(radii)}"
    assert all(len(f.ripples) == 1 for f in frames), "more than one ring was drawn"
    assert model.active_count == 0, "the sonar model was advanced despite reduced motion"


def test_the_animated_ring_does_travel():
    """Red-green for the test above: it must be capable of observing movement.

    Asserting "the radius never changes" passes just as well against a frame
    pipeline that emits nothing at all.
    """
    frames, model = _frames(False, [0.0, 0.2, 0.5, 0.9, 1.3])
    radii = {r.radius_frac for f in frames for r in f.ripples}
    assert len(radii) > 1, "the animated overlay did not move either -- the test is blind"
    assert model.active_count > 0


def test_the_centre_glow_stops_breathing_too():
    """The ring is not the only thing that moves, and this was missed at first.

    `SonarWidget._paint` sizes a centre glow as `half * (0.10 + 0.10 * intensity)`
    from `Frame.intensity`. Banding only the ring left the rings still while the
    core grew and shrank with the raw microphone level sixty times a second —
    the same class of motion in a smaller place, and invisible to a test that
    only looked at `ripples`.
    """
    seen = set()
    for level in [i / 200 for i in range(0, 101)]:
        env, model = _runtime()  # fresh: the envelope has attack state of its own
        frame = compute_frame(
            StatusSnapshot(state="recording", audio_level=level, vad_threshold=0.01),
            OverlayConfig(), env, model,
            now=0.0, cursor=(500, 400), screen=SCREEN, reduced_motion=True,
        )
        seen.add(frame.intensity)
        assert frame.intensity == motion.band(frame.intensity), (
            f"Frame.intensity {frame.intensity} is not a band, so the widget's glow "
            "radius is driven by the raw live level"
        )
    assert len(seen) <= motion.ALPHA_STEPS + 1, (
        f"the glow took {len(seen)} distinct sizes across the level range: {sorted(seen)}"
    )


def test_the_animated_glow_is_not_banded():
    """Red-green for the test above, which would pass on a frame pipeline that
    banded *everything* — including the normal one, where continuous is correct."""
    raw = set()
    for level in [i / 200 for i in range(0, 101)]:
        env, model = _runtime()
        frame = compute_frame(
            StatusSnapshot(state="recording", audio_level=level, vad_threshold=0.01),
            OverlayConfig(), env, model,
            now=0.0, cursor=(500, 400), screen=SCREEN,
        )
        raw.add(frame.intensity)
    assert len(raw) > motion.ALPHA_STEPS + 1, (
        "the default overlay is banded too -- the reduced-motion test proves nothing"
    )


def test_releasing_the_key_hides_the_reduced_overlay():
    """The steady ring must not outlive the recording it reports."""
    env, model = _runtime()
    frame = compute_frame(
        StatusSnapshot(state="idle"), OverlayConfig(), env, model,
        now=2.0, cursor=(500, 400), screen=SCREEN, reduced_motion=True,
    )
    assert frame.visible is False
    assert frame.ripples == []


def test_reduced_motion_is_off_by_default_for_callers_that_do_not_pass_it():
    """Every existing call site keeps its behaviour; this is opt-in at the seam."""
    frames, _ = _frames(False, [0.0, 0.6])
    env, model = _runtime()
    default = compute_frame(
        LOUD, OverlayConfig(), env, model,
        now=0.0, cursor=(500, 400), screen=SCREEN,
    )
    assert default.ripples[0].radius_frac == frames[0].ripples[0].radius_frac


# --------------------------------------------------------------------------
# detection — best effort, never fatal
# --------------------------------------------------------------------------

def test_a_missing_settings_command_is_unknown_not_false(monkeypatch):
    """`None` and `False` mean different things and the difference is the whole
    reason `auto` can be overridden."""
    def _boom(*a, **k):
        raise FileNotFoundError("gsettings")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert motion._linux_prefers_reduced() is None


def test_a_hung_settings_daemon_does_not_delay_the_overlay(monkeypatch):
    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="gsettings", timeout=1.0)

    monkeypatch.setattr(subprocess, "run", _timeout)
    assert motion._linux_prefers_reduced() is None


def test_gnome_saying_animations_are_off_reads_as_reduced(monkeypatch):
    class _Out:
        returncode = 0
        stdout = "false\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Out())
    assert motion._linux_prefers_reduced() is True

    _Out.stdout = "true\n"
    assert motion._linux_prefers_reduced() is False


def test_detect_never_raises(monkeypatch):
    """It runs while the overlay is starting; an indicator that fails to appear
    because a settings key could not be read is worse than the bug this fixes."""
    def _boom(*a, **k):
        raise RuntimeError("desktop on fire")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert motion.detect_os_preference() in (True, False, None)


def test_the_windows_flag_and_its_polarity_are_pinned(monkeypatch):
    """The Windows path cannot be exercised here, so pin what it depends on.

    A wrong `SPI_GETCLIENTAREAANIMATION` fails silently in the worst way: the call
    errors, the probe returns "cannot tell", and that is indistinguishable from a
    desktop with no such setting — so reduced motion would simply never engage on
    Windows and nothing would look broken. The value and the polarity are from the
    Win32 `SystemParametersInfoW` reference: `pvParam` receives TRUE when animations
    are ENABLED, so this module's answer is the inverse.
    """
    assert motion._SPI_GETCLIENTAREAANIMATION == 0x1042

    calls = []

    class _User32:
        def SystemParametersInfoW(self, action, uiParam, pvParam, fWinIni):  # noqa: N802
            calls.append(action)
            pvParam._obj.value = _User32.animations_enabled
            return 1

    class _Windll:
        user32 = _User32()

    import ctypes

    monkeypatch.setattr(ctypes, "windll", _Windll(), raising=False)

    _User32.animations_enabled = 1  # Windows: animations ON
    assert motion._windows_prefers_reduced() is False
    _User32.animations_enabled = 0  # Windows: animations OFF
    assert motion._windows_prefers_reduced() is True
    assert calls == [0x1042, 0x1042], "the probe asked for a different system parameter"


class _FakeWorkspace:
    reduce = False

    @classmethod
    def sharedWorkspace(cls):  # noqa: N802 - ObjC selector name
        return cls()

    def accessibilityDisplayShouldReduceMotion(self):  # noqa: N802 - ObjC selector name
        return _FakeWorkspace.reduce


def _install_appkit(monkeypatch, workspace):
    import sys
    import types

    module = types.ModuleType("AppKit")
    module.NSWorkspace = workspace
    monkeypatch.setitem(sys.modules, "AppKit", module)


def test_macos_prefers_the_supported_api_over_the_undocumented_key(monkeypatch):
    """`accessibilityDisplayShouldReduceMotion` is published; the defaults key is not.

    `com.apple.universalaccess reduceMotion` is an undocumented preference: absent
    until the user has toggled the setting once, and free to be renamed. pyobjc is a
    hard dependency on darwin, so there is no reason to guess when we can ask.

    Not inverted, unlike the Windows flag: true means reduce.
    """
    called = []
    monkeypatch.setattr(motion, "_run", lambda argv: called.append(argv) or "1")
    _install_appkit(monkeypatch, _FakeWorkspace)

    _FakeWorkspace.reduce = True
    assert motion._macos_prefers_reduced() is True
    _FakeWorkspace.reduce = False
    assert motion._macos_prefers_reduced() is False
    assert not called, "shelled out to `defaults` while the supported API was available"


def test_macos_falls_back_when_appkit_is_unavailable(monkeypatch):
    """A stripped install must not lose the capability entirely.

    The absence has to be *made*, not assumed. The first version of this test simply
    did not install a fake AppKit and trusted that none existed — true on the Linux
    machine it was written on, false on the macOS runners, where the import succeeds
    and the real `NSWorkspace` answers. It passed locally and turned both macOS jobs
    red: a test that read the host rather than the code.

    Setting `sys.modules["AppKit"] = None` makes `import AppKit` raise `ImportError`
    whatever the platform, so this exercises the fallback everywhere. It is asserted
    below that the block beats a *working* AppKit, which is what makes the test
    meaningful on a machine that has one.
    """
    import sys

    _install_appkit(monkeypatch, _FakeWorkspace)  # a working one, to be overridden
    monkeypatch.setitem(sys.modules, "AppKit", None)

    monkeypatch.setattr(motion, "_run", lambda argv: "1")
    assert motion._macos_prefers_reduced() is True, (
        "AppKit was still reachable — the fallback was never exercised"
    )

    monkeypatch.setattr(motion, "_run", lambda argv: None)
    assert motion._macos_prefers_reduced() is None


def test_macos_falls_back_when_the_selector_raises(monkeypatch):
    """An AppKit that imports but cannot answer is not a reason to give up."""

    class _Broken:
        @classmethod
        def sharedWorkspace(cls):  # noqa: N802
            raise RuntimeError("no window server")

    _install_appkit(monkeypatch, _Broken)
    monkeypatch.setattr(motion, "_run", lambda argv: "0")
    assert motion._macos_prefers_reduced() is False


# --------------------------------------------------------------------------
# Linux: the portal is tried before GNOME's own key
# --------------------------------------------------------------------------

_PORTAL_ON = "({'enable-animations': <true>, 'color-scheme': <uint32 1>},)"
_PORTAL_OFF = "({'enable-animations': <false>},)"


def _fake_run(monkeypatch, answers):
    """Route `_run` by the command being invoked; record what was asked."""
    asked = []

    def _run(argv):
        asked.append(argv[0])
        return answers.get(argv[0])

    monkeypatch.setattr(motion, "_run", _run)
    return asked


def test_the_portal_answers_and_gsettings_is_not_consulted(monkeypatch):
    """The portal is the route that works beyond GNOME *and* inside a snap.

    A confined process reading `gsettings` may be answering about the sandbox
    rather than the user's session, so this order is not a preference — under
    confinement it is the difference between right and about-the-wrong-machine.
    """
    asked = _fake_run(monkeypatch, {"gdbus": _PORTAL_OFF, "gsettings": "true"})
    assert motion._linux_prefers_reduced() is True
    assert asked == ["gdbus"], f"fell through to {asked[1:]} despite a portal answer"

    asked = _fake_run(monkeypatch, {"gdbus": _PORTAL_ON, "gsettings": "false"})
    assert motion._linux_prefers_reduced() is False
    assert asked == ["gdbus"]


def test_no_portal_falls_back_to_gsettings(monkeypatch):
    asked = _fake_run(monkeypatch, {"gdbus": None, "gsettings": "false"})
    assert motion._linux_prefers_reduced() is True
    assert asked == ["gdbus", "gsettings"]


def test_a_portal_without_the_key_is_not_an_answer(monkeypatch):
    """A backend can answer ReadAll and carry no animation key. That is "cannot
    tell", and it must fall through rather than be read as "animations on"."""
    asked = _fake_run(monkeypatch, {"gdbus": "({'color-scheme': <uint32 1>},)",
                                    "gsettings": "false"})
    assert motion._linux_prefers_reduced() is True
    assert asked == ["gdbus", "gsettings"]


def test_neither_route_answers_is_unknown_not_false(monkeypatch):
    _fake_run(monkeypatch, {"gdbus": None, "gsettings": None})
    assert motion._linux_prefers_reduced() is None


@pytest.mark.skipif(sys.platform != "darwin", reason="needs a real AppKit")
def test_the_real_nsworkspace_selector_works_on_macos(monkeypatch):
    """The one thing the fakes above cannot check: that the selector is real.

    Every other macOS test here injects a fake workspace, so all of them would pass
    just as happily against a misspelt selector or a wrong call shape — and
    `_macos_prefers_reduced` swallows the exception and falls through to `defaults`,
    so a broken AppKit path fails *silently* and forever. The machine that wrote it
    has no AppKit; the macOS runners do, and that asymmetry is the whole point of
    running this there.

    `_run` is made fatal so a fall-through cannot be mistaken for success: this
    passes only if the answer genuinely came from AppKit.
    """
    def _must_not_shell_out(argv):
        raise AssertionError(
            f"fell back to {argv!r} — the NSWorkspace path raised on a machine that "
            "has AppKit, so the selector or the call shape is wrong"
        )

    monkeypatch.setattr(motion, "_run", _must_not_shell_out)
    assert motion._macos_prefers_reduced() in (True, False)
