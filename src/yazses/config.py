import dataclasses
import logging
import tomllib
import typing
from dataclasses import dataclass, field
from pathlib import Path

from yazses.configcheck import ConfigProblem, build_section

log = logging.getLogger(__name__)


@dataclass
class SttConfig:
    # Which speech-to-text backend decodes audio: "faster-whisper" (default,
    # Whisper via CTranslate2) | "parakeet" (NVIDIA Parakeet TDT via onnx-asr —
    # better English WER than whisper-large-v3 at ~30x realtime CPU, no silence
    # hallucinations; opt-in via `yazses features enable stt-parakeet`). An
    # unknown value or a missing optional dep falls back to faster-whisper with
    # a logged warning — never a crash (stt/factory.py).
    engine: str = "faster-whisper"
    # base.en balances accuracy and CPU latency far better than tiny.en, which
    # produces frequent word errors. Larger models (small.en/medium.en) trade
    # decode latency for marginal gains on clean speech.
    model: str = "base.en"
    # Spoken language, as a Whisper code ("en", "de", "fr", "es", "fa", …).
    # Empty string = let Whisper auto-detect per utterance, which costs an extra
    # decode pass and can flip mid-session, so an explicit code is preferred when
    # you know the language. Requires a MULTILINGUAL model: the `.en` checkpoints
    # (base.en, small.en, …) are English-only and cannot decode anything else, so
    # set `model = "small"` (no suffix) alongside it — stt/factory.py warns when
    # the pair is contradictory. Ignored on the translate path (ADR-v2-014), which
    # auto-detects the source by design, and by the Parakeet engine (English-only).
    language: str = "en"
    device: str = "cpu"
    compute_type: str = "int8"
    # Optional vocabulary/context primed into Whisper as initial_prompt. Helps it
    # spell domain terms and proper nouns it otherwise mis-transcribes. `yazses
    # tune` proposes additions here from the learning corpus.
    initial_prompt: str = ""
    # Recover personal-vocabulary words the recogniser mis-heard, after decoding
    # (#73). `initial_prompt` is Whisper-only, so with `engine = "parakeet"` the
    # personal dictionary is otherwise ignored entirely — this is engine-agnostic
    # and helps Whisper too. OFF by default: it rewrites transcribed text, and
    # that is a thing a user should switch on knowingly.
    vocab_correction: bool = False
    # How many CPU cores the decoder may use. 0 keeps ctranslate2's default, which
    # is "all of them" — a 0.8 s decode measured 4.9 CPU-seconds on a 20-core
    # laptop, because the work is spread across every core. That is the right
    # trade on mains power and the wrong one on battery, where the cost is the
    # core-seconds rather than the wall-clock. Nothing capped it before this.
    cpu_threads: int = 0
    # Which Han script Chinese output is written in: "simplified" (简体, mainland)
    # | "traditional" (繁體, Taiwan/Hong Kong) | "" to leave the model's own choice
    # alone. Whisper picks a script per utterance and is not consistent about it,
    # so a mainland user gets Traditional characters back for a large share of
    # correct transcriptions (postprocess/han_script.py has the measurements).
    # Empty by default because the right answer is regional, not universal.
    # Needs the `chinese` extra; without it the setting warns once and no-ops.
    chinese_script: str = ""


@dataclass
class HotkeyConfig:
    # "auto" resolves to the platform's default hold-to-talk key (Linux:
    # right_alt, macOS: right_option, Windows: right_ctrl) — a modifier key, so
    # it never collides with normal typing the way the space bar would.
    key: str = "auto"
    hold_threshold_ms: int = 500
    source: str = "default"
    evdev_device: str = ""
    # Optional dedicated *command* key. Empty = single-key mode (commands are
    # auto-detected on the dictation key). When set to a different key, holding
    # it forces command mode: whatever you say is parsed as a command and never
    # typed as literal text (an unrecognised phrase is ignored, not inserted).
    command_key: str = ""


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    # Hard cap on a single hold-to-talk recording. Generous so long dictations
    # aren't cut off mid-sentence; raise further in config for very long takes.
    max_record_seconds: int = 300
    # Pin the input microphone by name (case-insensitive substring). Empty =
    # follow the OS default input device. Resolved fresh on each recording, so a
    # hotplug that shifts device indices can't break the pin. Set it with
    # `yazses audio use <name>` so a monitor/headset can't silently steal capture.
    device: str = ""
    # Desktop-notify (with action buttons where supported) when the OS default
    # input device changes — so a silent switch that breaks dictation is visible.
    device_change_notify: bool = True
    # Desktop-notify after a run of consecutive silent-discards (the direct
    # "dictation stopped writing" symptom of a mic that switched to a dead source).
    silent_streak_notify: bool = True
    # How many silent-discards in a row trigger the notify + auto-heal.
    silent_streak_threshold: int = 3
    # On a device change / silent streak, automatically switch capture back to the
    # last device that produced usable audio ("last-good"), then notify what changed.
    auto_heal_device: bool = True
    # Cadence of the background default-input-device watcher, in seconds. 0 disables
    # the watcher (the silent-streak detector still works, being on the hot path).
    device_poll_interval_s: float = 3.0
    # Answer the mic guard's [Re-calibrate]/[Pin this mic]/[Ignore] toast by SAYING one
    # of them (ADR-022, Spec 1). Without this the daemon asks a question about your
    # microphone that can only be answered with a pointer -- and the person seeing it is
    # the one whose dictation just stopped working. OFF by default like the other
    # utterance-consuming guards (`[cmdsafety]`, `[checkdigit]`): it swallows a burst
    # that would otherwise be typed, and that is a behaviour change to opt into.
    voice_answer: bool = False
    # How long the toast stays answerable by voice. Bounded on purpose -- "ignore" is
    # an ordinary word, and an unbounded window arms it for the rest of the session.
    voice_answer_window_s: float = 45.0


@dataclass
class InjectionConfig:
    backend: str = "auto"
    fallback_to_clipboard: bool = True
    # Successive hold-to-talk bursts within this window are treated as one
    # continuous dictation: a separating space is prepended to the next burst
    # so words don't glue together at the boundary (postprocess/spacing.py).
    # 0 disables continuation spacing entirely.
    continuation_window_ms: int = 30000
    # "No text target" guard: what to do when you dictate with no editable field focused
    # (so the text would be typed into the wrong place / nowhere). "clipboard" (default) —
    # copy the transcript to the clipboard + notify instead of typing; "warn" — notify but
    # still type; "off" — no guard. Detection is AT-SPI when available (precise; needs
    # python3-pyatspi), else a best-effort X11 focus check. Only acts on a *confident* "no
    # target", so it never drops normal dictation.
    target_guard: str = "clipboard"


@dataclass
class GeneralConfig:
    log_level: str = "INFO"
    # Periodically ask whether a newer YazSes has been released and, if so, say
    # so once with the exact steps to update.
    #
    # OFF by default, and it must stay that way: this is the only thing in YazSes
    # that reaches the network on its own, and "nothing leaves the machine" is the
    # product. A background check tells github.com/PyPI your IP and that you run
    # this tool. Nothing about your voice, audio, text or config is ever sent —
    # the request is a plain "what is the latest version" GET — but it is still an
    # outbound connection the user has to choose. Turn it on with
    # `yazses features enable update-check`.
    update_check: bool = False
    update_check_interval_hours: int = 24


@dataclass
class StreamingConfig:
    # Disabled by default for two independent reasons.
    #
    # Correctness: live-partial injection corrects on commit via shift+Left
    # selection (inject/streaming.py), which deletes text in apps where
    # shift+Left isn't "extend selection". Batch transcribe-on-release is the
    # reliable, higher-accuracy path proven by tools like nerd-dictation and
    # faster-whisper-dictation.
    #
    # Latency: streaming does NOT make the final text arrive sooner — commit()
    # re-decodes the whole utterance anyway, now competing with a decode loop
    # running every partial_interval_ms. Measured (paper/benchmark/bench_streaming.py,
    # n=15 real-time-fed utterances): speech-end -> final text 0.92 s -> 1.22 s on
    # tiny.en, and 1.42 s -> 2.21 s on base.en. Worse, on base.en the rolling
    # decode cannot keep up with the audio, so LocalAgreement confirmed no prefix
    # at all before release in 9 of 15 utterances (0 % visible at release, vs 72 %
    # on tiny.en). Streaming is only a win on tiny.en.
    #
    # Opt back in with [streaming] enabled = true.
    enabled: bool = False
    partial_interval_ms: int = 300
    partial_marker: str = ""


@dataclass
class DisfluencyConfig:
    enabled: bool = True
    filler_words: list[str] = field(default_factory=lambda: [
        # "err" is deliberately absent: it is an ordinary English verb
        # ("to err is human", "err on the side of caution"), so stripping it by
        # default deleted real words mid-sentence (issue #125). Users who really
        # do hesitate with "err" can add it back to [filters.disfluency].
        #
        # like / right / sort of / kind of / actually are deliberately absent
        # too (issue #146): each is a genuine filler in some positions and
        # load-bearing content in others. Stripping them by default turns hedges
        # into facts, drops predicates ("not right" → "not"), and erases
        # correction markers. Users who want aggressive filler removal can add
        # them back under [filters.disfluency].
        #
        # `basically` and `literally` were removed for the same reason (issue
        # #236): "it seems basically correct" is a hedge and "it seems correct"
        # is a claim, and "the value is literally zero" asserts a precision that
        # "the value is zero" does not. The #146 test applies to them exactly —
        # they were simply missed when it was applied to the others.
        "um", "uh", "er", "ah", "hmm", "you know",
        "i mean", "okay so",
        "so um", "so uh",
    ])
    self_correction_triggers: list[str] = field(default_factory=lambda: [
        "no wait", "delete that", "scratch that", "never mind",
        "forget that", "strike that",
    ])
    # v0.8.0 — Dysfluency-Friendly Mode collapse pass (ADR-015); off by default.
    collapse_repetitions: bool = False      # b-b-because / b b because / the the the
    collapse_prolongations: bool = False    # sooo -> so
    prolongation_min_run: int = 3           # letter-run length that triggers collapse
    repetition_max_fragment_len: int = 2    # max length of a stutter "fragment"
    llm_enabled: bool = False
    llm_endpoint: str = "http://localhost:11434"
    # Refuse an `llm_endpoint` that is not loopback. Cleanup sends *transcribed
    # text* to the endpoint, so a remote host here would carry dictation off the
    # machine — which AGENTS.md rule 1 ("nothing leaves the machine") forbids by
    # default. Setting this true is the deliberate, documented opt-out; the
    # daemon warns on every start while it is on.
    llm_allow_remote_endpoint: bool = False
    # Local GGUF model path for offline cleanup; empty falls back to the Ollama
    # HTTP endpoint above. Mirrors the Rust v1.0 [cleanup] feature for the
    # Python path (kept in parity until v1.0 GA).
    llm_model: str = ""
    llm_system_prompt: str = (
        "Reformat only. Do not add facts and do not remove information. "
        "Preserve every proper noun, number, code identifier, and URL exactly "
        "as given. Fix capitalization, punctuation, and paragraph breaks; do "
        "not change word choices. Output ONLY the reformatted text with no "
        "preamble, no explanation, and no markdown fences."
    )
    llm_max_tokens: int = 256
    llm_timeout_ms: int = 2000
    llm_min_length_ratio: float = 0.5
    llm_max_length_ratio: float = 2.0


