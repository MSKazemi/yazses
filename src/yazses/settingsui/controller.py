"""Settings-window action controller — set a feature on/off, write its config.

Performs exactly the same writes ``yazses features enable/disable <slug>`` does
(same registry, same ``on_writes``/``off_writes`` tuples), so the GUI and the CLI
can never disagree about what a toggle means. The config loader, the writer, and
the dependency probe are all injected, so every path — the experimental
confirmation gate, a failed write, a feature whose optional deps are missing —
is testable without touching a real config file.

Two rules this layer exists to enforce:

* **Set, never flip.** The window knows the state the user asked for; it says so.
  Deriving the direction from the config at write time would invert the write
  whenever the file changed after the window was built (a terminal running
  ``yazses features enable`` alongside it), turning "enable this" into "disable
  it".
* **Nothing raises into Qt.** A write that fails comes back as a result the
  window can show, not an exception escaping a signal handler.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from yazses.config import Config
from yazses.system.deps import missing_modules
from yazses.system.features import EXPERIMENTAL, find_feature

# Same shape as configedit.set_config_key(path, section, key, value, quote=...),
# with the path already bound by the caller.
ConfigWriter = Callable[[str, str, object, bool | None], None]
ConfigLoader = Callable[[], Config]
DepsProbe = Callable[[Iterable[str]], list[str]]


@dataclass(frozen=True)
class ToggleResult:
    """What happened when a row was applied."""

    ok: bool
    enabled: bool = False
    # True = the feature is experimental and turning it on needs a second call
    # with ``confirmed=True`` — mirrors the CLI's ``--force`` guard.
    needs_confirmation: bool = False
    error: str | None = None
    # Optional pip packages the feature needs that are not importable here.
    # `yazses features enable` installs these; the window cannot block its UI
    # thread on a pip install, so it names them instead of enabling in silence.
    missing_packages: tuple[str, ...] = ()


class PendingChanges:
    """Settings-window edits staged in memory until Apply. Pure — no Qt, no I/O.

    Tracks each row against the state it loaded with, so checking a box and
    unchecking it again stages nothing, and records which experimental rows the
    user has actually confirmed (a confirmation is spent when the row returns to
    its baseline, so re-checking asks again).
    """

    def __init__(self, original: Mapping[str, bool]) -> None:
        self._original = dict(original)
        self._desired: dict[str, bool] = {}
        self._confirmed: set[str] = set()

    def stage(self, slug: str, desired: bool) -> None:
        """Record that the user wants *slug* in the *desired* state."""
        if self._original.get(slug) == desired:
            self._desired.pop(slug, None)
            self._confirmed.discard(slug)
        else:
            self._desired[slug] = desired

    def confirm(self, slug: str) -> None:
        """Record that the user accepted the experimental warning for *slug*."""
        self._confirmed.add(slug)

    def is_confirmed(self, slug: str) -> bool:
        return slug in self._confirmed

    def baseline(self, slug: str) -> bool:
        """The state *slug* loaded with (or last successfully applied as)."""
        return self._original.get(slug, False)

    def items(self) -> list[tuple[str, bool]]:
        """Staged ``(slug, desired)`` pairs, in a stable order."""
        return sorted(self._desired.items())

    def settle(self, slug: str, enabled: bool) -> None:
        """A write landed: *enabled* is this row's new baseline, nothing staged."""
        self._original[slug] = enabled
        self._desired.pop(slug, None)
        self._confirmed.discard(slug)

    def __len__(self) -> int:
        return len(self._desired)


@dataclass
class ApplyReport:
    """The outcome of applying every staged change — what landed, what did not."""

    applied: int = 0
    errors: list[str] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)
    missing_packages: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.unconfirmed


class SettingsController:
    """Apply settings-window changes. Config load, write and dep probe injected."""

    def __init__(
        self,
        load_config: ConfigLoader,
        writer: ConfigWriter,
        deps_probe: DepsProbe | None = None,
    ) -> None:
        self._load_config = load_config
        self._writer = writer
        self._deps_probe = deps_probe or missing_modules

    def set_enabled(self, slug: str, desired: bool, *, confirmed: bool = False) -> ToggleResult:
        """Put one feature into the *desired* state, mirroring `yazses features`.

        Writes the state the caller asked for rather than flipping whatever the
        config currently says, so a config edited elsewhere after the window was
        built cannot invert the user's intent. Turning ON an experimental feature
        without ``confirmed=True`` writes nothing and returns
        ``needs_confirmation=True`` so the Qt layer can warn and call again.

        Never raises: a failing write comes back as ``ok=False`` with an ``error``.
        """
        try:
            cfg = self._load_config()
        except Exception as exc:  # pragma: no cover - defensive; load_config is total
            return ToggleResult(ok=False, error=f"Could not read the config: {exc}")

        feat = find_feature(cfg, slug)
        if feat is None or not feat.toggleable or not feat.wired:
            return ToggleResult(ok=False, error=f"{slug!r} is not a toggleable feature.")

        if desired and feat.tier == EXPERIMENTAL and not confirmed:
            return ToggleResult(ok=False, needs_confirmation=True)

        writes = feat.on_writes if desired else feat.off_writes
        for index, (section, key, value, quote) in enumerate(writes):
            try:
                self._writer(section, key, value, quote)
            except Exception as exc:
                partial = (
                    f" ({index} of {len(writes)} keys were already written)" if index else ""
                )
                return ToggleResult(
                    ok=False,
                    error=f"Could not write [{section}] {key}: {exc}{partial}",
                )

        return ToggleResult(
            ok=True,
            enabled=desired,
            missing_packages=self._missing_packages(feat) if desired else (),
        )

    def apply(self, pending: PendingChanges) -> ApplyReport:
        """Apply every staged change, settling the ones that land. Never raises.

        Rows that fail — or that still need an experimental confirmation — stay
        staged so the user can fix the cause and click Apply again.
        """
        report = ApplyReport()
        for slug, desired in pending.items():
            result = self.set_enabled(slug, desired, confirmed=pending.is_confirmed(slug))
            if result.ok:
                pending.settle(slug, result.enabled)
                report.applied += 1
                if result.missing_packages:
                    report.missing_packages[slug] = result.missing_packages
            elif result.needs_confirmation:
                report.unconfirmed.append(slug)
            else:
                report.errors.append(result.error or f"{slug}: unknown error")
        return report

    def _missing_packages(self, feat) -> tuple[str, ...]:
        """Optional deps this feature needs that are not importable here."""
        if not feat.pip_packages:
            return ()
        if feat.check_modules and not self._deps_probe(feat.check_modules):
            return ()
        return tuple(feat.pip_packages)
