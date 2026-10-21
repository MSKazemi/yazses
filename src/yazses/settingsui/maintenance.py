"""What the Settings window says and offers for updates and dormant features.

The owner's two asks were "push a button: it finds the update and updates", and "when a
feature is needed, install its requirements". The tray and the CLI already do both. The
Settings window did neither, so a GUI user who opened it was sent back to a terminal.

This module holds the *decisions* and the *wording*, with no Qt import:
:mod:`yazses.settingsui.maintenance_panel` owns the widgets and the threads. That is the
split the rest of ``settingsui/`` uses (``deps.py`` / ``worker.py``, ``restart.py``), and
it is what lets every branch below be tested without a display.

Nothing here updates or installs anything. The actual work is done by the functions the
tray and the CLI already call, and only those:

* the check: ``tray.updates.check_updates`` and ``installer_update.one_click_offer``;
* a one-click hand-off (the Windows channels, ADR-027):
  ``tray.updates.hand_off_outside_tray``;
* a pip-family upgrade: ``updater.run_upgrade_checked``, which keeps the enabled
  features' libraries through the upgrade and re-reads the version afterwards;
* a feature install: ``system.ondemand.install_one`` (the transactional
  ``deps.install_feature``), or ``packs.manage.install`` for an ADR-028 add-on in a
  frozen build.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

# ---- updates ----------------------------------------------------------------


class UpdateAction(Enum):
    """The one thing the update button does next."""

    NONE = "none"            # nothing a click can do (up to date, no network, a terminal)
    ONE_CLICK = "one-click"  # download, verify, hand off, quit (ADR-027)
    UPGRADE = "upgrade"      # run the install's own upgrade command, verified
    OPEN_PAGE = "open-page"  # the releases page: the installer there upgrades in place


@dataclass(frozen=True)
class UpdateView:
    """The status line under the button, and what the action button is."""

    text: str
    action: UpdateAction = UpdateAction.NONE
    label: str = ""


INSTALL_LABEL = "Install update…"
OPEN_PAGE_LABEL = "Open download page"
CHECK_LABEL = "Check for updates"


def idle_text(current: str) -> str:
    """The line before anything was checked. Says the version: the first thing asked."""
    return (
        f"Installed: YazSes {current}. Checking asks the place YazSes was installed "
        "from (PyPI, GitHub or the snap store) for its newest version."
    )


def checking_text(current: str) -> str:
    return f"Installed: YazSes {current}. Checking for updates…"


def _versions(status) -> str:
    latest = getattr(status, "latest", None)
    line = f"Installed: {status.current}"
    if latest:
        line += f"   Available: {latest}"
    method = getattr(status, "method", "")
    if method and method != "unknown":
        line += f"   (installed with {method})"
    return line


def _steps(steps: Iterable[str] | None) -> str:
    lines = [s for s in (steps or []) if s is not None]
    if not lines:
        return ""
    return "\n" + "\n".join(f"    {s}" if s else "" for s in lines)


def _after_headline(body: str) -> str:
    """``update_message`` leads with "YazSes X → Y"; the versions line already says it."""
    return body.split("\n", 1)[1].strip("\n") if "\n" in body else ""


def plan_update(status, offer) -> UpdateView:
    """Turn a finished check into what the window shows and offers.

    ``offer`` is ``installer_update.one_click_offer(status, launcher)``: ``None`` when
    one-click does not apply to this install at all, ``Offer(ok=False, reason)`` when it
    applies but cannot deliver now (an all-users install, a package feed that has not
    caught up), ``Offer(ok=True)`` when it can.
    """
    from yazses.system.updater import GITHUB_METHODS, MSIX_METHODS
    from yazses.tray.about import needs_terminal, update_message

    versions = _versions(status)
    if status.latest is None:
        _title, body = update_message(status)
        return UpdateView(f"{versions}\n{body}")
    if not status.available:
        return UpdateView(f"{versions}\nYou're on the latest version. ✓")

    if offer is not None:
        if offer.ok:
            return UpdateView(
                f"{versions}\nUpdate available. Install it from here: YazSes downloads "
                "and checks it, closes, updates in place and starts again by itself. "
                "Your settings and models are kept.",
                UpdateAction.ONE_CLICK,
                INSTALL_LABEL,
            )
        # It applies but cannot deliver now. The reason already ends in what to do; the
        # steps are the same ones `yazses update` prints in this case.
        return UpdateView(
            f"{versions}\n{offer.reason}" + _steps(getattr(status, "steps", None)),
            UpdateAction.OPEN_PAGE,
            OPEN_PAGE_LABEL,
        )

    if status.command and not needs_terminal(status):
        return UpdateView(
            f"{versions}\nUpdate available. Installing runs:  {' '.join(status.command)}",
            UpdateAction.UPGRADE,
            INSTALL_LABEL,
        )

    _title, body = update_message(status)
    detail = _after_headline(body)
    text = f"{versions}\nUpdate available." + (f"\n{detail}" if detail else "")
    if (
        not status.command
        and status.method in GITHUB_METHODS
        and status.method not in MSIX_METHODS
    ):
        # A macOS .app, or a Windows install with no one-click launcher: the download is
        # the update. MSIX is excluded on purpose -- the page carries no .msix, and its
        # .exe would install a second copy beside the package (tray.updates says so too).
        return UpdateView(text, UpdateAction.OPEN_PAGE, OPEN_PAGE_LABEL)
    # A snap (`sudo snap refresh` needs a terminal for the password), or an unknown
    # method: the command or the steps are the whole answer.
    return UpdateView(text)


def upgrade_confirmation(status) -> tuple[str, str]:
    """``(title, text)`` asked before a pip-family upgrade runs."""
    command = " ".join(status.command or [])
    return (
        "Install the YazSes update?",
        f"YazSes {status.current} → {status.latest}\n\nRun  {command}  now?\n\n"
        "The libraries of the features you have switched on are kept. The running "
        "daemon keeps the old version until it restarts; you will be asked.",
    )


def unapplied_note(count: int) -> str:
    """Appended to the one-click question when this window has staged changes.

    The window closes for the update, and anything staged and not applied is lost. Saying
    so before the click is cheaper than a second dialog after it.
    """
    if count <= 0:
        return ""
    noun = "change" if count == 1 else "changes"
    return (
        f"\n\nThis window has {count} staged {noun} you have not applied. "
        "It closes for the update, so apply them first or they are discarded."
    )


def describe_handoff(result) -> UpdateView:
    """After ``hand_off_outside_tray``: closing on success, the way forward otherwise."""
    if result.ok:
        return UpdateView(f"{result.message}\nThis window closes now.")
    return UpdateView(
        f"{result.title}: {result.message}" + _steps(getattr(result, "steps", None)),
        UpdateAction.OPEN_PAGE,
        OPEN_PAGE_LABEL,
    )


def describe_upgrade(outcome) -> tuple[str, bool]:
    """``(text, offer_restart)`` after ``run_upgrade_checked``.

    A restart is offered only when the version really moved: ``uv tool upgrade`` exits 0
    on a pinned install and changes nothing, and restarting into the same version is the
    loop ``upgrade_result_message`` was written to end.
    """
    from yazses.tray.about import upgrade_result_message

    _title, body = upgrade_result_message(outcome)
    if outcome.ok:
        body += " Reopen this window to see the new version here."
    return body, bool(outcome.ok)


def progress_line(message: str, fraction) -> str:
    """One progress report from the hand-off, as the status line shows it."""
    if isinstance(fraction, (int, float)) and 0 <= fraction <= 1:
        return f"{message} {round(fraction * 100)} %"
    return message


# ---- dormant features --------------------------------------------------------

PIP = "pip"
PACK = "pack"


@dataclass(frozen=True)
class FeatureInstallRow:
    """One switched-on feature whose libraries are missing, and what a click can do."""

    slug: str
    name: str
    route: str          # PIP, PACK, or "" when nothing can install it here
    size: str           # "downloads ~224 MB (13 packages)", or "" when unknown
    detail: str         # the line shown beside the button
    item: Any = None    # the DormantFeature (PIP) or the pack IndexEntry (PACK)
    short: str = ""     # "224 MB": the size the button itself carries

    @property
    def installable(self) -> bool:
        return bool(self.route)

    @property
    def button_label(self) -> str:
        return f"Install now ({self.short})" if self.short else "Install now"


def _price_sentence(size: str) -> str:
    return f" Install now: {size}." if size else ""


def install_rows(
    items: Sequence,
    *,
    size_note: Callable[[object], tuple[str, str]],
    pack_status: Callable[[str], Any] | None = None,
    pack_entry: Callable[[str], Any] | None = None,
) -> list[FeatureInstallRow]:
    """One row per dormant feature, routed to the install that can work here.

    ``items`` are ``system.dormant.DormantFeature``. ``size_note(item)`` answers
    ``(sentence, short)`` from the committed size table (``system.depsize``), both empty
    when the size is unknown. ``pack_status(slug)`` is set only in
    a frozen build whose pack runtime is supported (ADR-028): it answers that feature's
    ``packs.state.PackStatus``, and the row then installs the add-on instead of refusing
    with "install from PyPI instead". Everything else keeps ``dormant_features``'s own
    answer -- ``installable`` and its ``remedy``, which already names the reason for a
    snap, a Homebrew cask, a frozen bundle or a PEP 668 system Python.
    """
    from yazses.packs.state import DAMAGED, NOT_INSTALLED, OK, STALE

    rows: list[FeatureInstallRow] = []
    for item in items:
        status = pack_status(item.slug) if pack_status is not None else None
        if status is not None:
            entry = pack_entry(item.slug) if pack_entry is not None else None
            size = short = ""
            if getattr(status, "download_bytes", 0):
                from yazses.packs.policy import human_bytes

                short = human_bytes(status.download_bytes)
                size = f"{short} download, {human_bytes(status.unpacked_bytes)} on disk"
            state = getattr(status, "state", "")
            if state in (NOT_INSTALLED, STALE, DAMAGED) and entry is not None:
                rows.append(FeatureInstallRow(
                    item.slug, item.name, PACK, size, status.message, entry, short,
                ))
                continue
            if state == OK:
                rows.append(FeatureInstallRow(
                    item.slug, item.name, "", size,
                    f"{status.message} Restart YazSes to load it.",
                ))
                continue
            rows.append(FeatureInstallRow(item.slug, item.name, "", size, status.message))
            continue

        if not getattr(item, "installable", True):
            rows.append(FeatureInstallRow(
                item.slug, item.name, "", "",
                f"{item.name} is on, but its libraries are missing and cannot be "
                f"installed here: {item.remedy}",
            ))
            continue
        size, short = size_note(item)
        rows.append(FeatureInstallRow(
            item.slug, item.name, PIP, size,
            f"{item.name} is on, but {', '.join(item.missing)} "
            f"{'is' if len(item.missing) == 1 else 'are'} not installed, so it does "
            f"nothing.{_price_sentence(size)}",
            item,
            short,
        ))
    return rows


def install_start_text(row: FeatureInstallRow) -> str:
    """What the window says as the install starts (price before charging, ADR-018)."""
    tail = f" — {row.size}" if row.size else ""
    return f"Installing for {row.name}{tail}… The rest of the window keeps working."


# How the transaction reports its undo. These are the lines ``deps._undo`` echoes; a
# contract test drives the real ``_undo`` and checks they still classify.
_UNDONE = "Undone: the environment is exactly as it was"
_NOT_UNDONE = "Could NOT fully undo"


class Rollback(Enum):
    NOT_NEEDED = "not-needed"   # failed before changing anything (or succeeded)
    COMPLETE = "complete"       # everything the install changed was put back
    INCOMPLETE = "incomplete"   # some of it is still different; restore commands printed


def rollback_from(lines: Iterable[str]) -> Rollback:
    """Which undo outcome the transactional install reported, from its own output."""
    seen = Rollback.NOT_NEEDED
    for line in lines:
        if _NOT_UNDONE in line:
            return Rollback.INCOMPLETE
        if _UNDONE in line:
            seen = Rollback.COMPLETE
    return seen


@dataclass(frozen=True)
class InstallResult:
    """What one click on Install now came to, for the status line and the dialogs."""

    slug: str
    name: str
    ok: bool
    rollback: Rollback = Rollback.NOT_NEEDED
    message: str = ""
    lines: tuple[str, ...] = ()


def _restore_block(lines: Sequence[str]) -> str:
    """The restore commands ``_undo`` printed after "Could NOT fully undo", verbatim."""
    for i, line in enumerate(lines):
        if _NOT_UNDONE in line:
            return "\n".join(lines[i:])
    return ""


def pip_result(row: FeatureInstallRow, ok: bool, lines: Sequence[str]) -> InstallResult:
    """Describe a finished ``ondemand.install_one`` from its verdict and its output."""
    rollback = rollback_from(lines)
    if ok:
        message = f"Installed the libraries for {row.name}. Restart YazSes to switch it on."
    elif rollback is Rollback.COMPLETE:
        message = (
            f"{row.name} could not be installed. Everything the install had changed was "
            "undone, so YazSes is exactly as it was. It stays switched on but dormant."
        )
    elif rollback is Rollback.INCOMPLETE:
        message = (
            f"{row.name} could not be installed, and the undo did not finish. Restore the "
            "environment with the commands below, then try again.\n"
            + _restore_block(lines)
        )
    else:
        message = (
            f"{row.name} could not be installed. Nothing was changed. It stays switched "
            "on but dormant."
        )
    if not ok:
        reason = _last_reason(lines)
        if reason and rollback is not Rollback.INCOMPLETE:
            message += f"\nLast message from the installer: {reason}"
    return InstallResult(row.slug, row.name, ok, rollback, message, tuple(lines))


def _last_reason(lines: Sequence[str]) -> str:
    """The installer's last meaningful line, so a failure is never just "failed"."""
    for line in reversed(lines):
        text = line.strip()
        if text and _UNDONE not in text:
            return text[:300]
    return ""


def pack_result(row: FeatureInstallRow, result) -> InstallResult:
    """Describe a finished ``packs.manage.install``. On failure it changed nothing."""
    if result.ok:
        return InstallResult(
            row.slug, row.name, True, Rollback.NOT_NEEDED,
            f"{result.message} Restart YazSes to switch {row.name} on.",
        )
    return InstallResult(
        row.slug, row.name, False, Rollback.NOT_NEEDED,
        f"{result.title}: {result.message}" + _steps(getattr(result, "steps", None)),
    )


def summary_counts(rows: Sequence[FeatureInstallRow]) -> str:
    """The heading line over the dormant-feature rows; empty when there are none."""
    if not rows:
        return ""
    can = sum(1 for r in rows if r.installable)
    noun = "feature is" if len(rows) == 1 else "features are"
    if can == len(rows):
        return f"{len(rows)} switched-on {noun} missing libraries."
    return f"{len(rows)} switched-on {noun} missing libraries; {can} can be installed here."