@dataclass
class FiltersConfig:
    disfluency: DisfluencyConfig = field(default_factory=DisfluencyConfig)


@dataclass
class AccessibilityConfig:
    min_silence_ms: int = 500
    # Silence lead-in prepended before STT decode. faster-whisper drops/clips the
    # first word when a clip starts abruptly mid-utterance; a short lead-in gives
    # it a clean onset boundary so the opening word survives.
    pre_speech_padding_ms: int = 300
    vad_source: str = "default"
    vad_threshold: float = 0.01
    # v0.8.0 — Dysfluency-Friendly Mode master preset (ADR-015): enables the
    # disfluency collapse pass and widens onset padding. Off by default.
    dysfluency_friendly: bool = False
    # v2 — Read-Back Loop (spec-read-back-loop): speak the final transcript back
    # via offline TTS so dictation can be verified by ear. "off" (default) |
    # "final" (P1: read the final transcript) | "confirm" (P2: full yes/no/redo
    # loop). Requires [tts] enabled. confirm_timeout_s is the P2 listen window.
    read_back: str = "off"
    confirm_timeout_s: float = 6.0


@dataclass
class TtsConfig:
    """v2 — offline text-to-speech for the Read-Back Loop (spec-read-back-loop).

    OFF by default (ADR-011): nothing is imported or downloaded unless ``enabled``.
    Permissive engines only — Kokoro-82M (Apache-2.0, default) / MeloTTS (MIT) /
    KittenTTS (Apache-2.0); GPL Piper fork and XTTS are excluded. The TTS deps live
    in the optional ``tts`` extra (kokoro-onnx, onnxruntime, soundfile).
    """
    enabled: bool = False
    engine: str = "kokoro"            # kokoro | melo | kitten
    voice: str = "default"
    model_path: str = ""              # override; empty => auto-resolved/downloaded
    voices_path: str = ""             # Kokoro voices file; empty => auto-resolved
    sample_rate: int = 24000          # Kokoro native rate
    speed: float = 1.0
    max_readback_chars: int = 600     # truncate very long bursts with "…"
    # v2.2 Wave F — Personal Read-Back Voice (ADR-v2-042). OFF by default.
    clone_voice: bool = False         # read back in a clone of the user's own voice
    clone_backend: str = "openvoice"  # openvoice (permissive) | f5 | xtts (non-commercial, opt-in)


@dataclass
class CommandsConfig:
    enabled: bool = True
    profile: str = "auto"
    custom: list[dict] = field(default_factory=list)
    # v0.4.0 — Tier 2 SLM intent routing (ADR-v04-001)
    slm_model_path: str = ""          # path to GGUF file; empty = disabled
    slm_confidence_threshold: float = 0.75
    # v0.4.0 — LSP context injection (ADR-v04-002)
    lsp_enabled: bool = False
    lsp_editor: str = "auto"          # auto | neovim | vscode
    # v1.4.0 — spoken punctuation/formatting in dictation ("comma", "new line").
    # Off by default: these words also occur in ordinary speech.
    voice_punctuation: bool = False
    # Offline Command Mode (#99): with a selection and the command key held,
    # "make this shorter" rewrites it in place using the LOCAL model configured
    # under [filters.disfluency]. OFF by default — it replaces text the user
    # already wrote, which is not something to switch on for them.
    rewrite: bool = False
    # Seconds a local rewrite may take before it is abandoned and the selection
    # left alone. A stalled model must not hold the dictation pipeline.
    rewrite_timeout_s: float = 20.0
    # v2.4 Wave H — Emoji & Symbol by Voice (ADR-v2-055): "shrug emoji"→🤷, "right arrow"→→.
    # Off by default: the names also occur in ordinary speech.
    symbols: bool = False
    # v2.4 Wave H — Mid-Utterance Self-Repair (ADR-v2-058): "email Sarah no I mean Sara"→"Sara".
    # Off by default: editing phrases also occur in ordinary speech.
    self_repair: bool = False
    # v2.0.0 Wave A — Spoken Edit Mode (ADR-v2-003): open-ended voice editing of the
    # last-injected span ("change X to Y", "delete the last sentence"). Command-key
    # gated to avoid dictate-vs-command ambiguity. OFF by default.
    spoken_edit: bool = False
    # Allow destructive spoken edits (delete last sentence/words). OFF by default;
    # when on, a destructive edit still updates the ledger so "scratch that" undoes
    # it. Requires spoken_edit. (ADR-v2-003)
    spoken_edit_destructive: bool = False


@dataclass
class LearningConfig:
    """v0.5.0 — opt-in self-improvement loop (ADR-012).

    OFF by default to honour ADR-011 (zero telemetry, no transcript persistence).
    When enabled, each dictation event is captured to a local, encrypted corpus
    (text stages + optional source audio) that never leaves the machine. The
    `yazses tune` command turns that corpus into proposed config diffs.
    """
    enabled: bool = False
    capture_audio: bool = True
    retention_days: int = 30
    max_corpus_mb: int = 500
    # Larger model used by `yazses tune` to re-transcribe captured audio and
    # produce pseudo-ground-truth for error detection.
    tune_model: str = "small.en"
    # Regexes scrubbed (replaced with [REDACTED]) from text before it is stored.
    redact_patterns: list[str] = field(default_factory=list)
    # v2.3 Wave G — Corpus Voiceprint Scrub (ADR-v2-048): speaker-anonymize stored clips.
    anonymize_audio: bool = False
    anonymize_strength: float = 1.08
    # Edit capture (signal b): after a dictation, read the editor line back and
    # record what you changed in place. Opt-in, editor-bridge only (NO keystroke
    # logging). Currently supports Neovim via a --listen socket.
    capture_edits: bool = False
    edit_capture_delay_s: float = 8.0
    editor_socket: str = ""           # e.g. nvim --listen /tmp/nvim.sock; empty = disabled


@dataclass
class MacrosConfig:
    """v2 — Say-Macro: user-programmable voice macros (spec-say-macro).

    OFF by default per ADR-011. When enabled, triggers and expansions are read
    from a dedicated ``macros.toml`` (sibling of config.toml); this section only
    carries the switches. P1 supports ``text`` and ``snippet`` expansions matched
    by whole-utterance exact match; OS-action chains land in P2.
    """
    enabled: bool = False
    path: str = "macros.toml"         # relative to config dir, or absolute
    author: str = ""                  # value substituted for ${author}


@dataclass
class ReviseConfig:
    """v2 — Mid-Thought Undo (spec-mid-thought-undo), P1 template layer.

    "scratch that" / "delete that" delete the last YazSes-injected dictation
    burst via backspaces (works in any text field). On by default with the rest
    of the command grammar; open-ended "no, make it X" rewrite is deferred to P2.
    """
    enabled: bool = True


@dataclass
class GazeConfig:
    """v2 — Glance-Type (spec-glance-type), P1 look-to-pane (design/v2-cognitive-layer §3.3).

    Glance at a coarse screen zone to target where the next dictation lands. Webcam
    gaze is coarse (~3-5 cm), so this is look-to-PANE, not look-to-caret. OFF by
    default; needs a webcam + a one-time calibration. The gaze backend lives in the
    optional ``gaze`` extra (l2cs-net + mediapipe + opencv); frames are processed
    in-RAM during a hold and never stored or sent (ADR-011).
    """
    enabled: bool = False
    backend: str = "mediapipe"        # mediapipe (light, offline) | l2cs | none
    model_path: str = ""              # override the mediapipe model asset; "" = auto-download
    zones: str = "grid3x3"            # grid3x3 | grid2x2 | windows
    camera_index: int = 0
    calibration_points: int = 9
    confidence_min: float = 0.5
    # v2.0.0 Wave C — Gaze-Routed Dictation (ADR-v2-010): route the next dictation
    # to the looked-at window (else the focused window), and confirm destructive
    # gaze-routed actions since coarse gaze can misroute. Off by default.
    route_dictation: bool = False
    confirm_destructive: bool = True
    # Gaze deixis (2026-08): in command mode, "close this" / "focus that" /
    # "minimize this" act on the window the gaze snapshot says you are looking
    # at. Sub-flag of the (opt-in) gaze feature; destructive actions honour
    # confirm_destructive above via an actionable confirm toast.
    deixis: bool = True


@dataclass
class CocktailConfig:
    """v2 — Cocktail Filter (spec-cocktail-filter), P1 personal-VAD gate (§3.2).

    Drop audio frames that aren't the enrolled target speaker, so an interfering
    voice never enters the transcript. OFF by default; requires an enrolled
    voiceprint (else dormant). ``mode="suppress"`` (P2) is gated on an open model.
    """
    enabled: bool = False
    mode: str = "gate"                # gate (P1) | suppress (P2, gated on a model)
    target_threshold: float = 0.5     # per-window target-speaker cosine score to keep
    window_ms: int = 500              # window the gate scores (ECAPA needs ~0.5s+)


