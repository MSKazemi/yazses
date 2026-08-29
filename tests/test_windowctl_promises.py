"""`windowctl` must not advertise verbs nothing can carry out.

For a long time the feature described itself as *"Hands-free desktop layout:
'move window left half', 'maximize', 'workspace 3'"* — and every one of those
three examples was dead. Their grammar is `windowctl/commands.py::parse_wm_command`,
which nothing in `src/` imports, and the `WindowBackend` protocol
(`windowctl/focus.py`) declares only `list_windows()` and `focus()`. There is no
method that could execute a `WmAction` even after someone wired the parser up.

So `yazses features enable windowctl` succeeded, `yazses features` listed it as
available, and the three things it named did nothing. That is worse than not
shipping the feature: a toggle that reports success teaches people the product is
broken in some way they cannot see.

The registry now describes focusing only, which is what runs. This pins that pair
together: **the description may name a layout verb only when the backend has grown
a method that performs it.** Restoring the promise then means restoring the
capability, in the same change.

## The guard had a blind spot, and the promise survived in it

The first version of this file scanned `feat.name` and `feat.why`. A feature's
`example` and `use_case` live in two *other* dicts in `features.py`, far from the
`_Def`, and were never in scope — so the correction landed on `why` and the banned
verbs stayed in the two lines `yazses features info` prints directly underneath it:

    Say 'focus the browser' ... Rearranging windows by voice is designed but
    not connected yet. Off by default.
    Use when:  When you want to arrange windows and switch workspaces ...
    Example:   Say 'move window left half' or 'workspace 3' ...

One screen, contradicting itself: "not connected yet", then two lines telling you to
say the things that are not connected. Every field the user is shown is now scanned.

## And the toggle was read by nothing

Separately: `[windowctl] enabled` was never consulted. `core/daemon.py` called
`_try_window_focus` unconditionally in command mode, so voice focus ran whether or not
the feature was on — `features disable windowctl` was a no-op, and "Off by default" was
false, against a house rule that new features ship off. `_build_window_backend` now
returns None when the feature is off, which routes a disabled feature down the already
tested Wayland path: the phrase is dictated as text instead of consumed.
"""
from __future__ import annotations

import re
from pathlib import Path

from yazses.config import Config
from yazses.system.features import grouped_features
from yazses.windowctl.focus import WindowBackend

#: Words that promise moving, sizing or workspace-switching — none of which the
#: backend protocol can do. Focusing and raising are fine: those work.
LAYOUT_VERBS = ("move window", "maximize", "maximise", "workspace", "tile", "snap to")

#: The backend method that executes a layout action, plus the names this list
#: guessed at before one existed. `perform` is the real one: `WindowBackend.perform`
#: takes a whole `WmAction` rather than exposing one method per verb, so the grammar
#: can grow a kind without every backend growing a method it would only raise from.
#:
#: The rest are kept because a future backend may well split them out, and a guard
#: that only accepts today's spelling fails the next correct implementation.
LAYOUT_METHODS = (
    "perform",
    "move", "resize", "maximize", "maximise", "tile", "workspace", "set_geometry",
)


def _windowctl_entry():
    for _category, _blurb, feats in grouped_features(Config()):
        for feat in feats:
            if feat.slug == "windowctl":
                return feat
    raise AssertionError("the windowctl feature is no longer in the registry")


def _backend_methods() -> set[str]:
    return {name for name in dir(WindowBackend) if not name.startswith("_")}


def test_the_feature_exists_and_this_guard_is_looking_at_it() -> None:
    """Guard the guard: a renamed slug would make every assertion below vacuous."""
    feat = _windowctl_entry()
    assert feat.name and feat.why


def _all_user_visible_text(feat) -> str:
    """Every string `yazses features` / `features info` / docs/features.md print.

    Scanning only name+why is how the banned verbs survived: `example` and `use_case`
    are separate dicts in features.py and were out of scope.
    """
    return " ".join(
        str(t) for t in (feat.name, feat.note, feat.why, feat.example, feat.use_case) if t
    ).lower()


def test_every_user_visible_field_is_in_scope() -> None:
    """Guard the guard, second layer: a new display field must be added above.

    Without this, `features info` can grow a line that no assertion here reads —
    which is exactly the failure this file already had once.
    """
    feat = _windowctl_entry()
    shown = {"name", "note", "why", "example", "use_case"}
    fields = set(feat.__dataclass_fields__)
    unscanned = {f for f in fields if f in {"name", "note", "why", "example", "use_case"}}
    assert unscanned == shown, (
        f"a user-visible field was renamed or removed: {sorted(fields)} — update "
        f"_all_user_visible_text so the promise check still covers what is printed"
    )
    for field in shown:
        value = getattr(feat, field)
        if value:
            assert str(value).lower() in _all_user_visible_text(feat)


def test_no_layout_verb_is_promised_without_a_backend_that_can_do_it() -> None:
    feat = _windowctl_entry()
    text = _all_user_visible_text(feat)
    promised = [verb for verb in LAYOUT_VERBS if verb in text]
    if not promised:
        return

    methods = _backend_methods()
    capable = [m for m in LAYOUT_METHODS if m in methods]
    assert capable, (
        f"windowctl advertises {promised} but WindowBackend only offers "
        f"{sorted(methods)} — there is no method that could carry any of them out, "
        f"so enabling the feature would succeed and the examples would do nothing. "
        f"Either add the backend capability, or stop promising it."
    )


def test_the_description_still_promises_what_does_work() -> None:
    """The opposite failure: trimming it until it describes nothing. Focusing by
    name is wired (core/daemon.py imports parse_focus_command) and should be said."""
    feat = _windowctl_entry()
    text = _all_user_visible_text(feat)
    assert "focus" in text or "switch to" in text


