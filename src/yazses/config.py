import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SttConfig:
    # base.en balances accuracy and CPU latency far better than tiny.en, which
    # produces frequent word errors. Larger models (small.en/medium.en) trade
    # decode latency for marginal gains on clean speech.
    model: str = "base.en"
    device: str = "cpu"
    compute_type: str = "int8"
    # Optional vocabulary/context primed into Whisper as initial_prompt. Helps it
    # spell domain terms and proper nouns it otherwise mis-transcribes. `yazses
    # tune` proposes additions here from the learning corpus.
    initial_prompt: str = ""


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


@dataclass
class InjectionConfig:
    backend: str = "auto"
    fallback_to_clipboard: bool = True
    # Successive hold-to-talk bursts within this window are treated as one
    # continuous dictation: a separating space is prepended to the next burst
    # so words don't glue together at the boundary (postprocess/spacing.py).
    # 0 disables continuation spacing entirely.
    continuation_window_ms: int = 30000


@dataclass
class GeneralConfig:
    log_level: str = "INFO"


@dataclass
class StreamingConfig:
    # Disabled by default: live-partial injection corrects on commit via
    # shift+Left selection (inject/streaming.py), which deletes text in apps
    # where shift+Left isn't "extend selection". Batch transcribe-on-release is
    # the reliable, higher-accuracy path proven by tools like nerd-dictation and
    # faster-whisper-dictation. Opt back in with [streaming] enabled = true.
    enabled: bool = False
    partial_interval_ms: int = 300
    partial_marker: str = ""