@dataclass
class PersonalizeConfig:
    """v2 — Voiceprint Mind (spec-voiceprint-mind), P1 biasing (§3.1).

    Personalize STT to the user. P1 (this): compose ``initial_prompt`` from the user
    vocabulary + frequent personal n-grams mined from the corpus — nearly free, no
    training. P2 (``lora``): an opt-in nightly LoRA personal fine-tune (train→merge→
    ct2-convert), gated on a held-out WER win. OFF by default.
    """
    enabled: bool = False
    bias_from_corpus: bool = True
    max_prompt_terms: int = 64
    lora: bool = False                # P2 master switch (training is heavy)
    lora_base_model: str = "small.en"
    lora_min_events: int = 200
    lora_min_improvement: float = 0.03  # min held-out relative WER win to apply (ADR-v2-021)


@dataclass
class PolyglotConfig:
    """v2 — Polyglot Switch (spec-polyglot-switch), P0 scaffolding (§3.4).

    Transcribe code-switched speech for one configured pair (e.g. "fa-en"). Needs a
    trained CS adapter (stock Whisper can't code-switch); dormant until ``adapter_path``
    is set. OFF by default.
    """
    enabled: bool = False
    pair: str = ""
    adapter_path: str = ""
    lid: str = "segment"
    mer_gate: float = 0.0


@dataclass
class VoiceprintConfig:
    """v2 shared infra — speaker enrollment + embedding (design/v2-cognitive-layer).

    A one-time enrollment produces a speaker embedding (d-vector) used by
    Cocktail Filter (target-speaker gate) and Voiceprint Mind (personalization).
    OFF by default; the embedder lives in the optional ``voiceprint`` extra and is
    imported only when enabled. The embedding is biometric → stored only in the
    encrypted learning corpus (ADR-012), never plaintext, never leaves the machine.
    """
    enabled: bool = False
    backend: str = "ecapa"            # ecapa (speechbrain) | resemblyzer
    enroll_seconds: float = 25.0      # speech captured during enrollment
    multi_profile: bool = False       # v2.1 Wave E — N-way per-speaker routing (ADR-v2-028)
    profile_min_similarity: float = 0.5  # min cosine to switch to a matched profile


@dataclass
class PunchInConfig:
    """v2 — Punch-In (spec-punch-in), P1 alignment core.

    Re-speak a phrase to correct a span; the daemon/UI surfaces the top aligned
    candidates to confirm (not auto-splice) because pure respeak fixes only ~35%
    (Suhm 2001). OFF by default; the interactive re-record + confirm flow is P2.
    """
    enabled: bool = False
    min_score: float = 0.5            # minimum difflib similarity to surface a span
    max_candidates: int = 3
    record_seconds: float = 4.0       # re-record window for the respoken phrase


@dataclass
class EndpointConfig:
    """v2 — Ghost Ahead -> endpoint anticipation (spec-ghost-ahead), P1 core.

    Predicts *when* the speaker stops (stable partial + trailing silence) to hide
    release latency. OFF by default; the authoritative transcript always stays on
    real hold-release. Phase 1 = harmless pre-warm (eager decode on endpoint);
    speculative finalize (Phase 2) stays gated behind ``speculative_finalize``.
    """
    enabled: bool = False
    min_silence_s: float = 0.3
    stable_updates: int = 2
    prewarm: bool = True              # Phase 1: eagerly decode the buffer on endpoint
    speculative_finalize: bool = False  # Phase 2 (gated): decode early, discardable
    debounce_ms: int = 500           # min gap between endpoint fires (anti-thrash)
    prefix_stable_ms: int = 400      # confirmed prefix unchanged this long = content flat
    falling_window_ms: int = 250     # window over which trailing energy must be falling


@dataclass
class ProsodyConfig:
    """v2 — Prosody Ink (spec-prosody-ink), P1 wired into the dictation pipeline.

    Maps vocal prosody to text formatting: a long inter-word pause becomes a
    paragraph break (Phase 1, no acoustic dep), vocal emphasis becomes bold
    (Phase 2, needs the ``prosody`` extra → parselmouth). OFF by default; batch +
    dictation only. ``format="none"`` keeps the universal pause→¶ whitespace but
    suppresses emphasis (no portable way to express bold in plain text). The
    pitch→question signal stays gated behind ``experimental_pitch_question`` and
    is never built into Phase 1 (acoustically unreliable, ~64.6%; PMC2631211).
    """
    enabled: bool = False
    format: str = "none"              # none | markdown
    pause_paragraph_ms: int = 700     # inter-word gap (ms) at/above which a ¶ is inserted
    # v2.0.0 Wave A — pause→sentence punctuation (ADR-v2-002). 0 disables; when >0, a gap
    # at/above this (but below pause_paragraph_ms) inserts a sentence-ending period.
    pause_sentence_ms: int = 0
    emphasis_enabled: bool = True     # bold prominent words (only when format renders bold)
    emphasis_sensitivity: float = 0.65  # 0..1; higher = fewer, surer bolds (precision bias)
    experimental_pitch_question: bool = False
    max_latency_ms: int = 150         # latency valve: above this, log + degrade to pause-only


@dataclass
class RemoteConfig:
    default_host: str = ""
    ssh_port: int = 22
    agent_port: int = 9875
    key_file: str = ""


@dataclass
class EmgConfig:
    """v0.4.0 — EMG silent speech backend (ADR-v04-003).

    v0.4.1 adds ``ble_address`` for wireless BLE transport (same YESP protocol).
    Set either ``device_port`` (USB serial) or ``ble_address`` (BLE), not both.
    """
    device_port: str = ""             # e.g. /dev/ttyUSB0; empty = disabled
    baud_rate: int = 115200
    ble_address: str = ""             # e.g. "AA:BB:CC:DD:EE:FF"; empty = disabled
    mode: str = "command"             # command | full_text
    command_map: dict[str, str] = field(default_factory=dict)


@dataclass
class OverlayConfig:
    """v0.5.0 — futuristic on-screen voice-activity indicator.

    A standalone ``yazses-overlay`` process (separate from the daemon, which is
    blocked by the hotkey loop) draws an animated "sonar" — concentric rings that
    expand near the cursor and pulse with your live mic level while you dictate.
    It is a thin IPC client that polls the daemon's ``status`` RPC, so either the
    Python or the Rust daemon can drive it. Requires the ``overlay`` extra
    (``pip install yazses[overlay]`` / ``uv sync --extra overlay``) for PySide6.
    """
    enabled: bool = True             # auto-launch the overlay with the daemon
    # (on by default; soft no-op when the `overlay` extra / PySide6 is absent)
    style: str = "sonar"             # reserved for future styles
    position: str = "cursor"         # cursor | bottom_center | top_center | corner
    react_to_voice: bool = True      # amplitude-driven vs state-only self-animation
    accent: str = "#00e5ff"          # ring colour (neon cyan)
    size_px: int = 220               # overlay window square size
    fps: int = 60                    # render tick rate
    cursor_offset_px: int = 28       # offset from the pointer so it isn't under the caret
    # auto | on | off. `auto` follows the desktop's own reduce-animations setting
    # (GNOME, macOS, Windows); a desktop it cannot read means full motion, as before.
    # Reduced motion keeps the ring and drops the travel -- it removes the animation,
    # not the answer to "am I being heard".
    reduced_motion: str = "auto"


@dataclass
class TrayConfig:
    """System-tray / top-bar indicator icon with a click-menu.

    A standalone ``yazses-tray`` process (like the overlay) that polls the daemon's
    ``status`` RPC and shows a menu-bar / indicator icon whose click-menu lets you pick
    the input microphone, re-calibrate, and start/stop the daemon. On Linux it is a
    PySide6 ``QSystemTrayIcon`` (needs an SNI/AppIndicator host — standard on Ubuntu
    GNOME); on macOS/Windows the existing rumps/pystray backends. Soft no-op where no
    system tray is available.
    """
    enabled: bool = True             # auto-launch the tray with the daemon
    poll_interval_s: float = 1.0     # how often the tray refreshes daemon state


@dataclass
class StagedConfig:
    """Staged dictation — speak, review, then commit (#294).

    Bursts accumulate in a buffer instead of typing straight into the focused app,
    so a mis-transcribed token can be caught *before* it reaches a terminal or a
    source file. OFF by default: an existing install must not change behaviour.

    `spoken_commit` is opt-in on purpose. A spoken commit inside a buffer whose
    purpose is catching mis-recognition can be triggered by the very
    mis-recognition it exists to catch — prose mis-heard as "commit" types early,
    which is the accident staged mode was turned on to prevent. A *missed* commit
    costs one more action and is visible; a premature one has already typed.
    """
    enabled: bool = False
    spoken_commit: bool = False       # also accept "commit that" / "discard that" by voice
    show_in_overlay: bool = True      # show the pending text while you speak
    max_chunks: int = 200             # a runaway buffer is a bug, not a workflow


@dataclass
class ConfidenceConfig:
    """v2.0.0 Wave A — Confidence Ink & Voice Re-pick (ADR-v2-001).

    Surface Whisper's per-word confidence (derived from token log-probabilities) so
    low-confidence words can be marked (overlay) and re-picked by voice instead of
    re-dictated. OFF by default; pure post-processing over the decode output.
    """
    enabled: bool = False
    threshold: float = 0.55           # words at/below this confidence (0..1) are flagged
    mark_in_overlay: bool = True      # show markers via the overlay when available


