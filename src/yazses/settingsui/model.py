"""Pure settings-window model, built from the feature registry + live config.

No Qt import here — ``app.py`` renders this, ``controller.py`` mutates the config
it describes. Grouping, labels, and the toggleable/experimental rules all come
straight from ``system/features.py`` (the single source of truth also used by
``yazses features`` and ``yazses features enable/disable``), so the window can
never drift into a hand-maintained list that disagrees with the CLI.

Each row also carries the material ``yazses features info`` prints — the
description, the "use when" scenario, a concrete example, the config keys the
toggle writes, and the packages it pulls in. ``help.py`` renders that into the
window's tooltips and details dialog, so a checkbox in a window explains itself
exactly as well as the terminal does.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from yazses.config import Config
from yazses.system.features import EXPERIMENTAL, Feature, default_state, grouped_features


@dataclass(frozen=True)
class SettingRow:
    """One feature as a row in the settings window."""

    slug: str
    label: str
    tier_label: str
    enabled: bool
    # False for core features (can't be turned off) and for designed-but-unwired
    # ones (toggling would write a config key nothing reads) — shown, not clickable.
    toggleable: bool
    # True = flipping it ON must go through a confirmation dialog first.
    experimental: bool
    why: str
    # --- help material (see help.py). All optional: a capability with none of it
    # still renders, it just has less to say.
    # Where it lives in config.toml, e.g. "[commands] voice_punctuation".
    note: str = ""
    # A concrete "how do I use it" trigger — a spoken phrase or a command line.
    example: str = ""
    # The "when would I reach for this" scenario.
    use_case: str = ""
    # (section, key, value, quote) tuples enabling the row writes — the honest
    # answer to "what does ticking this actually change?".
    on_writes: tuple = ()
    # Optional pip packages ticking it installs.
    packages: tuple[str, ...] = ()
    # Its state on a fresh install; None when the row is not a switch at all.
    default_enabled: bool | None = None
    # False = designed but not yet wired into any runtime path.
    wired: bool = True
    # True = the config turns it on and nothing reads it. `enabled` above is
    # deliberately False in that case -- the box reflects what is happening, not
    # what the file says -- so this carries the fact the help text needs.
    inert: bool = False


@dataclass(frozen=True)
class SettingsGroup:
    """One functional category (as `yazses features` groups them) + its rows."""

    category: str
    blurb: str
    rows: tuple[SettingRow, ...]


@dataclass(frozen=True)
class SettingsModel:
    groups: tuple[SettingsGroup, ...]
    # Shipped on/off state per toggleable slug — what "Restore defaults" targets.
    defaults: dict[str, bool] = field(default_factory=dict)
    # The configured hold-to-talk key. Not a feature toggle, so it is not a row:
    # the picker needs to open on what is actually set, or it shows a default the
    # user never chose and writes it the moment they touch anything else.
    hotkey: str = ""
    # `[audio] device` — empty means "follow the OS default", which is a choice
    # rather than an absence, so the dropdown needs to show it as one.
    microphone: str = ""
    # `[accessibility] vad_threshold` — the level below which audio is discarded
    # as silence. The number behind every "Silent audio -- discarding" report.
    vad_threshold: float = 0.01
    # `[stt] model` — the single biggest lever on both accuracy and latency, and
    # until now editable only by hand-editing TOML.
    stt_model: str = "base.en"
    # `[stt] language` — "" auto-detects per utterance. Constrained by the model:
    # an `.en` checkpoint cannot decode anything else, so the two are validated
    # together rather than independently.
    language: str = ""
    # `[injection] backend` — how the finished text reaches the focused window.
    injection_backend: str = "auto"
    # `[stt] device`, needed only to ask ctranslate2 which quantisations are
    # available *here*. Not itself editable in the window: changing cpu→cuda without
    # a CUDA build is a config that cannot start, and the window has no way to check.
    stt_device: str = "cpu"
    # `[stt] compute_type` — the accuracy/speed lever below model size. An
    # unsupported value surfaces as "model unavailable" at next start, blaming the
    # wrong thing entirely, so the window offers only what this machine reports.
    compute_type: str = "int8"
    # `[stt] initial_prompt` — vocabulary primed into the decoder so it spells your
    # names and jargon. `yazses tune` proposes additions to this from the corpus;
    # until now, accepting one meant hand-editing TOML.
    initial_prompt: str = ""
    # `[injection] target_guard` — what happens when you dictate with no editable
    # field focused. The tray already has a colour for this state; this is the
    # setting behind it.
    target_guard: str = "clipboard"
    # `[accessibility] pre_speech_padding_ms` — silence prepended before decode so
    # faster-whisper does not clip the first word.
    pre_speech_padding_ms: int = 300

    def rows(self) -> tuple[SettingRow, ...]:
        return tuple(row for group in self.groups for row in group.rows)


def build_settings_model(cfg: Config) -> SettingsModel:
    """Build the settings window model from the feature registry + *cfg*.

    Mirrors ``yazses features``: same categories, same order, same on/off state.
    """
    # Built once, not per row: `default_state()` walks the whole registry, and
    # there are ~200 rows.
    defaults = default_state()
    groups = tuple(
        SettingsGroup(
            category=category,
            blurb=blurb,
            rows=tuple(_row(f, defaults) for f in feats),
        )
        for category, blurb, feats in grouped_features(cfg)
    )
    return SettingsModel(
        groups=groups,
        defaults=defaults,
        hotkey=cfg.hotkey.key,
        microphone=cfg.audio.device,
        vad_threshold=cfg.accessibility.vad_threshold,
        stt_model=cfg.stt.model,
        language=cfg.stt.language,
        injection_backend=cfg.injection.backend,
        stt_device=cfg.stt.device,
        compute_type=cfg.stt.compute_type,
        initial_prompt=cfg.stt.initial_prompt,
        target_guard=cfg.injection.target_guard,
        pre_speech_padding_ms=cfg.accessibility.pre_speech_padding_ms,
    )


def _row(f: Feature, defaults: dict[str, bool]) -> SettingRow:
    return SettingRow(
        slug=f.slug,
        label=f.name,
        tier_label=f.tier_label,
        # `f.on` alone ticked a greyed-out box for a capability nothing reads,
        # on any config seeded before `_UNWIRED` existed.
        enabled=f.on and f.wired,
        toggleable=f.toggleable and f.wired,
        experimental=f.tier == EXPERIMENTAL,
        why=f.why,
        note=f.note,
        example=f.example,
        use_case=f.use_case,
        on_writes=f.on_writes,
        packages=tuple(f.pip_packages),
        default_enabled=defaults.get(f.slug),
        wired=f.wired,
        inert=f.inert,
    )
