"""The Wayland injection path: keysym mapping, backend selection, portal client.

The portal itself is not reachable in CI -- no session bus, no compositor, no
consent dialog -- so the D-Bus layer is driven through a fake session that
*records* what was notified. That is the part worth asserting anyway: the bug
this path exists to prevent is typing the wrong characters, not failing to
connect.
"""

from __future__ import annotations

import pytest

from yazses.inject import auto, portal
from yazses.inject.keysyms import char_to_keysym, is_modifier, name_to_keysym, parse_combo

# ---------------------------------------------------------------- keysyms


@pytest.mark.parametrize(
    ("char", "expected"),
    [
        ("a", 0x61),
        ("A", 0x41),
        (" ", 0x20),
        ("~", 0x7E),
        ("é", 0xE9),  # Latin-1: the codepoint IS the keysym, no prefix.
        ("ÿ", 0xFF),  # last legacy codepoint before the prefix range
        ("€", 0x0100_20AC),  # beyond Latin-1: prefixed
        ("م", 0x0100_0645),
        ("→", 0x0100_2192),
    ],
)
def test_char_keysyms_span_every_range(char: str, expected: int) -> None:
    assert char_to_keysym(char) == expected


def test_control_characters_become_named_keys() -> None:
    """A dictated newline must press Return, not emit codepoint 0x0A.

    0x0A is not a keysym any compositor acts on, so mapping it arithmetically
    would make "new line" silently do nothing.
    """
    assert char_to_keysym("\n") == 0xFF0D
    assert char_to_keysym("\r") == 0xFF0D
    assert char_to_keysym("\t") == 0xFF09


def test_latin1_boundary_is_not_prefixed() -> None:
    """0xFF is legacy, 0x100 is not -- the off-by-one that breaks accented text."""
    assert char_to_keysym("ÿ") == 0x00FF
    assert char_to_keysym("Ā") == 0x0100_0100


def test_char_to_keysym_rejects_non_single_characters() -> None:
    with pytest.raises(ValueError):
        char_to_keysym("ab")


def test_name_to_keysym_is_case_insensitive_for_names() -> None:
    assert name_to_keysym("Return") == name_to_keysym("return") == 0xFF0D
    assert name_to_keysym("BackSpace") == 0xFF08
    assert name_to_keysym("F5") == 0xFFC2


def test_name_to_keysym_preserves_case_for_single_characters() -> None:
    """"A" must not be lowercased into "a" by the table lookup."""
    assert name_to_keysym("A") == 0x41
    assert name_to_keysym("a") == 0x61


def test_name_to_keysym_returns_none_rather_than_raising() -> None:
    """An unknown key degrades to "do nothing" -- it runs on a daemon thread."""
    assert name_to_keysym("NoSuchKey") is None
    assert name_to_keysym("") is None


def test_is_modifier() -> None:
    assert is_modifier("ctrl") and is_modifier("Shift") and is_modifier("super")
    assert not is_modifier("Left") and not is_modifier("a")


def test_parse_combo_splits_modifiers_from_the_key() -> None:
    mods, key = parse_combo("ctrl+shift+Left")
    assert mods == [0xFFE3, 0xFFE1]
    assert key == 0xFF51


def test_parse_combo_rejects_an_unknown_final_key() -> None:
    """Dropping the key silently presses nothing; that must be visible, not quiet."""
    assert parse_combo("ctrl+Nonsense") is None
    assert parse_combo("") is None


def test_parse_combo_drops_an_unknown_modifier_but_keeps_the_key() -> None:
    mods, key = parse_combo("hyper+a")
    assert mods == []
    assert key == 0x61


# ---------------------------------------------------------------- injector


class FakeSession:
    """Records (keysym, state) instead of talking to D-Bus."""

    def __init__(self) -> None:
        self.events: list[tuple[int, int]] = []
        self.started = 0
        self.closed = 0

    def ensure_started(self) -> None:
        self.started += 1

    def notify_keysym(self, keysym: int, state: int) -> None:
        self.events.append((keysym, state))

    def tap(self, keysym: int, delay: float) -> None:
        self.notify_keysym(keysym, portal.KEY_PRESSED)
        self.notify_keysym(keysym, portal.KEY_RELEASED)

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def fake_injector() -> tuple[portal.PortalInjector, FakeSession]:
    session = FakeSession()
    return portal.PortalInjector(session=session), session


def test_inject_presses_and_releases_every_character(fake_injector) -> None:
    injector, session = fake_injector
    injector.inject("Hi")
    assert session.events == [
        (0x48, 1),
        (0x48, 0),
        (0x69, 1),
        (0x69, 0),
    ]


def test_inject_handles_non_ascii(fake_injector) -> None:
    injector, session = fake_injector
    injector.inject("é€")
    assert [k for k, state in session.events if state == 1] == [0xE9, 0x0100_20AC]


def test_empty_inject_never_opens_a_session(fake_injector) -> None:
    """The hot path must not negotiate a portal session for a discarded burst."""
    injector, session = fake_injector
    injector.inject("")
    assert session.started == 0
    assert session.events == []


def test_inject_backspaces_emits_exactly_count_taps(fake_injector) -> None:
    injector, session = fake_injector
    injector.inject_backspaces(3)
    assert session.events.count((0xFF08, 1)) == 3
    assert session.events.count((0xFF08, 0)) == 3


def test_inject_backspaces_ignores_non_positive(fake_injector) -> None:
    injector, session = fake_injector
    injector.inject_backspaces(0)
    injector.inject_backspaces(-2)
    assert session.events == []