@dataclass
class ContextConfig:
    """v2.0.0 Wave A — Context-Primed Dictation & Commanding (ADR-v2-004).

    Compose Whisper's initial_prompt from already-consented, transient desktop
    signals (active window title, selection, clipboard, editor LSP symbols) and
    resolve deictic commands against them. OFF by default; content is read at decode
    time and NEVER stored or logged.
    """
    enabled: bool = False
    use_window_title: bool = True
    use_selection: bool = True
    use_clipboard: bool = False       # clipboard is the broadest signal; opt-in separately
    use_lsp: bool = True
    max_terms: int = 48


@dataclass
class RecallConfig:
    """v2.0.0 Wave B — Spoken Recall & Ambient Scratch (ADR-v2-005).

    Query past dictations from the encrypted learning corpus ("what did I say
    about X") and capture spoken notes-to-self. OFF by default; recall reads the
    local corpus only (nothing leaves the machine) and scratch notes are a plain
    local JSONL file.
    """
    enabled: bool = False
    scratch: bool = False             # capture note-to-self phrases to the scratch pad
    max_hits: int = 5                 # how many recall results to return


@dataclass
class AgentConfig:
    """v2.0.0 Wave B — Voice-to-Tool / offline Spoken MCP (ADR-v2-006).

    Speak an intent → a local SLM emits a GBNF-constrained tool call executed via
    MCP against an ``allowlist``, confirming state-mutating tools. OFF by default;
    the SLM + MCP client are heavy and opt-in behind the ``agent`` extra, lazy-
    imported only when enabled.
    """
    enabled: bool = False
    allowlist: list[str] = field(default_factory=list)   # tool names allowed to run
    confirm: str = "writes"           # all | writes | none — confirm before running
    slm_model_path: str = ""          # local planner SLM; empty = disabled


@dataclass
class PilotConfig:
    """v2.0.0 Wave B — AT-SPI Voice Pilot (ADR-v2-007).

    Voice-drive the desktop via the accessibility tree ("click Save", "focus the
    terminal"). Linux-first via pyatspi (opt-in, system packages); reads element
    labels/roles only — never a screenshot. OFF by default.
    """
    enabled: bool = False
    backend: str = "atspi"            # atspi | none
    match_threshold: float = 0.5      # min label-match similarity to act
    confirm_ambiguous: bool = True    # ask when several elements tie


@dataclass
class ActivationConfig:
    """Intent-carrying activation sources (#137) and their confirmation gate (#138).

    A source that decodes *meaning* — silent speech, EMG word decoding, a BCI —
    emits a label plus a confidence instead of a bare onset. Because the best
    reported non-invasive accuracy is 96–97% on 10–30 words (Tang,
    arXiv:2504.13921; Kurotaki, doi:10.1002/aisy.70440), roughly one command in
    thirty is wrong, so an intent is gated on confidence × consequence before it
    executes. See ``activation/confirm.py`` for why these defaults.

    OFF by default: with no intent-carrying source configured this changes
    nothing, and ``EMGBackend`` (onset/offset only) is unaffected either way.
    """
    enabled: bool = False
    confirm_threshold: float = 0.90   # below this, a reversible action confirms
    reject_floor: float = 0.50        # below this, the intent is dropped outright


@dataclass
class ModalityConfig:
    """v2.0.0 Wave C — sEMG Command Layer & Modality Role Router (ADR-v2-011).

    Assign each input modality its fastest role (voice→dictation, EMG→command,
    gaze→targeting, keyboard→activate) via a preset + priority order. EXPERIMENTAL,
    off by default; the router is pure policy — hardware intakes stay opt-in.
    """
    enabled: bool = False
    preset: str = "balanced"          # balanced | hands-free | voice-only
    priority: list[str] = field(
        default_factory=lambda: ["voice", "emg", "gaze", "keyboard"]
    )


@dataclass
class ContinuumConfig:
    """v2.0.0 Wave C — Accessibility Continuum (ADR-v2-012).

    Opt-in capabilities for effortful/quiet speech: Whisper/Low-Effort Mode (scale
    the VAD threshold down for quiet speech), Semantic Capture (meaning-not-words
    via the LLM-cleanup path, dormant), and adaptive pacing. OFF by default.
    """
    enabled: bool = False
    whisper_mode: bool = False
    whisper_threshold_factor: float = 0.4   # VAD threshold multiplier for quiet speech
    semantic_capture: bool = False          # reuse LLM cleanup for meaning capture


@dataclass
class BridgeConfig:
    """v2.0.0 Wave C — Glasses↔Desktop Dictation Bridge (ADR-v2-013).

    A companion device (phone-as-mic; glasses later) streams audio to the desktop,
    which runs STT + injection. Reuses the remote/ transport; pairs over a shared
    token. EXPERIMENTAL, off by default; nothing leaves the paired local link.
    """
    enabled: bool = False
    listen_port: int = 9876
    pair_token: str = ""              # shared secret the companion must present
    device_name: str = ""            # last paired companion (informational)


@dataclass
class TranslateConfig:
    """v2.1 Wave D — Real-time offline speech translation (ADR-v2-014).

    Dictate in one language, inject another. ``whisper`` backend does X→English via
    Whisper's built-in translate task (zero new deps); ``seamless`` (opt-in, behind
    the translate extra) does N-to-M. OFF by default.
    """
    enabled: bool = False
    target: str = "en"               # target language (whisper backend: English only)
    backend: str = "whisper"         # whisper (X→English) | seamless (opt-in)


@dataclass
class AffectConfig:
    """v2.1 Wave D — Emotion/tone-aware formatting (ADR-v2-017).

    Reflect vocal tone as light punctuation (``!``/``?``). ``conservative`` acts only
    on clear excitement/question; ``expressive`` widens the set. The SER model is opt-
    in behind the ``affect`` extra; absent → neutral label → no-op. OFF by default.
    """
    enabled: bool = False
    mode: str = "conservative"       # conservative | expressive
    min_confidence: float = 0.6


@dataclass
class DenoiseConfig:
    """v2.1 Wave D — Real-time noise-suppression front-end (ADR-v2-015).

    Denoise/dereverb before STT so noisy rooms and quiet speech work. Identity
    passthrough when off. The installable backend is ``spectral`` (the default),
    which the ``denoise`` extra supplies as ``noisereduce``; ``deepfilternet`` is
    accepted as a name but nothing can supply it (#69). OFF by default.
    """
    enabled: bool = False
    # `spectral` is the only backend that can be installed: deepfilternet
    # pins numpy<2.0 against this project's numpy>=2.4.6 (#69), so it is
    # kept as a name the config accepts but nothing can supply.
    backend: str = "spectral"   # spectral | deepfilternet | none
    strength: float = 1.0            # graded suppression (higher = more aggressive)


@dataclass
class PredictConfig:
    """v2.1 Wave D — Predictive dictation completion (ADR-v2-016).

    A tiny on-device LLM proposes the rest of a phrase; accept by voice. The
    generator (llama.cpp) is opt-in behind the ``predict`` extra and runs in a
    background thread. OFF by default.
    """
    enabled: bool = False
    model_path: str = ""             # local planner/completion GGUF; empty = disabled
    max_tokens: int = 12


@dataclass
class VoiceguardConfig:
    """v2.1 Wave D — Voice-biometric gate + anti-spoof (ADR-v2-018).

    Inject only when the live speaker matches the enrolled voiceprint and the audio
    isn't synthetic/replayed. ECAPA match + anti-spoof models opt-in behind the
    ``voiceguard`` extra. ``fail_open`` admits when a score is unavailable (avoids
    lockout). EXPERIMENTAL, OFF by default.
    """
    enabled: bool = False
    match_threshold: float = 0.5     # min cosine similarity to the enrolled voiceprint
    spoof_threshold: float = 0.5     # max spoof probability allowed
    fail_open: bool = True           # admit when a score is unavailable


@dataclass
class ScribeConfig:
    """v2.1 Wave D — Ambient Meeting Scribe (ADR-v2-019).

    On-device "who said what" transcript. Streaming diarization backend opt-in behind
    the ``scribe`` extra; the enrolled user is labelled "You". OFF by default.
    """
    enabled: bool = False
    backend: str = "sortformer"      # sortformer | none
    max_speakers: int = 6


@dataclass
class RagConfig:
    """v2.1 Wave D — Voice-grounded RAG over personal notes (ADR-v2-020).

    Ask by voice, answer cited from local docs. Embedding model + sqlite-vec index +
    answer LLM opt-in behind the ``rag`` extra. OFF by default.
    """
    enabled: bool = False
    top_k: int = 4
    min_score: float = 0.2
    embed_model: str = "embeddinggemma"   # embedding backend (lazy)
    store_path: str = ""                  # sqlite-vec index; empty = disabled


@dataclass
class CodecConfig:
    """v2.1 Wave D — Neural-codec ultra-low-latency streaming STT (ADR-v2-022).

    Route decoding to a streaming-native codec engine (Kyutai/Mimi) when enabled, else
    keep faster-whisper. Engine opt-in behind the ``codec`` extra. OFF by default.
    """
    enabled: bool = False
    backend: str = "kyutai"          # kyutai (Mimi) | none
    max_delay_ms: int = 500


@dataclass
class HallucinationConfig:
    """v2.1 Wave E — Hallucination Guard (ADR-v2-025).

    Drop fabricated transcripts Whisper emits on silence/noise (ghost outro phrases,
    repetition loops, and — when available — low-confidence segment signals). Pure text
    checks wired into the daemon; conservative. OFF by default.
    """
    enabled: bool = False
    drop_ghost_phrases: bool = True
    drop_loops: bool = True
    no_speech_threshold: float = 0.6
    logprob_threshold: float = -1.0
    compression_ratio_threshold: float = 2.4


@dataclass
class SnippetsConfig:
    """v2.1 Wave E — Voice Snippets spoken text expander (ADR-v2-026).

    ``entries`` maps a spoken trigger phrase to a template string. OFF by default.
    """
    enabled: bool = False
    entries: dict = field(default_factory=dict)


@dataclass
class PhoneticConfig:
    """v2.1 Wave E — Phonetic Corrector (ADR-v2-027).

    Fix mis-heard proper nouns against the personal vocabulary in sound space. A stronger
    G2P backend is opt-in behind the ``phonetic`` extra. OFF by default.
    """
    enabled: bool = False
    max_distance: float = 0.34       # normalized phonetic-key distance to accept a fix


