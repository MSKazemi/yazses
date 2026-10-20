"""Install a switched-on feature's libraries at the moment it turns out to need them.

`system/dormant.py` finds every enabled capability whose libraries are missing — a
hand-edited ``config.toml``, ``--no-install``, a failed install whose key stood, an
upgrade that rebuilt the environment without them. Until now the answer to all of
those was a sentence: "Install them with: yazses features enable …". The owner's
complaint was exactly that: a feature should bring its own requirements, in a later
phase, when it is needed — not leave the user to find a terminal and type.

So each surface that discovers dormancy now *offers* the install as one action:

* the daemon's start-up toast carries an **Install now** button
  (:func:`toast_actions`, :func:`handle_action`);
* ``yazses start`` / ``restart`` in a terminal ask once, before starting
  (:func:`prompt_text`);
* ``yazses features install`` does all of them, or the ones named.

What does **not** change is consent. Nothing here installs on its own: the toast
installs on a click, the prompt on a typed yes, the command because it was typed
(AGENTS.md rule 1, ADR-019 — the download is the user's action). A feature this
environment can never supply (a snap, a frozen bundle, the system Python) gets no
button, only the reason, because a button that cannot work is worse than none.

Pure orchestration over injected callables, so every path tests without a network,
a notifier or a daemon.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Sequence

log = logging.getLogger(__name__)

INSTALL = "install"
LATER = "later"

#: One install at a time per process. Two toasts clicked in quick succession would
#: otherwise run two installers into one environment at once.
_busy = threading.Lock()


def installable(items: Iterable) -> list:
    """The dormant features this environment can actually install."""
    return [d for d in items if getattr(d, "installable", True)]


def _size_note(item) -> str:
    try:
        from yazses.system.depsize import download_note

        return download_note(item.slug, list(item.missing))
    except Exception:  # noqa: BLE001 - a size is a courtesy, never a failure
        return ""


def toast_body(item) -> str:
    """The start-up toast: what is wrong, what fixing it costs, and that it asks first."""
    body = item.describe()
    note = _size_note(item)
    if note and getattr(item, "installable", True):
        body += f"\nInstall now: {note}."
    return body


def toast_actions(item):
    """The toast's buttons, or ``None`` when no install can work here."""
    if not getattr(item, "installable", True):
        return None
    from yazses.system.notify import NotifyAction

    return [NotifyAction(INSTALL, "Install now"), NotifyAction(LATER, "Not now")]


def install_one(
    item,
    *,
    install: Callable[..., bool] | None = None,
    echo: Callable[[str], None] = log.info,
) -> bool:
    """Install *item*'s packages and prove its modules now import. True on success."""
    run = install
    if run is None:
        from yazses.system.deps import install_feature

        run = install_feature
    return bool(run(tuple(item.packages), check_modules=tuple(item.missing), echo=echo))


def result_message(item, ok: bool) -> tuple[str, str]:
    """``(title, body)`` for the toast that follows a clicked install."""
    if ok:
        return (
            f"{item.name} is installed",
            "Restart YazSes to switch it on: tray → Restart daemon, or `yazses restart`.",
        )
    retry = getattr(item, "command", "") or f"yazses features enable {item.slug}"
    return (
        f"{item.name} could not be installed",
        "It stays switched on but dormant. The daemon log says why, and whether "
        "anything the install had changed was undone.\n"
        f"Retry from a terminal:  {retry}",
    )


def handle_action(
    key: str,
    item,
    *,
    install: Callable[..., bool] | None = None,
    notify: Callable[[str, str], None] | None = None,
) -> bool | None:
    """Run a clicked toast button. ``None`` when nothing was installed.

    Runs on the notifier's own background thread, so the install blocks only the
    toast that asked for it. A second click while one install is running is
    refused with a toast rather than queued: the first one may be the fix.
    """
    if key != INSTALL:
        return None
    say = notify or _notify
    if not _busy.acquire(blocking=False):
        say("An install is already running", "Wait for it to finish, then try again.")
        return None
    try:
        log.info("Installing the libraries for %s (asked from the toast).", item.slug)
        ok = install_one(item, install=install)
    except Exception:  # noqa: BLE001 - a toast handler must never take the daemon down
        log.exception("on-demand install of %s raised", item.slug)
        ok = False
    finally:
        _busy.release()
    say(*result_message(item, ok))
    return ok


def _notify(title: str, body: str) -> None:
    from yazses.system import notify as notify_mod

    urgency, expire_ms = notify_mod.toast_policy(False)
    notify_mod.notify(title, body, urgency=urgency, expire_ms=expire_ms)


def prompt_text(items: Sequence) -> str:
    """What `yazses start`/`restart` print before asking. Empty when nothing to ask."""
    can = installable(items)
    if not can:
        return ""
    lines = ["These features are switched on but cannot run — their libraries are missing:"]
    for item in can:
        note = _size_note(item)
        lines.append(
            f"  {item.name} [{item.slug}]: {', '.join(item.packages)}"
            + (f"  ({note})" if note else "")
        )
    return "\n".join(lines)


def install_all(
    items: Sequence,
    *,
    install: Callable[..., bool] | None = None,
    echo: Callable[[str], None] = print,
) -> list[str]:
    """Install every item in turn; the slugs that failed. Each is attempted.

    A failure does not stop the rest: the camera features share mediapipe, so one
    failure usually means all, but a partial run still leaves what it can working.
    """
    failed: list[str] = []
    for item in items:
        echo(f"\n{item.name} [{item.slug}]")
        if not install_one(item, install=install, echo=echo):
            failed.append(item.slug)
    return failed
