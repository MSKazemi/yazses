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

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from yazses.config import Config
from yazses.system.deps import install_blocked_reason, missing_modules
from yazses.system.features import EXPERIMENTAL, find_feature

# Same shape as configedit.set_config_key(path, section, key, value, quote=...),
# with the path already bound by the caller.
ConfigWriter = Callable[[str, str, object, bool | None], None]
ConfigLoader = Callable[[], Config]
DepsProbe = Callable[[Iterable[str]], list[str]]
# Why this environment can never supply a feature's libraries, or None.
BlockedProbe = Callable[[Sequence[str]], str | None]


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

    def current(self, slug: str) -> bool:
        """The state the window is *showing* — staged if edited, else baseline."""
        return self._desired.get(slug, self._original.get(slug, False))

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


def defaults_diff(
    defaults: Mapping[str, bool],
    pending: PendingChanges,
    *,
    toggleable: Iterable[str] | None = None,
) -> list[tuple[str, bool]]:
    """``(slug, default)`` for every row the window is showing off-default.

    Compares against what the window currently *shows* (staged edits included),
    not against the file, so clicking Restore defaults after ticking three boxes
    undoes those three too — which is what "restore" means to the person
    clicking it.

    ``toggleable`` restricts the result to rows that can actually be switched
    here. Without it a reset could stage a capability the window renders greyed
    out, and Apply would then report a failure the user has no way to act on.
    """
    allowed = None if toggleable is None else set(toggleable)
    out: list[tuple[str, bool]] = []
    for slug, default in sorted(defaults.items()):
        if allowed is not None and slug not in allowed:
            continue
        if pending.current(slug) != default:
            out.append((slug, default))
    return out


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
        blocked_probe: BlockedProbe | None = None,
    ) -> None:
        self._load_config = load_config
        self._writer = writer
        self._deps_probe = deps_probe or missing_modules
        self._blocked_probe = blocked_probe or install_blocked_reason

    def set_hotkey(self, key: str) -> ToggleResult:
        """Set the hold-to-talk key, refusing anything unbindable *before* writing.

        A key the platform cannot bind is the worst kind of bad setting: it writes
        fine, and then dictation simply never happens, with nothing on screen
        connecting the two. So validation happens here rather than at the next
        daemon start.

        Two rejections, and the second is the interesting one:

        * not in `SUPPORTED_HOTKEYS` — no backend binds it.
        * the same physical key as ``[hotkey] command_key`` — command mode would
          swallow every dictation burst. Compared through `canonical()` because
          `right_option` and `right_alt` are one key under two names, so a string
          comparison would wave the clash straight through.
        """
        from yazses.hotkeys.names import AUTO, SETTABLE_HOTKEYS, canonical
        from yazses.settingsui.controls import validate_hotkey

        cleaned = (key or "").strip().lower()
        problem = validate_hotkey(cleaned, SETTABLE_HOTKEYS)
        if problem:
            return ToggleResult(ok=False, error=problem)

        try:
            cfg = self._load_config()
        except Exception as exc:  # pragma: no cover - load_config is total
            return ToggleResult(ok=False, error=f"Could not read the config: {exc}")

        # `auto` is checked for a clash by the daemon, not here: it resolves to
        # `platform.default_hotkey` at start, and this process cannot know what
        # that will be on the machine the config ends up on.
        command_key = getattr(getattr(cfg, "hotkey", None), "command_key", "") or ""
        if cleaned != AUTO and command_key and canonical(command_key) == canonical(cleaned):
            return ToggleResult(
                ok=False,
                error=(
                    f"{key!r} is already the command key, and one physical key cannot "
                    f"be both — every dictation would be read as a command. Change "
                    f"the command key first, or pick another hold-to-talk key."
                ),
            )

        try:
            self._writer("hotkey", "key", cleaned, True)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the hotkey: {exc}")
        return ToggleResult(ok=True)

    def set_microphone(self, name: str) -> ToggleResult:
        """Pin capture to *name*, or follow the OS default when it is empty.

        The empty string is a real choice, not an unset field: it is what
        ``[audio] device`` holds when YazSes should follow whatever the system
        picks, and it is the state most people should be in. Pinning is for when a
        device *steals* capture — a USB-C monitor arriving mid-session — not the
        normal case.

        The name is matched as a *substring* by the recorder, so it is stored
        exactly as the user chose it rather than normalised.
        """
        try:
            self._writer("audio", "device", name.strip(), True)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the microphone: {exc}")
        return ToggleResult(ok=True)

    def set_vad_threshold(self, value: float) -> ToggleResult:
        """Set the silence gate, clamped to the range where it means anything.

        Clamped rather than refused. Below the floor the gate treats silence as
        speech; above the ceiling it rejects a shout. A slider cannot produce a
        value outside that range, so a refusal here would only ever be API misuse
        — and silently dropping a drag would be worse than pinning it to the edge.

        A non-numeric value *is* refused, because that is a caller bug and writing
        the string "loud" into a float key would break config loading.
        """
        from yazses.settingsui.controls import clamp_threshold

        try:
            number = float(value)
        except (TypeError, ValueError):
            return ToggleResult(
                ok=False, error=f"{value!r} is not a number — the threshold is a level, e.g. 0.004."
            )

        try:
            self._writer("accessibility", "vad_threshold", clamp_threshold(number), False)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the threshold: {exc}")
        return ToggleResult(ok=True)

    def set_stt_model(self, name: str, language: str | None = None) -> ToggleResult:
        """Choose the transcription model, refusing a pair that cannot work.

        The refusal is the point. Picking an English-only checkpoint while
        ``[stt] language`` names another language does not fail at runtime — Whisper
        transliterates, so the user gets fluent English nonsense and no error. The
        daemon logs it, but a log line loses to a settings window that simply will
        not let the pair be saved.

        A name outside the known set is accepted: a Hugging Face id or a local path
        is a legitimate model, and `is_whisper_model` answers False for both.

        *language* names the language to judge the model against. Pass it when the
        caller already knows the user's intent — the settings window applies the
        model and the language in one click, and validating against the *stored*
        language would judge the new model against the value it is about to
        replace. Omit it to read the config, which is right for any caller acting
        on the model alone.
        """
        from yazses.stt.download import language_model_problem

        cleaned = (name or "").strip()
        if not cleaned:
            return ToggleResult(ok=False, error="Pick a model — an empty name has no default here.")

        if language is None:
            try:
                cfg = self._load_config()
            except Exception as exc:  # pragma: no cover - load_config is total
                return ToggleResult(ok=False, error=f"Could not read the config: {exc}")
            language = getattr(getattr(cfg, "stt", None), "language", "") or ""

        problem = language_model_problem(cleaned, language)
        if problem:
            return ToggleResult(ok=False, error=problem)

        try:
            self._writer("stt", "model", cleaned, True)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the model: {exc}")
        return ToggleResult(ok=True)

    def set_language(self, code: str, model: str | None = None) -> ToggleResult:
        """Set the spoken language, checked against the model that will decode it.

        The empty string is a real choice — auto-detect per utterance — and not an
        unset field, so it is written rather than rejected.

        *model* is the counterpart to `set_stt_model`'s *language*: pass the model
        the user has actually selected so that switching both at once is judged as
        the pair they intend, rather than against whichever half happened to be
        written first.
        """
        from yazses.stt.download import language_model_problem

        cleaned = (code or "").strip()
        if model is None:
            try:
                cfg = self._load_config()
            except Exception as exc:  # pragma: no cover - load_config is total
                return ToggleResult(ok=False, error=f"Could not read the config: {exc}")
            model = getattr(getattr(cfg, "stt", None), "model", "") or "base.en"

        problem = language_model_problem(model, cleaned)
        if problem:
            return ToggleResult(ok=False, error=problem)

        try:
            self._writer("stt", "language", cleaned, True)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the language: {exc}")
        return ToggleResult(ok=True)

    def set_injection_backend(self, backend: str) -> ToggleResult:
        """Choose how text is delivered to the focused window.

        Refused rather than clamped when unknown: an unrecognised backend falls
        through to `auto` at runtime, so accepting it would show the user a setting
        that reads back as theirs while doing something else entirely.
        """
        from yazses.settingsui.controls import INJECTION_BACKENDS

        cleaned = (backend or "").strip().lower()
        if cleaned not in INJECTION_BACKENDS:
            return ToggleResult(
                ok=False,
                error=(
                    f"{backend!r} is not an injection backend. Choose one of: "
                    f"{', '.join(INJECTION_BACKENDS)}."
                ),
            )
        try:
            self._writer("injection", "backend", cleaned, True)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the injection backend: {exc}")
        return ToggleResult(ok=True)

    def set_compute_type(self, name: str, device: str | None = None) -> ToggleResult:
        """Choose the quantisation, refusing one this machine cannot run.

        The refusal is the reason this is worth exposing at all. An unsupported
        compute type raises inside `WhisperModel(...)`, which `stt/faster_whisper.py`
        catches and re-raises as `ModelUnavailableError` — so the user is told their
        *model* is unavailable and given three ways to download a model they already
        have. Nothing mentions quantisation. Refusing at write time replaces a
        misdiagnosis at next start with an accurate message now.

        *device* names the device to check against; omitted, it is read from the
        config, since a machine's supported set differs between cpu and cuda.
        """
        from yazses.settingsui.controls import compute_type_choices

        cleaned = (name or "").strip()
        if not cleaned:
            return ToggleResult(
                ok=False, error="Pick a compute type — an empty value has no default here."
            )

        if device is None:
            try:
                cfg = self._load_config()
            except Exception as exc:  # pragma: no cover - load_config is total
                return ToggleResult(ok=False, error=f"Could not read the config: {exc}")
            device = getattr(getattr(cfg, "stt", None), "device", "") or "cpu"

        # `compute_type_choices` keeps a configured-but-unsupported value in the list
        # so the box can show it; that must not make it *settable*, or the refusal
        # would pass anything already in the file. So the supported set is recomputed
        # from an empty `current`.
        supported = compute_type_choices(device, current="")
        if cleaned not in supported:
            return ToggleResult(
                ok=False,
                error=(
                    f"{name!r} is not a compute type this machine can run on "
                    f"{device!r}. Available here: {', '.join(supported)}."
                ),
            )

        try:
            self._writer("stt", "compute_type", cleaned, True)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the compute type: {exc}")
        return ToggleResult(ok=True)

    def set_initial_prompt(self, text: str) -> ToggleResult:
        """Set the vocabulary primed into the decoder.

        Free text, and deliberately not validated for content: it is a hint to
        Whisper, and there is no wrong string. The empty string is a real choice —
        no priming — and is written rather than rejected.

        Newlines *are* stripped. The value is a single TOML string, and a literal
        newline would produce a file the loader rejects; `configcheck` would then
        repair the whole section to defaults, silently discarding settings the user
        never touched.
        """
        cleaned = " ".join((text or "").split())
        try:
            self._writer("stt", "initial_prompt", cleaned, True)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the vocabulary: {exc}")
        return ToggleResult(ok=True)

    def set_target_guard(self, mode: str) -> ToggleResult:
        """Choose what happens when you dictate with nowhere to type.

        Refused rather than clamped when unknown, for the same reason as the
        injection backend: the daemon compares this against ``"off"`` and treats
        everything else as on, so an unrecognised value would silently mean
        "clipboard" while reading back as whatever the user typed.
        """
        from yazses.settingsui.controls import TARGET_GUARDS

        cleaned = (mode or "").strip().lower()
        valid = [value for _label, value in TARGET_GUARDS]
        if cleaned not in valid:
            return ToggleResult(
                ok=False,
                error=(
                    f"{mode!r} is not a no-text-target mode. Choose one of: "
                    f"{', '.join(valid)}."
                ),
            )
        try:
            self._writer("injection", "target_guard", cleaned, True)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the guard: {exc}")
        return ToggleResult(ok=True)

    def set_pre_speech_padding(self, value) -> ToggleResult:
        """Set the silence prepended before decode, clamped to a useful range.

        Clamped rather than refused, exactly like the VAD threshold: a spin box
        cannot produce an out-of-range number, so a refusal would only ever be API
        misuse — and dropping the edit silently is worse than pinning it.

        A non-numeric value *is* refused, because writing a string into an int key
        makes the config loader repair the section, discarding neighbouring settings
        the user never touched.
        """
        from yazses.settingsui.controls import clamp_padding_ms

        try:
            number = float(value)
        except (TypeError, ValueError):
            return ToggleResult(
                ok=False,
                error=f"{value!r} is not a number — the padding is milliseconds, e.g. 300.",
            )

        try:
            self._writer("accessibility", "pre_speech_padding_ms", clamp_padding_ms(number), False)
        except Exception as exc:  # noqa: BLE001 - surfaced, never raised at Qt
            return ToggleResult(ok=False, error=f"Could not save the padding: {exc}")
        return ToggleResult(ok=True)

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

        if desired:
            # Refuse *before* writing when this environment can never supply the
            # feature's libraries — a snap, whose files are read-only. Naming the
            # packages afterwards (what this used to do) left the config saying
            # "on" while nothing could honour it, and pointed at a `features
            # enable` that refuses for exactly the same reason.
            blocked = self._blocked_reason(feat)
            if blocked is not None:
                return ToggleResult(ok=False, error=f"{feat.name}: {blocked}")

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

    def _blocked_reason(self, feat) -> str | None:
        """Why this environment can never install *feat*'s libraries, or ``None``.

        Only a genuinely impossible install counts, so a capability whose
        libraries the snap already bundles still toggles normally.
        """
        if not self._missing_packages(feat):
            return None
        return self._blocked_probe(feat.pip_packages)

    def _missing_packages(self, feat) -> tuple[str, ...]:
        """Optional deps this feature needs that are not importable here."""
        if not feat.pip_packages:
            return ()
        if feat.check_modules and not self._deps_probe(feat.check_modules):
            return ()
        return tuple(feat.pip_packages)