@dataclass
class AutoStopConfig:
    """v2.1 Wave E — hands-free tap-and-speak auto-stop (ADR-v2-029).

    Tap to start; auto-stop on trailing silence or a hard duration cap. The Smart Turn v2
    semantic model is opt-in behind the ``turn`` extra. OFF by default.
    """
    enabled: bool = False
    mode: str = "silence"            # silence | semantic
    silence_timeout_ms: int = 800
    max_duration_ms: int = 30000


@dataclass
class MousegridConfig:
    """v2.1 Wave E — Voice Mouse Grid pointer control (ADR-v2-030). OFF by default."""
    enabled: bool = False
    cols: int = 3
    rows: int = 3


@dataclass
class CodeConfig:
    """v2.1 Wave E — Spoken Code Mode (ADR-v2-031). OFF by default."""
    enabled: bool = False


@dataclass
class MathConfig:
    """v2.1 Wave E — Spoken Math → LaTeX (ADR-v2-032). OFF by default."""
    enabled: bool = False


@dataclass
class WakewordConfig:
    """v2.1 Wave E — Wake-Word Activation (ADR-v2-033). Always-listening → EXPERIMENTAL,
    OFF by default; the spotter model is opt-in behind the ``wakeword`` extra."""
    enabled: bool = False
    keyword: str = "hey yaz"
    threshold: float = 0.5
    cooldown_ms: int = 2000


@dataclass
class VoicehealthConfig:
    """v2.1 Wave E — Vocal-Strain Guard (ADR-v2-034). Advisory only. OFF by default."""
    enabled: bool = False
    threshold: float = 0.6           # mean strain over the window to advise a break
    min_samples: int = 20


@dataclass
class CoachConfig:
    """v2.2 Wave F — Speaking Coach private self-analytics (ADR-v2-035). OFF by default."""
    enabled: bool = False


@dataclass
class SmartpasteConfig:
    """v2.2 Wave F — Smart-Paste format adaptation (ADR-v2-036). OFF by default."""
    enabled: bool = False


@dataclass
class ScrubConfig:
    """v2.2 Wave F — Audio-Anchored Scrubbing (ADR-v2-037). OFF by default."""
    enabled: bool = False


@dataclass
class ReflowConfig:
    """v2.2 Wave F — Dictation Reflow / Voice Outliner (ADR-v2-038). OFF by default."""
    enabled: bool = False


@dataclass
class AcousticProfilesConfig:
    """v2.2 Wave F — Acoustic Context Profiles (ADR-v2-039). OFF by default."""
    enabled: bool = False
    min_stable: int = 3              # consecutive scene observations before switching


@dataclass
class SentimentConfig:
    """v2.2 Wave F — Mood Ledger speech-sentiment journal (ADR-v2-040). OFF by default."""
    enabled: bool = False


@dataclass
class PronunciationConfig:
    """v2.2 Wave F — Pronunciation Feedback L2 practice mode (ADR-v2-041). OFF by default."""
    enabled: bool = False
    good_threshold: float = 0.7      # GOP >= this is "good"
    poor_threshold: float = 0.4      # GOP < this is "poor" (needs practice)


@dataclass
class ItnConfig:
    """v2.3 Wave G — Entity Inverse Text Normalization (ADR-v2-045). OFF by default."""
    enabled: bool = False


@dataclass
class RedactionConfig:
    """v2.3 Wave G — Redaction Ink: mask secrets at injection time (ADR-v2-046). OFF by default."""
    enabled: bool = False
    mode: str = "mask"               # mask | hold


@dataclass
class FieldawareConfig:
    """v2.3 Wave G — Field-Aware Dictation (ADR-v2-047). OFF by default."""
    enabled: bool = False


@dataclass
class ComposeConfig:
    """v2.3 Wave G — Compose-in-Target-Language (ADR-v2-049). OFF by default."""
    enabled: bool = False
    source: str = ""                 # your spoken language (empty = autodetect)
    target: str = "en"               # language to inject


@dataclass
class GecConfig:
    """v2.3 Wave G — Grammar Repair, minimal-edit GEC (ADR-v2-050). OFF by default."""
    enabled: bool = False


@dataclass
class ScreengroundedConfig:
    """v2.3 Wave G — Screen-Grounded Dictation (ADR-v2-051). OFF by default."""
    enabled: bool = False
    max_terms: int = 32


@dataclass
class HeadpointerConfig:
    """v2.3 Wave G — Head-Pointer hands-free cursor (ADR-v2-052). OFF by default."""
    enabled: bool = False


@dataclass
class LipreadConfig:
    """v2.3 Wave G — Silent Lip-Reading Input / VSR (ADR-v2-053). OFF by default."""
    enabled: bool = False
    mouth_threshold: float = 0.35


@dataclass
class SignConfig:
    """v2.3 Wave G — Sign-Language Input / SLR (ADR-v2-054). OFF by default."""
    enabled: bool = False
    pause_frames: int = 8


@dataclass
class ConvertConfig:
    """v2.4 Wave H — Voice Unit Conversion (ADR-v2-056). OFF by default."""
    enabled: bool = False


@dataclass
class TemporalConfig:
    """v2.4 Wave H — Spoken Temporal Normalizer (ADR-v2-057). OFF by default."""
    enabled: bool = False


@dataclass
class SpreadsheetConfig:
    """v2.4 Wave H — Spoken Spreadsheet / Table Mode (ADR-v2-059). OFF by default."""
    enabled: bool = False


@dataclass
class CliphistoryConfig:
    """v2.4 Wave H — Clipboard-History by Voice (ADR-v2-060). OFF by default."""
    enabled: bool = False
    capacity: int = 20


@dataclass
class AudioguardConfig:
    """v2.4 Wave H — Ambient Audio-Event Guard (ADR-v2-061). OFF by default."""
    enabled: bool = False
    cooldown_frames: int = 30


@dataclass
class CondenseConfig:
    """v2.4 Wave H — On-Device Condense (ADR-v2-062). OFF by default."""
    enabled: bool = False
    max_sentences: int = 2


@dataclass
class SlotfillConfig:
    """v2.4 Wave H — Structured Form / Slot-Filling Dictation (ADR-v2-063). OFF by default."""
    enabled: bool = False


@dataclass
class CmdspotterConfig:
    """v2.4 Wave H — Few-Shot Personal Command Spotter (ADR-v2-064). OFF by default."""
    enabled: bool = False
    threshold: float = 0.75


@dataclass
class CmdsafetyConfig:
    """Command Safety Gate — hold a dangerous dictated command pending a spoken confirm
    (ADR-v2-065). OFF by default.

    **Why this does not gate on "am I in a terminal".** The feature was designed as a
    *terminal* gate, and the obvious implementation asks the focus detector whether a
    terminal is focused. That answer is unavailable in exactly the sessions where the
    guard matters most: `TargetDetector` needs AT-SPI or X11, so on Wayland without
    AT-SPI the app class is `""`. A guard that silently stops protecting on a whole
    display server is worse than no guard, because the user believes it is on.

    So the gate reads the *command text* and nothing else. That is defensible because
    the patterns in `cmdsafety/classify.py` are highly specific -- `rm -rf`, `mkfs`,
    `dd of=`, a fork bomb, `curl | sh`. Prose that matches one of them is vanishingly
    rare, and when it happens the cost is one spoken "confirm". The reverse mistake --
    letting a mis-heard `rm -rf /` through because the display server hid the window
    class -- is unrecoverable. Asymmetric costs, so the gate fails safe.
    """
    enabled: bool = False
    # Phrases that release a held command / discard it. Empty falls back to the
    # defaults in `cmdsafety/spoken.py` rather than disabling the words, because a
    # held command with no release phrase cannot be run at all.
    confirm_words: list[str] = field(default_factory=list)
    cancel_words: list[str] = field(default_factory=list)


@dataclass
class SpokenregexConfig:
    """v2.5 Wave I — Spoken Regex Builder (ADR-v2-066). OFF by default."""
    enabled: bool = False


@dataclass
class MarkupConfig:
    """v2.5 Wave I — Structured-Markup Dictation (ADR-v2-067). OFF by default."""
    enabled: bool = False
    flavor: str = "markdown"


@dataclass
class FindreplaceConfig:
    """v2.5 Wave I — Document-Wide Find-and-Replace (ADR-v2-068). OFF by default."""
    enabled: bool = False


@dataclass
class HotwordsConfig:
    """v2.5 Wave I — Hard Contextual Biasing (ADR-v2-069). OFF by default."""
    enabled: bool = False
    boost: float = 2.0


@dataclass
class WindowctlConfig:
    """v2.5 Wave I — Voice Window/Workspace Management (ADR-v2-070). OFF by default."""
    enabled: bool = False


@dataclass
class CiteConfig:
    """v2.5 Wave I — Citation-by-Voice (ADR-v2-071). OFF by default."""
    enabled: bool = False
    bib_path: str = ""
    style: str = "latex"


@dataclass
class LangrouteConfig:
    """v2.5 Wave I — Per-Language Auto Model Switching (ADR-v2-072). OFF by default."""
    enabled: bool = False
    min_confidence: float = 0.5


@dataclass
class LatencyConfig:
    """v2.5 Wave I — Adaptive Latency Governor (ADR-v2-073). OFF by default."""
    enabled: bool = False
    high_load: float = 85.0
    low_load: float = 40.0


@dataclass
class DiarizeConfig:
    """v2.5 Wave I — Diarized Conversation Capture (ADR-v2-074). OFF by default."""
    enabled: bool = False


@dataclass
class SpellingConfig:
    """v2.6 Wave J — Phonetic Spelling Mode (ADR-v2-075). OFF by default."""
    enabled: bool = False


@dataclass
class GitvoiceConfig:
    """v2.6 Wave J — Voice Git Choreographer (ADR-v2-076). OFF by default."""
    enabled: bool = False