def test_the_wayland_limitation_is_stated() -> None:
    """The backend is X11-only; a Wayland user enabling this needs to know before
    they conclude the product is broken."""
    feat = _windowctl_entry()
    assert re.search(r"x11|wayland", f"{feat.name} {feat.why}", re.I)


def test_the_layout_grammar_is_still_present_for_whoever_wires_it() -> None:
    """The parser is good code with tests; this is a wiring gap, not a deletion.
    If someone removes it, that should be a deliberate choice rather than a
    side effect of tidying up after this guard."""
    from yazses.windowctl.commands import parse_wm_command

    assert parse_wm_command("move window left half") is not None


def test_the_daemon_honours_the_toggle() -> None:
    """`features disable windowctl` was a no-op: nothing read `[windowctl] enabled`.

    Voice focus ran in command mode for every user, including the ones who never
    enabled it, against both the catalogue's own "Off by default" and the project rule
    that new features ship off.

    Asserted on the real method rather than on a grep, so moving the check elsewhere
    is fine as long as a disabled feature still produces no backend.
    """
    from yazses.core.daemon import Daemon

    cfg = Config()
    assert cfg.windowctl.enabled is False, "the default changed — re-read ADR-011"

    build = Daemon._build_window_backend
    assert build(object(), cfg) is None, (
        "windowctl is disabled but a window backend was built — voice focus will run "
        "for a user who never enabled it"
    )


def test_the_gate_is_not_simply_always_off() -> None:
    """The opposite failure: a gate that never opens would pass the test above.

    Enabled, the backend build must at least be *attempted* — it still legitimately
    returns None off X11 and without xdotool, so this asserts the attempt, not the
    result.
    """
    from unittest.mock import patch

    from yazses.core.daemon import Daemon

    cfg = Config()
    cfg.windowctl.enabled = True
    with patch("yazses.windowctl.focus.build_window_backend", return_value="BACKEND") as m:
        got = Daemon._build_window_backend(object(), cfg)
    assert m.called, "the feature is enabled and the backend was never even built"
    assert got == "BACKEND"


def test_doctor_does_not_claim_a_disabled_feature_works() -> None:
    """The half-fix this pass nearly shipped.

    Gating the daemon on `[windowctl] enabled` made `yazses doctor` wrong in the same
    breath: it reported

        [OK] Voice window focus: xdotool (X11) — "focus the browser" works

    from the presence of xdotool alone. That was true only while voice focus ran
    unconditionally. Doctor is exactly where someone looks after it did not work, so a
    confident OK there is worse than no line at all.
    """
    from yazses.system.doctor import _window_focus_check

    cfg = Config()
    assert cfg.windowctl.enabled is False
    name, status, detail = _window_focus_check(False, True, cfg)
    assert status != "OK", f"doctor says {detail!r} for a disabled feature"
    assert "features enable windowctl" in detail, (
        "a user told the feature is off needs the command that turns it on"
    )


def test_doctor_still_confirms_it_when_the_feature_is_on() -> None:
    """The opposite failure: a check that never says OK proves nothing."""
    import shutil

    from yazses.system.doctor import _window_focus_check

    if not shutil.which("xdotool"):
        import pytest

        pytest.skip("xdotool absent — the OK branch is unreachable on this host")
    cfg = Config()
    cfg.windowctl.enabled = True
    _name, status, _detail = _window_focus_check(False, True, cfg)
    assert status == "OK"


def test_wayland_is_reported_before_the_toggle() -> None:
    """Order matters: enabling the feature on Wayland would not help.

    Sending someone to run a command that cannot work on their session is worse than
    telling them the platform said no.
    """
    from yazses.system.doctor import _window_focus_check

    cfg = Config()
    for enabled in (False, True):
        cfg.windowctl.enabled = enabled
        _name, status, detail = _window_focus_check(True, False, cfg)
        assert status == "SKIP"
        assert "wayland" in detail.lower()
        assert "features enable" not in detail


def test_the_shipped_backend_really_implements_the_executor() -> None:
    """A method on the Protocol and nothing behind it is the same defect, moved.

    `test_no_layout_verb_is_promised_without_a_backend_that_can_do_it` reads
    `dir(WindowBackend)`, and a Protocol will happily declare a method whose body is
    a docstring. That would let the description promise "maximize" again while the
    only concrete backend still cannot do it — the original bug with an extra step.
    So check the class that actually ships, and check it is not inheriting the
    Protocol's empty stub.
    """
    from yazses.windowctl.focus import XdotoolWindows

    implemented = [m for m in LAYOUT_METHODS if callable(getattr(XdotoolWindows, m, None))]
    assert implemented, (
        f"XdotoolWindows implements none of {LAYOUT_METHODS} — the protocol may "
        f"declare a layout method but nothing carries it out."
    )
    for name in implemented:
        method = getattr(XdotoolWindows, name)
        assert method.__qualname__.startswith("XdotoolWindows"), (
            f"XdotoolWindows.{name} is inherited, not implemented here"
        )


def test_the_executor_is_reachable_from_the_daemon() -> None:
    """The grammar existed for a release with no caller. Pin the caller too.

    This is the specific shape of #164: a designed, tested, documented capability
    whose only defect was that nothing invoked it. A guard on the description alone
    would pass on a parser nothing calls.
    """
    daemon = (
        Path(__file__).resolve().parent.parent
        / "src" / "yazses" / "core" / "daemon.py"
    ).read_text(encoding="utf-8")
    assert "parse_wm_command" in daemon, (
        "core/daemon.py no longer imports parse_wm_command — the layout grammar is "
        "back to being parsed by nobody, which is what this feature shipped as."
    )
    assert "_try_window_action" in daemon
