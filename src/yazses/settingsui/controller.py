"""Settings-window action controller — toggle a feature, write its config.

Performs exactly the same writes ``yazses features enable/disable <slug>`` does
(same registry, same ``on_writes``/``off_writes`` tuples), so the GUI and the CLI
can never disagree about what a toggle means. The config loader and the writer
are both injected, so every path — including the experimental confirmation gate
— is testable without touching a real config file.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from yazses.system.features import EXPERIMENTAL, find_feature

# Same shape as configedit.set_config_key(path, section, key, value, quote=...),
# with the path already bound by the caller.
ConfigWriter = Callable[[str, str, object, bool | None], None]
ConfigLoader = Callable[[], object]


@dataclass(frozen=True)
class ToggleResult:
    """What happened when a row was toggled."""

    ok: bool
    enabled: bool = False
    # True = the feature is experimental and turning it on needs a second call
    # with ``confirmed=True`` — mirrors the CLI's ``--force`` guard.
    needs_confirmation: bool = False
    error: str | None = None


class SettingsController:
    """Apply settings-window toggles. Config load + write are both injected."""

    def __init__(self, load_config: ConfigLoader, writer: ConfigWriter) -> None:
        self._load_config = load_config
        self._writer = writer

    def toggle(self, slug: str, *, confirmed: bool = False) -> ToggleResult:
        """Flip one feature on/off, mirroring `yazses features enable/disable`.

        Turning ON an experimental feature without ``confirmed=True`` does not
        write anything — it returns ``needs_confirmation=True`` so the Qt layer
        can show a warning dialog and call again once the user confirms.
        """
        cfg = self._load_config()
        feat = find_feature(cfg, slug)
        if feat is None or not feat.toggleable or not feat.wired:
            return ToggleResult(ok=False, error=f"{slug!r} is not a toggleable feature.")

        turning_on = not feat.on
        if turning_on and feat.tier == EXPERIMENTAL and not confirmed:
            return ToggleResult(ok=False, needs_confirmation=True)

        writes = feat.on_writes if turning_on else feat.off_writes
        for section, key, value, quote in writes:
            self._writer(section, key, value, quote)
        return ToggleResult(ok=True, enabled=turning_on)