@dataclass
class ReaskConfig:
    """v2.6 Wave J — Confidence-Gated Re-Ask (ADR-v2-077). OFF by default."""
    enabled: bool = False
    threshold: float = -1.0


@dataclass
class VerbatimConfig:
    """v2.6 Wave J — Verbatim⇄Autoformat Toggle (ADR-v2-078). OFF by default."""
    enabled: bool = False


@dataclass
class CorrdictConfig:
    """v2.6 Wave J — Self-Learning Correction Dictionary (ADR-v2-079). OFF by default."""
    enabled: bool = False
    min_support: int = 3


@dataclass
class FileopenConfig:
    """v2.6 Wave J — Voice Fuzzy File Open (ADR-v2-080). OFF by default."""
    enabled: bool = False
    threshold: float = 0.4


@dataclass
class JumpConfig:
    """v2.6 Wave J — Voice Jump-to-Symbol (ADR-v2-081). OFF by default."""
    enabled: bool = False


@dataclass
class ShellpipeConfig:
    """v2.6 Wave J — Spoken Shell Pipeline Builder (ADR-v2-082). OFF by default."""
    enabled: bool = False


@dataclass
class McpConfig:
    """Being callable by another agent over MCP (ADR-020). Off by default.

    Two tools and only two. `transcribe` reads a file the caller already has and
    returns text — it touches no microphone and no window, so it needs no
    permission beyond running the server at all.

    `ask_human` is the one with restraints, because an agent that can speak to you
    at will is an agent that can interrupt you at will. ADR-020 §4 makes the
    interrupt budget a condition of the feature existing rather than a setting:
    `ask_human_per_hour = 0` keeps the tool listed and always refusing, which is
    different from the tool being absent — the caller learns *why*.
    """

    #: Offer `ask_human` at all. `yazses mcp-server` always offers `transcribe`.
    ask_human: bool = False
    #: Spoken questions allowed per rolling hour, shared across every caller — it
    #: protects the person, not each agent's fair share. 0 = never.
    ask_human_per_hour: int = 3


@dataclass
class RecimportConfig:
    """Recording Import — offline batch file transcription with speaker attribution.

    ADR-v2-083 (batch transcription) + ADR-v2-125 (diarization + naming). OFF by default.
    Diarization is transient; speaker naming is opt-in, consent-gated, and on-device.
    """
    enabled: bool = False
    diarize: bool = False              # attribute speakers; false = plain transcript
    # sherpa (default, ONNX/no torch) | pyannote (accuracy; needs the
    # `diarization-pyannote` extra + a one-time gated HF model download) | none
    backend: str = "sherpa"
    # NOT an upper bound on the shipped `sherpa` backend, despite the name: it becomes
    # FastClusteringConfig(num_clusters=N), which is an EXACT cluster count. Measured
    # against sherpa-onnx 1.13.5 on two well-separated speakers: num_clusters=2 gave
    # 2 clusters, 4 gave 4, and 6 gave 6 -- it splits real speakers to reach the
    # number. So a generous "at most 6" invents six people. 0 auto-detects, which is
    # why it is the default. Only the (unshipped) pyannote backend treats it as a cap.
    max_speakers: int = 0              # 0 = auto-detect; otherwise an EXACT count
    min_speakers: int = 0
    cluster_threshold: float = 0.5     # sherpa fast-clustering threshold (auto-count mode)
    output_format: str = "txt"         # txt | md | srt | vtt | json
    model: str = ""                    # "" => inherit the [stt] model
    language: str = "en"               # "en" fast path, or "translate" (X→English)
    batched: bool = True               # BatchedInferencePipeline on long files
    name_from_voiceprints: bool = True # match enrolled voiceprints (needs enrollment)
    min_speaker_seconds: float = 3.0   # min aggregated cluster speech to attempt naming
    name_threshold: float = 0.5        # reject-biased cosine similarity to accept a name
    model_dir: str = ""                # "" => <data_dir>/diarization


@dataclass
class MeetingConfig:
    """Meeting Mode — hands-free continuous capture + hybrid speaker diarization.

    ADR-v2-127 (live meeting mode) + ADR-v2-128 (on-device minutes). OFF by default.
    Transcript streams live for the status view; the *authoritative* speaker-attributed
    transcript is produced by a batch diarization post-pass over the whole recording at
    stop (reusing the ADR-v2-125 ``recimport`` cores). On-device only (ADR-011): audio is
    a local temp file, kept only for the post-pass and deleted unless ``retain_audio``.
    The diarization/naming fields mirror ``RecimportConfig`` so the finalize step can pass
    this config straight to ``recimport.pipeline.transcribe_file``.
    """
    enabled: bool = False
    output_dir: str = ""               # "" => <data_dir>/meetings
    retain_audio: bool = False         # keep audio.wav after finalize (else deleted)
    live_transcript: bool = True       # stream a rolling transcript for `meeting status`
    # --- diarization (batch post-pass; RecimportConfig-compatible) ---
    diarize: bool = True               # attribute speakers at stop
    # sherpa (default, ONNX/no torch) | pyannote (accuracy; needs the
    # `diarization-pyannote` extra + a one-time gated HF model download) | none
    backend: str = "sherpa"
    # Exact cluster count on the shipped backend, not a cap -- see RecimportConfig.
    max_speakers: int = 0              # 0 = auto-detect; otherwise an EXACT count
    min_speakers: int = 0
    cluster_threshold: float = 0.5     # sherpa fast-clustering threshold (auto-count mode)
    model: str = ""                    # "" => inherit the [stt] model
    language: str = "en"               # "en" fast path, or "translate" (X→English)
    vad_backend: str = "calibrated"    # calibrated | silero (utterance segmentation)
    silero_threshold: float = 0.5      # silero speech-probability gate (needs the `silero` extra)
    name_from_voiceprints: bool = True # match enrolled voiceprints (needs enrollment)
    participants_dir: str = ""         # "" => <data_dir>/participants (enrolled speakers)
    min_speaker_seconds: float = 3.0   # min aggregated cluster speech to attempt naming
    name_threshold: float = 0.5        # reject-biased cosine similarity to accept a name
    model_dir: str = ""                # "" => <data_dir>/diarization
    output_format: str = "md"          # md | txt | srt | vtt | json
    max_minutes: int = 180             # auto-stop safety cap (0 = unlimited)
    # --- minutes / notes (ADR-v2-128; opt-in, dormant unless a model is set) ---
    notes: bool = False                # generate notes.md at stop (needs the `notes` extra)
    notes_model: str = ""              # path to a local GGUF; "" = dormant
    # Recommended GGUF (Q4_K_M, CPU-fit): Phi-4-mini-instruct or Qwen2.5-3B-Instruct.
    notes_grammar: bool = True         # constrain minutes JSON with a GBNF grammar (falls back to tolerant parse)
    notes_window_turns: int = 40       # map-reduce window size (utterance turns)
    notes_max_tokens: int = 1024       # per-window generation cap


@dataclass
class CrowdproofConfig:
    """v2.6 Wave J — Crowd-Proof Dictation (ADR-v2-084). OFF by default."""
    enabled: bool = False
    threshold: float = 0.5


@dataclass
class ChordsConfig:
    """v2.7 Wave K — Chorded Shortcut Synthesis (ADR-v2-085). OFF by default."""
    enabled: bool = False


@dataclass
class ComputeConfig:
    """v2.7 Wave K — Inline Compute (ADR-v2-086). OFF by default."""
    enabled: bool = False


@dataclass
class CasetransformConfig:
    """v2.7 Wave K — Voice Case & Identifier Transform (ADR-v2-087). OFF by default."""
    enabled: bool = False


@dataclass
class AutopairConfig:
    """v2.7 Wave K — Auto-Pairing & Wrap-Selection (ADR-v2-088). OFF by default."""
    enabled: bool = False


@dataclass
class TimelineConfig:
    """v2.7 Wave K — Voice Undo/Redo Timeline (ADR-v2-089). OFF by default."""
    enabled: bool = False


@dataclass
class BookmarksConfig:
    """v2.7 Wave K — Session Bookmarks & Resume (ADR-v2-090). OFF by default."""
    enabled: bool = False


@dataclass
class TablecsvConfig:
    """v2.7 Wave K — Spoken Table→CSV Data Entry (ADR-v2-091). OFF by default."""
    enabled: bool = False
    delimiter: str = ","


@dataclass
class WordgoalConfig:
    """v2.7 Wave K — Word-Count & Goal Tracker (ADR-v2-092). OFF by default."""
    enabled: bool = False
    goal: int = 0


@dataclass
class VoicetimerConfig:
    """v2.7 Wave K — Local Voice Timer & Break Reminder (ADR-v2-093). OFF by default."""
    enabled: bool = False


@dataclass
class FocusprofileConfig:
    """v2.7 Wave K — Focus-Class Auto-Profile Switching (ADR-v2-094). OFF by default."""
    enabled: bool = False


@dataclass
class VocaljoystickConfig:
    """v2.8 Wave L — Vocal Joystick continuous analog control (ADR-v2-095). OFF by default."""
    enabled: bool = False
    max_speed: float = 20.0
    click_pitch: float = 250.0


@dataclass
class EarconConfig:
    """v2.8 Wave L — Earcon Feedback Language (ADR-v2-096). OFF by default."""
    enabled: bool = False


@dataclass
class SpatialvadConfig:
    """v2.8 Wave L — Beam-Steered Spatial VAD (ADR-v2-098). OFF by default."""
    enabled: bool = False
    target_angle: float = 0.0
    tolerance_deg: float = 35.0
    mic_distance_m: float = 0.14


@dataclass
class ProsodypunctConfig:
    """v2.8 Wave L — Prosodic Auto-Punctuation (ADR-v2-104). OFF by default."""
    enabled: bool = False
    sentence_pause_ms: float = 700.0
    comma_pause_ms: float = 250.0


@dataclass
class HesitationConfig:
    """v2.8 Wave L — Hesitation-Hold Endpointing (ADR-v2-101). OFF by default."""
    enabled: bool = False
    commit_ms: float = 800.0
    hold_extra_ms: float = 1200.0