@dataclass
class DisfluencyConfig:
    enabled: bool = True
    filler_words: list[str] = field(default_factory=lambda: [
        "um", "uh", "er", "err", "ah", "hmm", "like", "you know",
        "i mean", "basically", "right", "okay so",
        "sort of", "kind of", "literally", "actually",
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
    model_path: str = ""
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
    backend: str = "l2cs"             # l2cs | none
    zones: str = "grid3x3"            # grid3x3 | grid2x2 | windows
    camera_index: int = 0
    calibration_points: int = 9
    confidence_min: float = 0.5
    # v2.0.0 Wave C — Gaze-Routed Dictation (ADR-v2-010): route the next dictation
    # to the looked-at window (else the focused window), and confirm destructive
    # gaze-routed actions since coarse gaze can misroute. Off by default.
    route_dictation: bool = False
    confirm_destructive: bool = True


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
    passthrough when off; the DeepFilterNet backend is opt-in behind the ``denoise``
    extra. OFF by default.
    """
    enabled: bool = False
    backend: str = "deepfilternet"   # deepfilternet | none
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
    tts: TtsConfig = field(default_factory=TtsConfig)
    voiceprint: VoiceprintConfig = field(default_factory=VoiceprintConfig)
    gaze: GazeConfig = field(default_factory=GazeConfig)
    cocktail: CocktailConfig = field(default_factory=CocktailConfig)
    personalize: PersonalizeConfig = field(default_factory=PersonalizeConfig)
    polyglot: PolyglotConfig = field(default_factory=PolyglotConfig)
    # v2.0.0 Wave A (Voice-First Interaction Layer)
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    recall: RecallConfig = field(default_factory=RecallConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    pilot: PilotConfig = field(default_factory=PilotConfig)
    modality: ModalityConfig = field(default_factory=ModalityConfig)
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


def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = Path.home() / ".config" / "yazses" / "config.toml"
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    cfg = Config(
        stt=SttConfig(**data.get("stt", {})),
        hotkey=HotkeyConfig(**data.get("hotkey", {})),
        audio=AudioConfig(**data.get("audio", {})),
        injection=InjectionConfig(**data.get("injection", {})),
        general=GeneralConfig(**data.get("general", {})),
        streaming=StreamingConfig(**data.get("streaming", {})),
        filters=_load_filters(data),
        accessibility=AccessibilityConfig(**data.get("accessibility", {})),
        commands=CommandsConfig(**data.get("commands", {})),
        macros=MacrosConfig(**data.get("macros", {})),
        revise=ReviseConfig(**data.get("revise", {})),
        punch_in=PunchInConfig(**data.get("punch_in", {})),
        endpoint=EndpointConfig(**data.get("endpoint", {})),
        prosody=ProsodyConfig(**data.get("prosody", {})),
        remote=RemoteConfig(**data.get("remote", {})),
        emg=_load_emg(data),
        learning=LearningConfig(**data.get("learning", {})),
        overlay=OverlayConfig(**data.get("overlay", {})),
        tts=TtsConfig(**data.get("tts", {})),
        voiceprint=VoiceprintConfig(**data.get("voiceprint", {})),
        gaze=GazeConfig(**data.get("gaze", {})),
        cocktail=CocktailConfig(**data.get("cocktail", {})),
        personalize=PersonalizeConfig(**data.get("personalize", {})),
        polyglot=PolyglotConfig(**data.get("polyglot", {})),
        confidence=ConfidenceConfig(**data.get("confidence", {})),
        context=ContextConfig(**data.get("context", {})),
        recall=RecallConfig(**data.get("recall", {})),
        agent=AgentConfig(**data.get("agent", {})),
        pilot=PilotConfig(**data.get("pilot", {})),
        modality=ModalityConfig(**data.get("modality", {})),
        continuum=ContinuumConfig(**data.get("continuum", {})),
        bridge=BridgeConfig(**data.get("bridge", {})),
        translate=TranslateConfig(**data.get("translate", {})),
        affect=AffectConfig(**data.get("affect", {})),
        denoise=DenoiseConfig(**data.get("denoise", {})),
        predict=PredictConfig(**data.get("predict", {})),
        voiceguard=VoiceguardConfig(**data.get("voiceguard", {})),
        scribe=ScribeConfig(**data.get("scribe", {})),
        rag=RagConfig(**data.get("rag", {})),
        codec=CodecConfig(**data.get("codec", {})),
        hallucination=HallucinationConfig(**data.get("hallucination", {})),
        snippets=SnippetsConfig(**data.get("snippets", {})),
        phonetic=PhoneticConfig(**data.get("phonetic", {})),
        autostop=AutoStopConfig(**data.get("autostop", {})),
        mousegrid=MousegridConfig(**data.get("mousegrid", {})),
        code=CodeConfig(**data.get("code", {})),
        math=MathConfig(**data.get("math", {})),
        wakeword=WakewordConfig(**data.get("wakeword", {})),
        voicehealth=VoicehealthConfig(**data.get("voicehealth", {})),
        coach=CoachConfig(**data.get("coach", {})),
        smartpaste=SmartpasteConfig(**data.get("smartpaste", {})),
        scrub=ScrubConfig(**data.get("scrub", {})),
        reflow=ReflowConfig(**data.get("reflow", {})),
        acoustic_profiles=AcousticProfilesConfig(**data.get("acoustic_profiles", {})),
        sentiment=SentimentConfig(**data.get("sentiment", {})),
        pronunciation=PronunciationConfig(**data.get("pronunciation", {})),
        gesture=GestureConfig(**data.get("gesture", {})),
        interpret=InterpretConfig(**data.get("interpret", {})),
        itn=ItnConfig(**data.get("itn", {})),
        redaction=RedactionConfig(**data.get("redaction", {})),
        fieldaware=FieldawareConfig(**data.get("fieldaware", {})),
        compose=ComposeConfig(**data.get("compose", {})),
        gec=GecConfig(**data.get("gec", {})),
        screengrounded=ScreengroundedConfig(**data.get("screengrounded", {})),
        headpointer=HeadpointerConfig(**data.get("headpointer", {})),
        lipread=LipreadConfig(**data.get("lipread", {})),
        sign=SignConfig(**data.get("sign", {})),
    )
    return _apply_presets(cfg)


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