def test_key_sequence_wraps_the_key_in_its_modifiers(fake_injector) -> None:
    """Modifiers must be held across the key and released in reverse order."""
    injector, session = fake_injector
    injector.inject_key_sequence(["ctrl+shift+Left"])
    assert session.events == [
        (0xFFE3, 1),  # ctrl down
        (0xFFE1, 1),  # shift down
        (0xFF51, 1),  # Left down
        (0xFF51, 0),  # Left up
        (0xFFE1, 0),  # shift up   -- reverse order
        (0xFFE3, 0),  # ctrl up
    ]


def test_key_sequence_skips_an_unrecognised_combo_without_raising(fake_injector) -> None:
    injector, session = fake_injector
    injector.inject_key_sequence(["Nonsense", "Return"])
    assert session.events == [(0xFF0D, 1), (0xFF0D, 0)]


def test_portal_injector_satisfies_the_injector_protocol() -> None:
    from yazses.inject.base import BaseInjector

    assert isinstance(portal.PortalInjector(session=FakeSession()), BaseInjector)


def test_backend_name_is_reported_not_the_class(fake_injector) -> None:
    injector, _ = fake_injector
    assert auto.describe_injector(injector) == "portal"


# ---------------------------------------------------------------- token


def test_token_round_trips_through_the_sandboxed_data_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))
    assert portal.read_token() == ""
    portal.write_token("restore-me")
    assert portal.token_path() == tmp_path / portal.TOKEN_FILENAME
    assert portal.read_token() == "restore-me"


def test_token_file_is_owner_only(tmp_path, monkeypatch) -> None:
    """The token authorises silent input injection; it is not world-readable."""
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))
    portal.write_token("secret")
    assert (portal.token_path().stat().st_mode & 0o777) == 0o600


def test_writing_an_empty_token_is_a_no_op(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path))
    portal.write_token("")
    assert not portal.token_path().exists()


def test_read_token_never_raises_on_an_unreadable_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YAZSES_DATA_DIR", str(tmp_path / "does" / "not" / "exist"))
    assert portal.read_token() == ""


# ---------------------------------------------------------------- key delay


def test_key_delay_defaults_and_honours_the_override(monkeypatch) -> None:
    monkeypatch.delenv("YAZSES_PORTAL_KEY_DELAY", raising=False)
    assert portal.key_delay() == portal.DEFAULT_KEY_DELAY_S
    monkeypatch.setenv("YAZSES_PORTAL_KEY_DELAY", "0.02")
    assert portal.key_delay() == 0.02
    monkeypatch.setenv("YAZSES_PORTAL_KEY_DELAY", "0")
    assert portal.key_delay() == 0.0


@pytest.mark.parametrize("bad", ["", "   ", "abc", "-1"])
def test_key_delay_falls_back_on_nonsense(monkeypatch, bad: str) -> None:
    monkeypatch.setenv("YAZSES_PORTAL_KEY_DELAY", bad)
    assert portal.key_delay() == portal.DEFAULT_KEY_DELAY_S


# ---------------------------------------------------------------- selection


@pytest.fixture
def wayland(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("YAZSES_INJECTOR", raising=False)
    return monkeypatch


def test_wayland_prefers_ydotool_over_the_portal(wayland) -> None:
    """An unconfined install that already works must not gain a consent dialog."""
    wayland.setattr(auto, "ydotool_ready", lambda: True)
    wayland.setattr(auto, "portal_available", lambda: True)
    assert auto.describe_injector(auto.get_injector("auto")) != "portal"


def test_wayland_uses_the_portal_when_ydotool_is_absent(wayland) -> None:
    """This is the snap: no ydotoold can run inside strict confinement."""
    wayland.setattr(auto, "ydotool_ready", lambda: False)
    wayland.setattr(auto, "portal_available", lambda: True)
    assert auto.describe_injector(auto.get_injector("auto")) == "portal"


def test_the_portal_is_preferred_over_wtype(wayland) -> None:
    """wtype needs virtual-keyboard-manager-v1, which GNOME and KDE refuse."""
    wayland.setattr(auto, "ydotool_ready", lambda: False)
    wayland.setattr(auto, "portal_available", lambda: True)
    wayland.setattr(auto.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert auto.describe_injector(auto.get_injector("auto")) == "portal"


def test_wayland_falls_back_to_wtype_when_the_portal_is_missing(wayland) -> None:
    wayland.setattr(auto, "ydotool_ready", lambda: False)
    wayland.setattr(auto, "portal_available", lambda: False)
    wayland.setattr(auto.shutil, "which", lambda name: "/usr/bin/wtype" if name == "wtype" else None)
    assert "Wtype" in auto.describe_injector(auto.get_injector("auto"))


def test_x11_is_untouched_by_the_portal(monkeypatch) -> None:
    """The portal must never displace xdotool on an X11 session."""
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("YAZSES_INJECTOR", raising=False)
    monkeypatch.setattr(auto, "portal_available", lambda: True)
    monkeypatch.setattr(auto.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert "Xdotool" in auto.describe_injector(auto.get_injector("auto"))


def test_portal_can_be_forced_on_any_session(monkeypatch) -> None:
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert auto.describe_injector(auto.get_injector("portal")) == "portal"


def test_portal_available_is_false_without_a_display(monkeypatch) -> None:
    """The probe must not open a bus connection on a headless box."""
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    assert portal.portal_available() is False