@dataclass
class ContourConfig:
    """v2.8 Wave L — Pitch-Contour Vocal Gestures (ADR-v2-103). OFF by default."""
    enabled: bool = False


@dataclass
class BreathConfig:
    """v2.8 Wave L — Breath-Paced Dictation (ADR-v2-099). OFF by default."""
    enabled: bool = False
    min_gap_s: float = 1.0
    onset_threshold: float = 0.6


@dataclass
class WhispermodeConfig:
    """v2.8 Wave L — Whisper-Aware Mode (ADR-v2-100). OFF by default.

    With ``command_channel`` (the sotto-voce channel, DualVoice pattern): a
    *whispered* burst is parsed as a command and never typed literally, while
    normally-voiced speech dictates — a hands-free, socially-silent mode switch
    on a plain microphone.
    """
    enabled: bool = False
    voicing_max: float = 0.3
    tilt_min: float = -1.0
    gain_db: float = 6.0
    vad_scale: float = 0.5
    command_channel: bool = True


@dataclass
class MouthswitchConfig:
    """v2.8 Wave L — Mouth-Sound Switch Access (ADR-v2-097). OFF by default."""
    enabled: bool = False
    dwell_s: float = 1.2


@dataclass
class InvoluntaryConfig:
    """v2.8 Wave L — Involuntary-Vocalization Auto-Excision (ADR-v2-102). OFF by default."""
    enabled: bool = False


@dataclass
class MorsevoxConfig:
    """v2.9 Wave M — Vocal Morse two-tone AAC (ADR-v2-105). OFF by default."""
    enabled: bool = False
    dot_max_ms: float = 200.0
    letter_gap_ms: float = 600.0
    word_gap_ms: float = 1400.0


@dataclass
class CheckdigitConfig:
    """Checksum-Validated Data Entry (ADR-v2-106, wired by ADR-021). OFF by default.

    A mis-heard digit in a card number, IBAN or ISBN is the cheapest error to catch and
    one of the most expensive to miss: nothing downstream will notice, and the failure
    surfaces as a declined payment or a wrong record rather than as a typo.

    **It fires only on arithmetic, never on a guess.** The utterance must look like a
    checkable number *and* fail its check digit. Digits that pass are typed with no
    comment, and anything that is not a plausible number is not examined at all — which
    is what keeps a guard like this from training the user to dismiss it (ADR-021: judge
    these on how rarely they fire, not on how much they catch).
    """
    enabled: bool = False
    #: Which checksums to test, in order. `luhn` covers payment cards and many national
    #: IDs; `isbn13`/`isbn10` books; `verhoeff` several government schemes (e.g. Aadhaar).
    schemes: list[str] = field(default_factory=lambda: ["luhn", "isbn13", "isbn10"])
    #: Shortest run of digits worth checking. Below this, false positives dominate —
    #: a 4-digit year or a house number is not a card number, and Luhn will happily
    #: reject it.
    min_digits: int = 12
    #: Offer the single-digit correction when exactly one candidate passes. More than one
    #: candidate means the suggestion would be a guess between them, so none is offered.
    suggest_fix: bool = True


@dataclass
class SembrConfig:
    """v2.9 Wave M — Semantic Line Breaks (ADR-v2-111). OFF by default."""
    enabled: bool = False
    max_len: int = 0


@dataclass
class AcronymsConfig:
    """v2.9 Wave M — Acronym/Glossary First-Use Manager (ADR-v2-114). OFF by default."""
    enabled: bool = False


@dataclass
class StyleguardConfig:
    """v2.9 Wave M — Local Style-Consistency Enforcer (ADR-v2-109). OFF by default."""
    enabled: bool = False
    path: str = "style-rules.toml"    # relative to config dir, or absolute


@dataclass
class SuggestmodeConfig:
    """v2.9 Wave M — Suggestion-Mode Dictation (ADR-v2-113). OFF by default."""
    enabled: bool = False


@dataclass
class ScreenplayConfig:
    """v2.9 Wave M — Screenplay & Dialogue Auto-Format (ADR-v2-110). OFF by default."""
    enabled: bool = False


@dataclass
class SrscapConfig:
    """v2.9 Wave M — Spoken Spaced-Repetition Capture (ADR-v2-112). OFF by default."""
    enabled: bool = False


@dataclass
class DiagramvoxConfig:
    """v2.9 Wave M — Diagrams-as-Code by Voice (ADR-v2-107). OFF by default."""
    enabled: bool = False
    flavor: str = "mermaid"


@dataclass
class ProofbackConfig:
    """v2.9 Wave M — Interruptible Read-Back Proofreading (ADR-v2-108). OFF by default."""
    enabled: bool = False


@dataclass
class HatselectConfig:
    """v2.10 Wave N — HatSelect spoken structural token addressing (ADR-v2-115). OFF by default."""
    enabled: bool = False


@dataclass
class TranslitConfig:
    """v2.10 Wave N — Romanized→Native-Script Transliteration (ADR-v2-116). OFF by default."""
    enabled: bool = False
    scheme: str = "finglish"


@dataclass
class BrailleoutConfig:
    """v2.10 Wave N — BrailleOut Unicode Braille output (ADR-v2-117). OFF by default."""
    enabled: bool = False
    grade: int = 2


@dataclass
class OutlineConfig:
    """v2.10 Wave N — Spoken Outline structuring (ADR-v2-124). OFF by default."""
    enabled: bool = False
    format: str = "markdown"


@dataclass
class DiacritizeConfig:
    """v2.10 Wave N — Diacritics restoration (ADR-v2-122). OFF by default."""
    enabled: bool = False


@dataclass
class SafeglyphConfig:
    """v2.10 Wave N — SafeGlyph confusable-hazard detection (ADR-v2-123). OFF by default."""
    enabled: bool = False


@dataclass
class WordfindConfig:
    """v2.10 Wave N — WordFind offline reverse dictionary (ADR-v2-118). OFF by default."""
    enabled: bool = False
    max_candidates: int = 5


@dataclass
class LoadguardConfig:
    """v2.10 Wave N — LoadGuard cognitive-load guardrails (ADR-v2-121). OFF by default."""
    enabled: bool = False
    threshold: float = 0.7


@dataclass
class EchoConfig:
    """v2.10 Wave N — Echo own-audio replay (ADR-v2-119). OFF by default."""
    enabled: bool = False


@dataclass
class SrpaceConfig:
    """v2.10 Wave N — SRPace screen-reader-paced injection (ADR-v2-120). OFF by default."""
    enabled: bool = False
    wpm: float = 180.0


@dataclass
class ProfilesConfig:
    """v2.10 Wave N — Per-app tone & formatting profiles (ADR-v2-100). OFF by default."""
    app: dict[str, str] = field(default_factory=dict)


@dataclass
class GestureConfig:
    """v2.2 Wave F — Gesture Chords (ADR-v2-043). OFF by default."""
    enabled: bool = False


@dataclass
class InterpretConfig:
    """v2.2 Wave F — Two-Way Live Interpreter (ADR-v2-044). OFF by default."""
    enabled: bool = False
    pair: str = "en-es"              # language pair to interpret between


