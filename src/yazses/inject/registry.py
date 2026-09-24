"""Every injection backend, its order, and what it costs — in one place.

The knowledge of *which backends exist, whether each can run here, why not, how to
fix it, and what it costs the user* used to live in five hand-maintained copies:
`inject/auto.get_injector` (the real ladder), a mirrored copy in
`system/doctor._injection_readiness`, loose probes (`ydotool_ready`,
`portal_available`, `runtime_availability`), the `configcheck` enum of legal values,
and the Settings combo built from that enum.

They drifted, exactly as this project's own memory predicts they will: the enum
omitted `ydotool` while `config.py` documented it and `get_injector` honoured it, so
the loader answered *"is not one of ..."* and silently replaced a user's documented
choice with `auto`. `doctor`'s docstring already warned that "a doctor that reports a
different backend from the one the daemon will choose is worse than no doctor" — a
warning is not a mechanism.

This module is the mechanism. Everything downstream *renders* `select()`; nothing
else derives a ladder. Adding a backend, or a platform, is one row.

Design rules:

* **Pure and injectable.** `Env` is a snapshot the caller builds; every probe takes
  it. That is what lets the whole ladder be tested on a machine with no Wayland, no
  snap and no session — which is every machine this is developed on.
* **Three-valued availability**, following `system/snap.py`: `None` means *could not
  determine*, and an unrun probe must never become a finding.
* **Nothing heavy at import.** Factories are dotted strings; probes import their
  backend lazily. Importing this module must not pull in jeepney or evdev.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


def _which(name: str) -> str | None:
    """`shutil.which`, looked up at call time so patching the module works."""
    return shutil.which(name)


# --------------------------------------------------------------------- consent


class Consent(str, Enum):
    """Whether choosing this backend needs the user to have said yes."""

    #: Selected freely by `auto` when available.
    NONE = "none"
    #: Never selected by `auto` without explicit consent. The portal is the only
    #: member: it makes the desktop display a screen-sharing indicator for as long
    #: as the session is open, which is not something to take on a user's behalf in
    #: an application whose whole promise is that nothing leaves the machine.
    EXPLICIT = "explicit"


class Eligibility(str, Enum):
    """Why a backend was or was not chosen. Rendered by doctor, status and the GUI."""

    CHOSEN = "chosen"
    UNAVAILABLE = "unavailable"
    WRONG_SESSION = "wrong-session"
    NEEDS_CONSENT = "needs-consent"
    NOT_AUTO = "not-auto"
    UNKNOWN = "unknown"


# ------------------------------------------------------------------ data shapes


@dataclass(frozen=True)
class Capability:
    """Whether a backend can run here, and what would fix it if not.

    A sibling of `system/backends.BackendStatus` rather than a fork — that one
    answers "is the *adapter and its Python deps* present", this one answers "can it
    run in *this session*". Probes that need the former call it and wrap the result.
    """

    available: bool | None
    reason: str = ""
    remedy: str = ""

    @property
    def determined(self) -> bool:
        return self.available is not None


@dataclass(frozen=True)
class Env:
    """A snapshot of everything selection depends on. Built by the caller, never here."""

    session: str = "headless"            # "wayland" | "x11" | "headless"
    #: Lowercased XDG_CURRENT_DESKTOP. Only wtype cares, and it cares a lot: GNOME's
    #: Mutter and KDE's KWin deliberately do not implement the protocol it needs.
    desktop: str = ""
    confinement: str = "none"            # "none" | "strict"
    requested: str = "auto"
    consent: str = "ask"                 # "ask" | "allow" | "deny"
    #: Backends the user has already consented to by other evidence — a portal
    #: restore token on disk, or having named the backend explicitly. Carrying it as
    #: data is what grandfathers every existing install with no migration step.
    prior_consent: frozenset[str] = field(default_factory=frozenset)
    #: Resolved through `_which` rather than bound to `shutil.which` directly: a
    #: default captured at class-definition time keeps pointing at the original
    #: function object, so a test that patches `shutil.which` patches everything
    #: except this — and the probe then reads the developer's real machine while the
    #: test believes it is describing an empty one.
    which: Callable[[str], str | None] = field(default=lambda name: _which(name))

    @classmethod
    def detect(cls, requested: str = "auto", *, consent: str = "ask") -> Env:
        """Build from the live process. The only impure thing in this module."""
        from yazses.system.snap import in_strict_snap

        session = "headless"
        if os.environ.get("WAYLAND_DISPLAY"):
            session = "wayland"
        elif os.environ.get("DISPLAY"):
            session = "x11"

        prior: set[str] = set()
        try:
            from yazses.inject.portal import read_token

            if read_token():
                prior.add("portal")
        except Exception:  # noqa: BLE001 — absent optional dep is "no evidence"
            pass

        return cls(
            session=session,
            desktop=(os.environ.get("XDG_CURRENT_DESKTOP", "") or "").lower(),
            confinement="strict" if in_strict_snap() else "none",
            requested=(requested or "auto").strip().lower(),
            consent=(consent or "ask").strip().lower(),
            prior_consent=frozenset(prior),
        )


@dataclass(frozen=True)
class InjectionBackend:
    """One way of getting characters into the focused window."""

    name: str
    label: str
    factory: str                                   # "module:ClassName", imported lazily
    probe: Callable[[Env], Capability]
    rank: int                                      # lower wins within a session
    sessions: frozenset[str]
    aliases: tuple[str, ...] = ()
    consent: Consent = Consent.NONE
    #: Confinements under which consent is implied. A strictly confined snap cannot
    #: apt-install ydotoold or ship a udev rule, so the portal is its *only* way to
    #: type on Wayland — expressing that as data keeps it out of the selection code.
    consent_implied_by_confinement: tuple[str, ...] = ()
    #: False for backends that must be asked for by name (never reached by `auto`).
    auto_selectable: bool = True
    #: Forcing this backend still requires its probe to pass. True only for wtype,
    #: preserving long-standing behaviour: a forced wtype on a machine without it
    #: falls through rather than yielding an injector that cannot type.
    force_requires_probe: bool = False
    #: Naming this backend works in any session. True for the three that are not a
    #: property of the display server: `clipboard` and `unicode` go through other
    #: mechanisms entirely, and a forced `portal` has always been honoured on X11
    #: too. The session-bound ones (ydotool, wtype, xdotool) fall through to the
    #: ladder when named in the wrong session -- `backend = "wtype"` on X11 has
    #: always yielded xdotool, and must keep doing so.
    force_ignores_session: bool = False
    terminal_safe: bool = True
    clobbers_clipboard: bool = False
    cost: str = ""

    @property
    def config_values(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class Evaluation:
    backend: InjectionBackend
    eligibility: Eligibility
    capability: Capability


@dataclass(frozen=True)
class Selection:
    chosen: InjectionBackend
    considered: tuple[Evaluation, ...]

    def evaluation(self, name: str) -> Evaluation | None:
        for item in self.considered:
            if item.backend.name == name:
                return item
        return None

    @property
    def needs_consent(self) -> tuple[Evaluation, ...]:
        """Backends that would have been chosen but for a missing consent.

        This is what makes "fall back to clipboard *and surface the choice*" a
        rendering of data the selector already produced, rather than a branch every
        consumer re-invents and one of them forgets.
        """
        return tuple(
            e for e in self.considered if e.eligibility is Eligibility.NEEDS_CONSENT
        )


# ---------------------------------------------------------------------- probes


def _probe_ydotool(env: Env) -> Capability:
    # Through the `auto` module's names rather than the underlying helpers: those
    # are the long-established seams the suite patches, and routing probes through
    # them keeps one patch point instead of two that can disagree.
    from yazses.inject import auto

    if not env.which("ydotool"):
        return Capability(
            available=False,
            reason="the `ydotool` client is not installed",
            remedy="Run `yazses setup`, then log out and back in.",
        )
    if not auto.ydotool_ready():
        return Capability(
            available=False,
            reason="ydotoold is not running (no socket)",
            # Both halves matter and both need a new session: the `ydotoold`
            # package, and the udev rule without which it cannot open /dev/uinput.
            remedy="Run `yazses setup`, then log out and back in.",
        )
    return Capability(available=True)
    from yazses.inject.auto import find_ydotool_socket

    path = find_ydotool_socket()
    if path is None:
        return True
    try:
        if os.stat(path).st_uid != os.geteuid():
            return True  # someone else's daemon; its device access is its business
    except OSError:  # pragma: no cover
        return True
    try:
        return os.access("/dev/uinput", os.W_OK)
    except OSError:  # pragma: no cover
        return True


def _probe_portal(env: Env) -> Capability:
    try:
        from yazses.inject import auto
    except Exception:  # noqa: BLE001 - no jeepney in this build
        return Capability(available=None, reason="the portal client could not be loaded")
    if not auto.portal_available():
        return Capability(
            available=False,
            reason="no xdg-desktop-portal RemoteDesktop on this session bus",
        )
    return Capability(available=True)


#: Compositors that refuse `virtual-keyboard-manager-v1`, the protocol wtype needs.
_WTYPE_HOSTILE = ("gnome", "kde", "plasma")


def _probe_wtype(env: Env) -> Capability:
    if not env.which("wtype"):
        return Capability(available=False, reason="`wtype` is not installed")
    if any(name in env.desktop for name in _WTYPE_HOSTILE):
        # Unavailable, not merely last. Being installed is not being able to type:
        # Mutter and KWin deliberately do not implement
        # `virtual-keyboard-manager-v1`, so wtype exits cleanly having done nothing.
        # Ranking it below the portal was enough only while the portal was taken
        # automatically; now that the portal waits for consent, an unconsented GNOME
        # user would fall straight onto a backend that silently types nothing --
        # strictly worse than the clipboard, which at least delivers the words.
        return Capability(
            available=False,
            reason=(
                f"{env.desktop.split(':')[-1] or 'this desktop'} does not implement "
                "the virtual-keyboard protocol wtype needs"
            ),
        )
    return Capability(available=True)


def _probe_xdotool(env: Env) -> Capability:
    if not env.which("xdotool"):
        return Capability(
            available=False,
            reason="`xdotool` is not installed",
            remedy="Run `yazses setup`.",
        )
    return Capability(available=True)


def _probe_unicode(env: Env) -> Capability:
    try:
        from yazses.inject.unicode import runtime_availability
    except Exception:  # noqa: BLE001
        return Capability(available=None, reason="the unicode backend could not be loaded")
    try:
        problem = runtime_availability()
    except Exception:  # noqa: BLE001
        return Capability(available=None, reason="the unicode backend probe did not run")
    if problem:
        reason, remedy = problem
        return Capability(available=False, reason=reason, remedy=remedy)
    return Capability(available=True)


def _probe_clipboard(env: Env) -> Capability:
    # The floor of the ladder: it is always constructible, and on Wayland without
    # wl-copy it degrades inside the injector rather than being unselectable. A
    # backend that can always be built is what makes `select` total.
    return Capability(available=True)


# -------------------------------------------------------------------- the table

BACKENDS: tuple[InjectionBackend, ...] = (
    InjectionBackend(
        name="ydotool",
        aliases=("type",),
        label="Type (ydotool)",
        factory="yazses.inject.ydotool:YdotoolInjector",
        probe=_probe_ydotool,
        rank=10,
        sessions=frozenset({"wayland"}),
        cost="types into every app, terminals included; needs a one-time setup",
    ),
    InjectionBackend(
        name="portal",
        label="Desktop portal (RemoteDesktop)",
        factory="yazses.inject.portal:PortalInjector",
        probe=_probe_portal,
        rank=20,
        sessions=frozenset({"wayland"}),
        consent=Consent.EXPLICIT,
        consent_implied_by_confinement=("strict",),
        force_ignores_session=True,
        cost="asks once for permission and shows a screen-sharing indicator while active",
    ),
    InjectionBackend(
        name="wtype",
        label="wtype (wlroots only)",
        factory="yazses.inject.wtype:WtypeInjector",
        probe=_probe_wtype,
        rank=30,
        sessions=frozenset({"wayland"}),
        force_requires_probe=True,
        cost="a silent no-op on GNOME and KDE, which do not implement its protocol",
    ),
    InjectionBackend(
        name="xdotool",
        label="xdotool (X11)",
        factory="yazses.inject.xdotool:XdotoolInjector",
        probe=_probe_xdotool,
        rank=10,
        sessions=frozenset({"x11"}),
        cost="needs no permission and shows no indicator",
    ),
    InjectionBackend(
        name="unicode",
        label="Unicode (XKB/uinput)",
        factory="yazses.inject.unicode:UnicodeInjector",
        probe=_probe_unicode,
        rank=90,
        sessions=frozenset({"wayland", "x11", "headless"}),
        auto_selectable=False,
        force_ignores_session=True,
        cost="opt-in; for layouts the other backends cannot reach",
    ),
    InjectionBackend(
        name="clipboard",
        label="Clipboard paste (Ctrl+V)",
        factory="yazses.inject.clipboard:ClipboardInjector",
        probe=_probe_clipboard,
        rank=100,
        sessions=frozenset({"wayland", "x11", "headless"}),
        auto_selectable=False,
        force_ignores_session=True,
        terminal_safe=False,
        clobbers_clipboard=True,
        cost="instant, but a no-op in terminals and it overwrites your clipboard",
    ),
)

#: The last resort. Always constructible, so `select` never has to return None.
FALLBACK = "clipboard"


def by_value(value: str) -> InjectionBackend | None:
    """The backend a config value names, honouring aliases. None if unknown."""
    wanted = (value or "").strip().lower()
    for backend in BACKENDS:
        if wanted in backend.config_values:
            return backend
    return None


def config_values() -> tuple[str, ...]:
    """Every legal `[injection] backend` value except `auto`, in ladder order.

    The config validator and the Settings combo both derive from this, so a backend
    cannot exist and be un-configurable — the exact drift that silently reverted
    `backend = "ydotool"` to `auto`.
    """
    out: list[str] = []
    for backend in BACKENDS:
        for value in backend.config_values:
            if value not in out:
                out.append(value)
    return tuple(out)


# ------------------------------------------------------------------- selection


def has_consent(backend: InjectionBackend, env: Env) -> bool:
    """Whether *backend* may be selected by `auto` in this environment."""
    if backend.consent is Consent.NONE:
        return True
    if env.consent == "deny":
        return False
    if env.consent == "allow":
        return True
    if env.confinement in backend.consent_implied_by_confinement:
        return True
    # Naming it, or having answered its dialog before, is consent. This is what
    # keeps every existing install working with no migration and no new prompt.
    return backend.name in env.prior_consent or env.requested in backend.config_values


def select(env: Env) -> Selection:
    """Choose a backend and explain every one considered. Pure; never raises."""
    considered: list[Evaluation] = []

    forced = by_value(env.requested) if env.requested not in ("", "auto") else None
    if forced is not None and not forced.force_ignores_session:
        # Named in the wrong session: fall through to the ladder rather than build
        # something that cannot reach the display server.
        if env.session not in forced.sessions:
            forced = None
    if forced is not None:
        capability = forced.probe(env)
        if not forced.force_requires_probe or capability.available:
            return Selection(
                chosen=forced,
                considered=(Evaluation(forced, Eligibility.CHOSEN, capability),),
            )
        considered.append(Evaluation(forced, Eligibility.UNAVAILABLE, capability))

    for backend in sorted(BACKENDS, key=lambda b: b.rank):
        if forced is not None and backend.name == forced.name:
            continue
        if backend.name == FALLBACK:
            continue
        if env.session not in backend.sessions:
            considered.append(
                Evaluation(backend, Eligibility.WRONG_SESSION, Capability(available=None))
            )
            continue
        if not backend.auto_selectable:
            considered.append(
                Evaluation(backend, Eligibility.NOT_AUTO, Capability(available=None))
            )
            continue
        capability = backend.probe(env)
        if capability.available is None:
            considered.append(Evaluation(backend, Eligibility.UNKNOWN, capability))
            continue
        if not capability.available:
            considered.append(Evaluation(backend, Eligibility.UNAVAILABLE, capability))
            continue
        if not has_consent(backend, env):
            considered.append(Evaluation(backend, Eligibility.NEEDS_CONSENT, capability))
            continue
        considered.append(Evaluation(backend, Eligibility.CHOSEN, capability))
        return Selection(chosen=backend, considered=tuple(considered))

    fallback = by_value(FALLBACK)
    assert fallback is not None  # the table always carries it
    considered.append(
        Evaluation(fallback, Eligibility.CHOSEN, fallback.probe(env))
    )
    return Selection(chosen=fallback, considered=tuple(considered))


def build(backend: InjectionBackend):
    """Instantiate *backend*'s injector. Imports the module lazily."""
    module_name, _, class_name = backend.factory.partition(":")
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)()


__all__ = [
    "BACKENDS",
    "FALLBACK",
    "Capability",
    "Consent",
    "Eligibility",
    "Env",
    "Evaluation",
    "InjectionBackend",
    "Selection",
    "build",
    "by_value",
    "config_values",
    "has_consent",
    "select",
]
