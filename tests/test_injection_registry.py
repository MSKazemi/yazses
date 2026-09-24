"""The backend table is the single source of truth, and consent is a gate in it.

Two classes of defect this pins:

1. **Drift.** The ladder used to exist in five hand-maintained copies, and they
   disagreed: `[injection] backend = "ydotool"` was documented in `config.py` and
   honoured by `get_injector`, but missing from the validator's enum, so the loader
   answered "is not one of ..." and silently replaced the user's choice with `auto`.
   Deriving the enum from the table makes that unrepresentable.

2. **Taking the portal on someone's behalf.** It makes the desktop show a
   screen-sharing indicator for as long as the session is open. `auto` must never
   select it unasked — but every install that already agreed has to keep working
   with no migration and no new prompt.

Every case builds its own `Env`, so nothing here reads the host.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from yazses.inject import registry as reg


def _env(**kw):
    kw.setdefault("which", lambda name: f"/usr/bin/{name}")
    return reg.Env(**kw)


@pytest.fixture
def only(monkeypatch):
    """Force exactly which backends probe as available.

    Rebuilds the table with `dataclasses.replace` rather than assigning to a field:
    `InjectionBackend` is frozen, which is the point — a row nobody can mutate at
    runtime is a row that still says at read time what it said at import time.
    """
    def _apply(*names, undetermined=(), real=()):
        def _probe(value):
            return lambda env: reg.Capability(
                available=value,
                reason="" if value else "probe stub says no",
            )

        table = tuple(
            backend
            if backend.name in real  # keep the genuine probe for what is under test
            else replace(
                backend,
                probe=_probe(None if backend.name in undetermined else backend.name in names),
            )
            for backend in reg.BACKENDS
        )
        monkeypatch.setattr(reg, "BACKENDS", table)
        return table

    return _apply


# ------------------------------------------------------------ the derived enum


def test_every_backend_is_configurable():
    """A backend that exists but cannot be named is the `ydotool` bug."""
    values = reg.config_values()
    for backend in reg.BACKENDS:
        for value in backend.config_values:
            assert value in values


def test_the_validator_accepts_every_registry_value():
    from yazses.config import InjectionConfig
    from yazses.configcheck import build_section, enum_values

    legal = enum_values("injection", "backend") or ()
    for value in reg.config_values():
        assert value in legal, f"{value} is in the table but not the enum"
        problems: list = []
        cfg = build_section(InjectionConfig, {"backend": value}, "injection", problems)
        assert cfg.backend == value, f"{value} was rejected: {problems}"


def test_every_value_resolves_back_to_its_backend():
    for value in reg.config_values():
        assert reg.by_value(value) is not None


def test_an_unknown_value_resolves_to_nothing():
    assert reg.by_value("telepathy") is None


# ------------------------------------------------------------------- the ladder


def test_wayland_prefers_ydotool(only):
    only("ydotool", "portal", "wtype")
    assert reg.select(_env(session="wayland")).chosen.name == "ydotool"


def test_x11_uses_xdotool(only):
    only("xdotool")
    assert reg.select(_env(session="x11")).chosen.name == "xdotool"


def test_the_floor_is_always_reachable(only):
    """`select` must be total: something is always returned."""
    only()  # nothing available at all
    assert reg.select(_env(session="wayland")).chosen.name == "clipboard"


def test_a_backend_from_another_session_is_never_chosen(only):
    only("xdotool")
    chosen = reg.select(_env(session="wayland")).chosen
    assert chosen.name != "xdotool"


# ------------------------------------------------------------------- consent


def test_the_portal_is_skipped_without_consent(only):
    only("portal")
    selection = reg.select(_env(session="wayland"))
    assert selection.chosen.name == "clipboard"
    assert [e.backend.name for e in selection.needs_consent] == ["portal"]


def test_consent_allow_selects_the_portal(only):
    only("portal")
    assert reg.select(_env(session="wayland", consent="allow")).chosen.name == "portal"


def test_a_prior_token_is_consent(only):
    """Grandfathering: anyone who already answered the dialog keeps working."""
    only("portal")
    env = _env(session="wayland", prior_consent=frozenset({"portal"}))
    assert reg.select(env).chosen.name == "portal"


def test_naming_the_portal_is_consent(only):
    only("portal")
    assert reg.select(_env(session="wayland", requested="portal")).chosen.name == "portal"


def test_a_strict_snap_gets_the_portal_unasked(only):
    """It cannot apt-install ydotoold or ship a udev rule — the portal is its only
    way to type on Wayland, and a dialog with one possible answer is not a choice."""
    only("portal")
    env = _env(session="wayland", confinement="strict")
    assert reg.select(env).chosen.name == "portal"


def test_deny_beats_a_prior_token(only):
    """An explicit no outranks inferred consent, or the setting does nothing."""
    only("portal")
    env = _env(
        session="wayland", consent="deny", prior_consent=frozenset({"portal"})
    )
    assert reg.select(env).chosen.name != "portal"


def test_an_explicit_deny_is_obeyed_even_in_a_snap(only):
    """The snap's implied consent covers "never asked", not "asked and said no".

    Tempting to override it — denying the portal in a confined snap leaves it with
    no way to type on Wayland at all. But quietly doing the thing a user explicitly
    forbade, on the grounds that we know better, is the same paternalism as taking
    the portal unasked in the first place. Obey, and let `doctor` say plainly what
    the consequence is.
    """
    only("portal")
    env = _env(session="wayland", consent="deny", confinement="strict")
    assert reg.select(env).chosen.name == "clipboard"


def test_wtype_is_unavailable_where_the_compositor_refuses_it(only):
    """Installed is not able-to-type.

    Mutter and KWin deliberately do not implement `virtual-keyboard-manager-v1`, so
    wtype exits cleanly having typed nothing. Ranking it below the portal was enough
    only while the portal was taken automatically; once the portal waits for consent,
    an unconsented GNOME user falls straight onto it — a backend that silently drops
    every burst, which is strictly worse than the clipboard.
    """
    only(real=("wtype",))
    env = _env(session="wayland", desktop="ubuntu:gnome")
    selection = reg.select(env)
    assert selection.chosen.name == "clipboard"
    wtype = selection.evaluation("wtype")
    assert wtype is not None and wtype.eligibility is reg.Eligibility.UNAVAILABLE


def test_wtype_is_available_on_a_wlroots_compositor(only):
    only(real=("wtype",))
    env = _env(session="wayland", desktop="sway")
    assert reg.select(env).chosen.name == "wtype"


def test_an_unconsented_gnome_user_still_gets_their_words(only):
    """The whole point of 'offer, don't take': refusing the portal must not mean
    refusing to type."""
    only("portal", real=("wtype",))
    env = _env(session="wayland", desktop="gnome")
    assert reg.select(env).chosen.name == "clipboard"


# -------------------------------------------------------------------- forcing


def test_naming_a_backend_from_another_session_falls_through(only):
    """`backend = "wtype"` on X11 has always yielded xdotool; it must keep doing so."""
    only("xdotool", "wtype")
    chosen = reg.select(_env(session="x11", requested="wtype")).chosen
    assert chosen.name == "xdotool"


def test_clipboard_can_be_named_anywhere(only):
    only()
    for session in ("wayland", "x11", "headless"):
        assert reg.select(_env(session=session, requested="clipboard")).chosen.name == "clipboard"


def test_an_alias_resolves_to_its_backend(only):
    only("ydotool")
    assert reg.select(_env(session="wayland", requested="type")).chosen.name == "ydotool"


# ------------------------------------------------------------------ reporting


def test_every_considered_backend_carries_a_reason(only):
    """Doctor, status and the GUI all render this; a blank reason is a blank line."""
    only("portal")
    selection = reg.select(_env(session="wayland"))
    for item in selection.considered:
        assert item.eligibility is not None
        if item.eligibility is reg.Eligibility.UNAVAILABLE:
            assert item.capability.reason or item.capability.remedy


def test_an_undetermined_probe_is_not_a_finding(only):
    """`None` means "could not tell" — it must never be rendered as a failure, the
    rule `system/snap.py` already follows."""
    only(undetermined=("portal",))
    selection = reg.select(_env(session="wayland"))
    item = selection.evaluation("portal")
    assert item is not None
    assert item.eligibility is reg.Eligibility.UNKNOWN
    assert selection.needs_consent == ()


def test_building_the_chosen_backend_works():
    """The factory strings must actually resolve — a typo there is only found here."""
    for backend in reg.BACKENDS:
        module_name, _, class_name = backend.factory.partition(":")
        module = __import__(module_name, fromlist=[class_name])
        assert hasattr(module, class_name), f"{backend.name}: {backend.factory} is wrong"
