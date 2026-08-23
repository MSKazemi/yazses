"""Deciding what the settings window installs, and what it says (#135).

`yazses features enable <slug>` installs a capability's optional packages before
telling you to restart. The settings window wrote the config key and stopped —
so for the 15 rows that need an extra it produced a config saying
``enabled = true`` and a daemon that could not load the feature. Honest, but it
sent a GUI user back to the terminal, which is the thing the settings epic exists
to avoid.

All of the *decisions* live here, pure and Qt-free; `app.py` owns only the thread
and the widgets. That split is the rest of `settingsui/`'s convention and it is
what makes the failure modes testable without a display.

## The rule when an install fails, and why

There are two failure shapes, and they are not the same:

* **Impossible** — this environment can never supply the libraries (a strict
  snap, no network policy, an unsupported interpreter). The CLI refuses *before*
  writing config, because "enabling a capability whose libraries can never
  arrive would leave a config key that nothing can honour". The controller
  already mirrors this via ``_blocked_reason``; nothing here changes it.

* **Attempted and failed** — pip ran and returned non-zero. Here the config key
  **stands**, and the window says plainly that the capability is switched on but
  dormant until its packages are installed.

Rolling the config back on that second case is the tempting choice and it is the
wrong one. A failed install is usually transient — a network blip, a mirror
timeout, a wheel building. Silently un-toggling a switch the user just moved
discards their stated intent and, worse, leaves no trace: they toggle again, hit
the same blip, and the window looks broken rather than the network. Keeping the
key matches the CLI exactly, keeps "enabled but dormant" as the visible,
reportable state the rest of the project already models (`yazses doctor` and
`yazses features` both surface dormancy), and leaves something the user can fix
by retrying rather than something they have to rediscover.

The Android port needs the same rule from the other end (#95, where the
equivalent artefact is a downloaded model, not a wheel): **enabling records
intent; satisfying it is a separate, retryable step, and the gap between them is
always visible.**
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class InstallPlan:
    """What to install for one capability the user just switched on."""

    slug: str
    packages: tuple[str, ...]

    def __bool__(self) -> bool:
        return bool(self.packages)


@dataclass(frozen=True)
class InstallOutcome:
    """What happened for one capability."""

    slug: str
    packages: tuple[str, ...]
    ok: bool
    error: str = ""


@dataclass
class InstallSummary:
    """The whole run, in the order the plans were executed."""

    outcomes: list[InstallOutcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(o.ok for o in self.outcomes)

    @property
    def failed(self) -> list[InstallOutcome]:
        return [o for o in self.outcomes if not o.ok]


def plan_installs(
    missing_by_slug: dict[str, Sequence[str]],
    *,
    auto_install: bool,
) -> list[InstallPlan]:
    """Turn the controller's per-slug missing packages into an ordered plan.

    ``auto_install=False`` is the window's equivalent of the CLI's
    ``--no-install`` and yields no plans at all — the config writes still happen,
    exactly as ``features enable --no-install`` behaves.

    Slugs are sorted so a run is deterministic and a progress log is diffable;
    nothing here depends on dict ordering.
    """
    if not auto_install:
        return []
    return [
        InstallPlan(slug=slug, packages=tuple(packages))
        for slug, packages in sorted(missing_by_slug.items())
        if packages
    ]


def total_packages(plans: Iterable[InstallPlan]) -> int:
    """How many packages the whole plan will install (for a progress range)."""
    return sum(len(p.packages) for p in plans)


def run_installs(
    plans: Sequence[InstallPlan],
    *,
    install: Callable[[Sequence[str]], bool],
    echo: Callable[[str], None] = lambda _line: None,
    on_start: Callable[[InstallPlan], None] | None = None,
) -> InstallSummary:
    """Execute *plans*, collecting outcomes. Pure orchestration.

    ``install`` is injected (``system.deps.install_packages`` in production, a
    fake in tests), which is what lets the whole failure matrix be exercised with
    no network and no Qt. A raising installer is recorded as a failed outcome
    rather than propagating: one capability failing to install must not abandon
    the ones after it in the plan.
    """
    summary = InstallSummary()
    for plan in plans:
        if on_start is not None:
            on_start(plan)
        try:
            ok = bool(install(plan.packages))
            error = "" if ok else "the installer exited non-zero"
        except Exception as exc:  # noqa: BLE001 - reported, never raised at the UI
            ok, error = False, str(exc)
            echo(f"{plan.slug}: {exc}")
        summary.outcomes.append(
            InstallOutcome(slug=plan.slug, packages=plan.packages, ok=ok, error=error)
        )
    return summary


def describe_summary(summary: InstallSummary) -> str:
    """One line the window can show. Empty when there is nothing to say."""
    if not summary.outcomes:
        return ""
    installed = [o for o in summary.outcomes if o.ok]
    parts: list[str] = []
    if installed:
        parts.append(
            f"Installed packages for {', '.join(o.slug for o in installed)}."
        )
    for outcome in summary.failed:
        parts.append(describe_failure(outcome))
    return "  ".join(parts)


def describe_failure(outcome: InstallOutcome) -> str:
    """Say exactly what state the user is in — never just 'install failed'.

    The config key stands (see the module docstring), so the message has to name
    that, or the user is left believing the toggle did nothing.
    """
    packages = " ".join(outcome.packages)
    detail = f" ({outcome.error})" if outcome.error else ""
    return (
        f"{outcome.slug} is switched on but {packages} could not be installed"
        f"{detail}. It stays dormant until they are. Retry with: "
        f"yazses features enable {outcome.slug}"
    )


def _depsize_price(slug: str, packages: Sequence[str]) -> tuple[str, bool]:
    """``(note, loud)`` for one capability, from the committed size table (ADR-018).

    Imported here rather than at module scope for the reason the rest of this package
    imports late: `settingsui/deps.py` is pure and must stay importable wherever the
    window's wiring is inspected.
    """
    from yazses.system.depsize import download_note, is_a_large_download

    return download_note(slug, list(packages)), is_a_large_download(slug, list(packages))


def describe_install_start(plans: Sequence[InstallPlan], *, price=None) -> str:
    """What the window says *before* it spends the user's bandwidth (ADR-018).

    `yazses features enable` prints the marginal download note first, and shouts for a
    large one, because "a download that turns out to be gigabytes is one the user should
    have been able to cancel". The window said only "this can take a few minutes" -- for
    installs that are ~3.1 GB.

    It is worse here than in the terminal: this window has no cancel at all. The worker
    exposes no interrupt and Apply is disabled while it runs, so the CLI's "Ctrl-C now to
    stop" has no equivalent, and the number *before* the click is the only warning that
    can help. That is why a loud run says plainly that it cannot be stopped.

    ``price`` is injected so the whole message matrix tests without the size catalogue.
    A pricing lookup that raises is treated as no price rather than an error: a size is a
    courtesy, and the CLI already refuses to let one break the thing it annotates.
    """
    if not plans:
        return ""
    lookup = price or _depsize_price
    slugs = ", ".join(p.slug for p in plans)

    notes: list[str] = []
    loud = False
    for plan in plans:
        try:
            note, is_loud = lookup(plan.slug, plan.packages)
        except Exception:  # noqa: BLE001 - a size must never break the message
            note, is_loud = "", False
        if note:
            # The slug is already in the "installing packages for X" clause, so repeat it
            # only when there is more than one and the notes would otherwise be ambiguous.
            notes.append(f"{plan.slug} {note}" if len(plans) > 1 else note)
        loud = loud or bool(is_loud)

    if not notes:
        return f"Installing packages for {slugs}\u2026 this can take a few minutes."

    detail = "; ".join(notes)
    if loud:
        return (
            f"\u26a0 Large download \u2014 installing packages for {slugs}\u2026 "
            f"{detail}. This cannot be stopped once it has started."
        )
    return f"Installing packages for {slugs}\u2026 {detail}."


def describe_skipped(missing_by_slug: dict[str, Sequence[str]]) -> str:
    """The message when the user opted out of installing (`--no-install`)."""
    if not missing_by_slug:
        return ""
    rows = ", ".join(
        f"{slug} ({' '.join(packages)})"
        for slug, packages in sorted(missing_by_slug.items())
        if packages
    )
    if not rows:
        return ""
    return (
        f"Not installing packages, as asked. These stay dormant until you do: "
        f"{rows}."
    )
