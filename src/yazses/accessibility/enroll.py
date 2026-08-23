"""Accessibility enrollment wizard — auto-tunes VAD parameters from user voice samples.

Guides the user through recording 20 short utterances and derives:
  - vad_threshold: percentile(noise_floors, 95) × 3.0
  - min_silence_ms: max(500, percentile(pause_durations, 95))

Writes derived values to config.toml under [accessibility].
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Harvard Sentences (phonetically diverse) — used for enrollment prompts.
_PROMPTS = [
    "The birch canoe slid on the smooth planks.",
    "Glue the sheet to the dark blue background.",
    "It is easy to tell the depth of a well.",
    "These days a chicken leg is a rare dish.",
    "Rice is often served in round bowls.",
    "The juice of lemons makes fine punch.",
    "The box was thrown beside the parked truck.",
    "The hogs were fed chopped corn and garbage.",
    "Four hours of steady work faced us.",
    "A large size in stockings is hard to sell.",
    "The boy was there when the sun rose.",
    "A rod is used to catch pink salmon.",
    "The source of the huge river is the clear spring.",
    "Kick the ball straight and follow through.",
    "Help the woman get back to her feet.",
    "A pot of tea helps to pass the evening.",
    "Smoky fires lack flame and heat.",
    "The soft cushion broke the man's fall.",
    "The salt breeze came across from the sea.",
    "The girl at the booth sold fifty bonds.",
]


def run_wizard(
    config_path: Path | None = None,
    recorder_factory=None,
    output_fn=print,
) -> dict:
    """Run the enrollment wizard. Returns the derived config values.

    Args:
        config_path: Path to config.toml. If None, uses platform default.
        recorder_factory: Callable returning an AudioRecorder-compatible object.
                          Used for testing (inject a mock recorder).
        output_fn: Function for user-facing output (default: print).
    """
    if recorder_factory is None:
        from yazses.audio.recorder import AudioRecorder
        recorder_factory = lambda: AudioRecorder(sample_rate=16000, max_seconds=5)  # noqa: E731

    output_fn("\nYazSes Accessibility Enrollment")
    output_fn("=" * 40)
    output_fn("You will read 20 short sentences aloud.")
    output_fn("Press Enter before each sentence, then speak normally.\n")

    noise_floors: list[float] = []
    speech_rms_values: list[float] = []
    pause_durations: list[float] = []

    sr = 16000
    noise_window = int(0.5 * sr)  # first 500ms = noise floor
    speech_start = noise_window   # rest = speech

    for i, prompt in enumerate(_PROMPTS):
        output_fn(f"\n[{i + 1}/20] Read aloud: \"{prompt}\"")
        input("  Press Enter when ready...")  # noqa: WPS421

        recorder = recorder_factory()
        output_fn("  Recording... (speak now)")
        recorder.start()
        time.sleep(3.0)
        audio = recorder.stop()

        if audio.size < sr:
            output_fn("  (recording too short, skipping)")
            continue

        nf = float(np.abs(audio[:noise_window]).mean()) if audio.size > noise_window else 0.0
        sp = float(np.abs(audio[speech_start:]).mean()) if audio.size > speech_start else 0.0
        noise_floors.append(nf)
        speech_rms_values.append(sp)

        # Estimate pause duration: count consecutive silent frames at end of recording
        frame_size = int(0.05 * sr)  # 50ms frames
        frames = [audio[j:j + frame_size] for j in range(0, audio.size - frame_size, frame_size)]
        silence_threshold = max(nf * 2, 0.005)
        trailing_silent_frames = 0
        for frame in reversed(frames):
            if np.abs(frame).mean() < silence_threshold:
                trailing_silent_frames += 1
            else:
                break
        pause_durations.append(trailing_silent_frames * 50)  # ms

        output_fn(f"  ✓ noise={nf:.4f}  speech={sp:.4f}")

    if len(noise_floors) < 5:
        output_fn("\nWarning: fewer than 5 valid recordings. Using default values.")
        return {"vad_threshold": 0.01, "min_silence_ms": 500}

    vad_threshold = float(np.percentile(noise_floors, 95) * 3.0)
    vad_threshold = max(0.001, min(vad_threshold, 0.1))  # clamp to sane range
    min_silence_ms = int(max(500, np.percentile(pause_durations, 95)))
    min_silence_ms = min(min_silence_ms, 5000)  # max 5 s

    output_fn("\nDerived settings:")
    output_fn(f"  vad_threshold   = {vad_threshold:.4f}")
    output_fn(f"  min_silence_ms  = {min_silence_ms}")

    result = {"vad_threshold": vad_threshold, "min_silence_ms": min_silence_ms}

    if config_path is not None:
        _write_config(config_path, result, output_fn)
    else:
        output_fn("\nTo apply, add to your config.toml:")
        output_fn("[accessibility]")
        for k, v in result.items():
            output_fn(f"{k} = {v}")

    return result


def _write_config(config_path: Path, values: dict, output_fn=print) -> None:
    """Write accessibility values to config.toml, preserving comments and other keys.

    This goes through ``system.configedit.set_config_key`` -- the same writer
    ``features``, ``hotkey set``, ``audio use`` and ``mic-level --set`` use -- rather
    than round-tripping the file through ``tomllib`` and back out.

    It used to do the round trip, and both of its branches lost something. The
    ``tomli_w`` branch rebuilt the file from parsed dicts, so every comment in it went
    away; and ``tomli_w`` is declared by no extra (it appears in ``pyproject.toml`` only
    in a mypy override list), so that branch never actually ran. What ran was the
    fallback, which deleted the whole ``[accessibility]`` section and wrote back only the
    two values the wizard computes -- silently resetting the other five to their
    defaults: ``pre_speech_padding_ms``, ``vad_source``, ``dysfluency_friendly``,
    ``read_back`` and ``confirm_timeout_s``.

    That last set is why this matters more here than it would elsewhere.
    ``dysfluency_friendly`` is the setting a disfluent speaker turns on deliberately, and
    this is the wizard written for that user; losing it as a side effect of calibrating a
    microphone is the opposite of what the command is for.
    """
    from yazses.system.configedit import set_config_key

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        for key, value in values.items():
            set_config_key(config_path, "accessibility", key, value)
        output_fn(f"\nConfig written to {config_path}")
    except Exception as exc:
        output_fn(f"\nWarning: could not write config: {exc}")
        output_fn("Manual config:")
        output_fn("[accessibility]")
        for k, v in values.items():
            output_fn(f"{k} = {v}")