@dataclass
class Config:
    stt: SttConfig = field(default_factory=SttConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    general: GeneralConfig = field(default_factory=GeneralConfig)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    filters: FiltersConfig = field(default_factory=FiltersConfig)
    accessibility: AccessibilityConfig = field(default_factory=AccessibilityConfig)
    commands: CommandsConfig = field(default_factory=CommandsConfig)
    macros: MacrosConfig = field(default_factory=MacrosConfig)
    revise: ReviseConfig = field(default_factory=ReviseConfig)
    punch_in: PunchInConfig = field(default_factory=PunchInConfig)
    endpoint: EndpointConfig = field(default_factory=EndpointConfig)
    prosody: ProsodyConfig = field(default_factory=ProsodyConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    emg: EmgConfig = field(default_factory=EmgConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    tray: TrayConfig = field(default_factory=TrayConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    voiceprint: VoiceprintConfig = field(default_factory=VoiceprintConfig)
    gaze: GazeConfig = field(default_factory=GazeConfig)
    cocktail: CocktailConfig = field(default_factory=CocktailConfig)
    personalize: PersonalizeConfig = field(default_factory=PersonalizeConfig)
    polyglot: PolyglotConfig = field(default_factory=PolyglotConfig)
    # v2.0.0 Wave A (Voice-First Interaction Layer)
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    staged: StagedConfig = field(default_factory=StagedConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    recall: RecallConfig = field(default_factory=RecallConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    pilot: PilotConfig = field(default_factory=PilotConfig)
    modality: ModalityConfig = field(default_factory=ModalityConfig)
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    continuum: ContinuumConfig = field(default_factory=ContinuumConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    translate: TranslateConfig = field(default_factory=TranslateConfig)
    affect: AffectConfig = field(default_factory=AffectConfig)
    denoise: DenoiseConfig = field(default_factory=DenoiseConfig)
    predict: PredictConfig = field(default_factory=PredictConfig)
    voiceguard: VoiceguardConfig = field(default_factory=VoiceguardConfig)
    scribe: ScribeConfig = field(default_factory=ScribeConfig)
    rag: RagConfig = field(default_factory=RagConfig)
    codec: CodecConfig = field(default_factory=CodecConfig)
    hallucination: HallucinationConfig = field(default_factory=HallucinationConfig)
    snippets: SnippetsConfig = field(default_factory=SnippetsConfig)
    phonetic: PhoneticConfig = field(default_factory=PhoneticConfig)
    autostop: AutoStopConfig = field(default_factory=AutoStopConfig)
    mousegrid: MousegridConfig = field(default_factory=MousegridConfig)
    code: CodeConfig = field(default_factory=CodeConfig)
    math: MathConfig = field(default_factory=MathConfig)
    wakeword: WakewordConfig = field(default_factory=WakewordConfig)
    voicehealth: VoicehealthConfig = field(default_factory=VoicehealthConfig)
    coach: CoachConfig = field(default_factory=CoachConfig)
    smartpaste: SmartpasteConfig = field(default_factory=SmartpasteConfig)
    scrub: ScrubConfig = field(default_factory=ScrubConfig)
    reflow: ReflowConfig = field(default_factory=ReflowConfig)
    acoustic_profiles: AcousticProfilesConfig = field(default_factory=AcousticProfilesConfig)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
    pronunciation: PronunciationConfig = field(default_factory=PronunciationConfig)
    gesture: GestureConfig = field(default_factory=GestureConfig)
    interpret: InterpretConfig = field(default_factory=InterpretConfig)
    itn: ItnConfig = field(default_factory=ItnConfig)
    redaction: RedactionConfig = field(default_factory=RedactionConfig)
    fieldaware: FieldawareConfig = field(default_factory=FieldawareConfig)
    compose: ComposeConfig = field(default_factory=ComposeConfig)
    gec: GecConfig = field(default_factory=GecConfig)
    screengrounded: ScreengroundedConfig = field(default_factory=ScreengroundedConfig)
    headpointer: HeadpointerConfig = field(default_factory=HeadpointerConfig)
    lipread: LipreadConfig = field(default_factory=LipreadConfig)
    sign: SignConfig = field(default_factory=SignConfig)
    convert: ConvertConfig = field(default_factory=ConvertConfig)
    temporal: TemporalConfig = field(default_factory=TemporalConfig)
    spreadsheet: SpreadsheetConfig = field(default_factory=SpreadsheetConfig)
    cliphistory: CliphistoryConfig = field(default_factory=CliphistoryConfig)
    audioguard: AudioguardConfig = field(default_factory=AudioguardConfig)
    condense: CondenseConfig = field(default_factory=CondenseConfig)
    slotfill: SlotfillConfig = field(default_factory=SlotfillConfig)
    cmdspotter: CmdspotterConfig = field(default_factory=CmdspotterConfig)
    cmdsafety: CmdsafetyConfig = field(default_factory=CmdsafetyConfig)
    spokenregex: SpokenregexConfig = field(default_factory=SpokenregexConfig)
    markup: MarkupConfig = field(default_factory=MarkupConfig)
    findreplace: FindreplaceConfig = field(default_factory=FindreplaceConfig)
    hotwords: HotwordsConfig = field(default_factory=HotwordsConfig)
    windowctl: WindowctlConfig = field(default_factory=WindowctlConfig)
    cite: CiteConfig = field(default_factory=CiteConfig)
    langroute: LangrouteConfig = field(default_factory=LangrouteConfig)
    latency: LatencyConfig = field(default_factory=LatencyConfig)
    diarize: DiarizeConfig = field(default_factory=DiarizeConfig)
    spelling: SpellingConfig = field(default_factory=SpellingConfig)
    gitvoice: GitvoiceConfig = field(default_factory=GitvoiceConfig)
    reask: ReaskConfig = field(default_factory=ReaskConfig)
    verbatim: VerbatimConfig = field(default_factory=VerbatimConfig)
    corrdict: CorrdictConfig = field(default_factory=CorrdictConfig)
    fileopen: FileopenConfig = field(default_factory=FileopenConfig)
    jump: JumpConfig = field(default_factory=JumpConfig)
    shellpipe: ShellpipeConfig = field(default_factory=ShellpipeConfig)
    mcp: McpConfig = field(default_factory=McpConfig)
    recimport: RecimportConfig = field(default_factory=RecimportConfig)
    meeting: MeetingConfig = field(default_factory=MeetingConfig)
    crowdproof: CrowdproofConfig = field(default_factory=CrowdproofConfig)
    chords: ChordsConfig = field(default_factory=ChordsConfig)
    compute: ComputeConfig = field(default_factory=ComputeConfig)
    casetransform: CasetransformConfig = field(default_factory=CasetransformConfig)
    autopair: AutopairConfig = field(default_factory=AutopairConfig)
    timeline: TimelineConfig = field(default_factory=TimelineConfig)
    bookmarks: BookmarksConfig = field(default_factory=BookmarksConfig)
    tablecsv: TablecsvConfig = field(default_factory=TablecsvConfig)
    wordgoal: WordgoalConfig = field(default_factory=WordgoalConfig)
    voicetimer: VoicetimerConfig = field(default_factory=VoicetimerConfig)
    focusprofile: FocusprofileConfig = field(default_factory=FocusprofileConfig)
    vocaljoystick: VocaljoystickConfig = field(default_factory=VocaljoystickConfig)
    earcon: EarconConfig = field(default_factory=EarconConfig)
    spatialvad: SpatialvadConfig = field(default_factory=SpatialvadConfig)
    prosodypunct: ProsodypunctConfig = field(default_factory=ProsodypunctConfig)
    hesitation: HesitationConfig = field(default_factory=HesitationConfig)
    contour: ContourConfig = field(default_factory=ContourConfig)
    breath: BreathConfig = field(default_factory=BreathConfig)
    whispermode: WhispermodeConfig = field(default_factory=WhispermodeConfig)
    mouthswitch: MouthswitchConfig = field(default_factory=MouthswitchConfig)
    involuntary: InvoluntaryConfig = field(default_factory=InvoluntaryConfig)
    morsevox: MorsevoxConfig = field(default_factory=MorsevoxConfig)
    checkdigit: CheckdigitConfig = field(default_factory=CheckdigitConfig)
    sembr: SembrConfig = field(default_factory=SembrConfig)
    acronyms: AcronymsConfig = field(default_factory=AcronymsConfig)
    styleguard: StyleguardConfig = field(default_factory=StyleguardConfig)
    suggestmode: SuggestmodeConfig = field(default_factory=SuggestmodeConfig)
    screenplay: ScreenplayConfig = field(default_factory=ScreenplayConfig)
    srscap: SrscapConfig = field(default_factory=SrscapConfig)
    diagramvox: DiagramvoxConfig = field(default_factory=DiagramvoxConfig)
    proofback: ProofbackConfig = field(default_factory=ProofbackConfig)
    hatselect: HatselectConfig = field(default_factory=HatselectConfig)
    translit: TranslitConfig = field(default_factory=TranslitConfig)
    brailleout: BrailleoutConfig = field(default_factory=BrailleoutConfig)
    outline: OutlineConfig = field(default_factory=OutlineConfig)
    diacritize: DiacritizeConfig = field(default_factory=DiacritizeConfig)
    safeglyph: SafeglyphConfig = field(default_factory=SafeglyphConfig)
    wordfind: WordfindConfig = field(default_factory=WordfindConfig)
    loadguard: LoadguardConfig = field(default_factory=LoadguardConfig)
    echo: EchoConfig = field(default_factory=EchoConfig)
    srpace: SrpaceConfig = field(default_factory=SrpaceConfig)
    profiles: ProfilesConfig = field(default_factory=ProfilesConfig)


def _load_filters(data: dict) -> FiltersConfig:
    filters_raw = data.get("filters", {})
    disf_raw = filters_raw.get("disfluency", {})
    return FiltersConfig(disfluency=DisfluencyConfig(**disf_raw))


def _load_emg(data: dict) -> EmgConfig:
    raw = data.get("emg", {})
    return EmgConfig(
        device_port=raw.get("device_port", ""),
        baud_rate=raw.get("baud_rate", 115200),
        ble_address=raw.get("ble_address", ""),
        mode=raw.get("mode", "command"),
        command_map=raw.get("command_map", {}),
    )


@dataclass(frozen=True)
class LoadedConfig:
    """A config, plus everything that was wrong with the file it came from."""

    config: Config
    problems: list[ConfigProblem]
    path: Path | None


def load_config_checked(path: Path | None = None) -> LoadedConfig:
    """Load the config, repairing what can be repaired and reporting the rest.

    Deliberately total: there is no input to this function that makes it raise. A
    dictation daemon that refuses to start because of one mistyped line is useless in
    exactly the moment you reach for the key, so a broken file degrades to defaults and
    the reasons come back in ``problems`` for the daemon to log and ``doctor`` to show.

    Sections are built by walking ``Config``'s own fields, so a new section is covered the
    day it is added rather than the day someone remembers to update this function.
    """
    if path is None:
        path = Path.home() / ".config" / "yazses" / "config.toml"
    problems: list[ConfigProblem] = []
    if not path.exists():
        return LoadedConfig(Config(), problems, None)

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError, ValueError) as exc:
        # Unparseable file: still start, on defaults, and say so loudly. Refusing to run
        # would turn a typo into "my dictation is gone" with no way to hear why.
        problems.append(
            ConfigProblem("", "", f"could not be read ({exc}); using defaults throughout", False)
        )
        return LoadedConfig(Config(), problems, path)

    hints = typing.get_type_hints(Config)
    fields = {f.name for f in dataclasses.fields(Config)}
    for name in data:
        if name not in fields:
            problems.append(
                ConfigProblem(str(name), "", "is not a known section; ignored", False)
            )

    sections = {
        name: build_section(hints[name], data[name], name, problems)
        for name in fields
        if name in data
    }
    return LoadedConfig(_apply_presets(Config(**sections)), problems, path)


def load_config(path: Path | None = None) -> Config:
    """Load the config. Never raises; problems are logged and the daemon carries on."""
    loaded = load_config_checked(path)
    for problem in loaded.problems:
        log.warning("config.toml: %s", problem)
    return loaded.config


def _apply_presets(cfg: Config) -> Config:
    """Apply convenience presets that flip several keys from one switch.

    Dysfluency-Friendly Mode (ADR-015): enable the disfluency collapse pass and
    widen pre-speech padding for delayed voice onset. It does NOT alter
    endpointing — YazSes is hold-to-talk, so the user controls utterance end.
    """
    if cfg.accessibility.dysfluency_friendly:
        cfg.filters.disfluency.collapse_repetitions = True
        cfg.filters.disfluency.collapse_prolongations = True
        cfg.accessibility.pre_speech_padding_ms = max(
            cfg.accessibility.pre_speech_padding_ms, 400
        )
    return cfg
