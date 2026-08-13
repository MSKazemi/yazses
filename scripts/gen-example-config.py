#!/usr/bin/env python3
"""Generate `examples/config.toml` from the real dataclass defaults (#20).

A hand-written example config is a promise that rots. The old one said
`key = "space"` and `model = "tiny.en"` long after the defaults had moved to
`right_ctrl` and `base.en` — so the file a newcomer was told to copy taught them
settings the program no longer used.

So it is generated from `yazses.config`, and `tests/test_example_config.py` fails
if the committed file drifts. Every value printed here is the value the daemon
uses when the key is absent, by construction rather than by review.

Deliberately **not** every section. The config has 40+ of them and a wall of
dormant experimental keys is not a starting point — it is the reference, which is
`docs/configuration.md` (also generated). This covers what the issue asks for:
the sections a new user actually touches.

Usage:
    uv run python scripts/gen-example-config.py            # write it
    uv run python scripts/gen-example-config.py --check    # fail if stale
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from yazses.config import (  # noqa: E402
    AccessibilityConfig,
    AudioConfig,
    CommandsConfig,
    HotkeyConfig,
    InjectionConfig,
    SttConfig,
)

TARGET = ROOT / "examples" / "config.toml"

# (section, dataclass, one-line purpose, {key: comment}). Only keys listed here
# are emitted: an example that prints every field is a reference, not an example.
SECTIONS = [
    ("stt", SttConfig, "How speech becomes text", {
        "engine": "faster-whisper (default) | parakeet | moonshine",
        "model": "tiny.en fast · base.en balanced · small.en accurate — see docs/models.md",
        "language": 'spoken language; "" auto-detects. Non-English needs a model without .en',
        "device": "cpu | cuda",
        "compute_type": "int8 is the CPU default; float16 for a GPU",
        "initial_prompt": "words to prime the recogniser with (Whisper only)",
        "vocab_correction": "repair mis-heard `yazses vocab` words after decoding",
    }),
    ("hotkey", HotkeyConfig, "The key you hold to talk", {
        "key": "right_ctrl | left_ctrl | right_alt | space | … (modifiers + space only)",
        "hold_threshold_ms": "how long to hold before recording starts",
        "command_key": 'a second key that forces command mode; "" disables',
    }),
    ("audio", AudioConfig, "Microphone capture", {
        "device": 'part of a mic name to pin it; "" follows the OS default',
        "sample_rate": "16 kHz is what the models expect — changing this is rarely right",
        "auto_heal_device": "switch back to the last working mic if capture goes silent",
    }),
    ("injection", InjectionConfig, "How text reaches the focused app", {
        "backend": "auto | type | clipboard | wtype",
        "target_guard": "what to do when the focused element accepts no text",
        "continuation_window_ms": "gap under which a new burst continues the last sentence",
    }),
    ("accessibility", AccessibilityConfig, "Speech and hearing accommodations", {
        "vad_threshold": "silence gate; lower it for a quiet voice (`yazses mic-level --set`)",
        "pre_speech_padding_ms": "silence prepended so the first word is not clipped",
        "dysfluency_friendly": "collapse repetitions and prolongations, widen onset padding",
    }),
    ("commands", CommandsConfig, "Spoken commands rather than text", {
        "enabled": "recognise 'delete the last word', 'new line', …",
        "voice_punctuation": "'comma' -> ',' — useful for code, noisy for prose",
    }),
]

HEADER = """# YazSes — annotated example configuration
#
# Copy to your config directory and edit; every key here is OPTIONAL and shows the
# built-in default, so an empty file behaves exactly like this one.
#
#   Linux    ~/.config/yazses/config.toml
#   macOS    ~/Library/Application Support/yazses/config.toml
#   Windows  %LOCALAPPDATA%\\yazses\\config.toml
#
# Apply changes with `yazses restart`, and check them with `yazses doctor`.
#
# This file is GENERATED from the dataclass defaults in src/yazses/config.py by
# scripts/gen-example-config.py — do not hand-edit it, and do not trust a value
# here that the code disagrees with (a test makes that impossible).
#
# The complete reference, including every section not shown here, is
# docs/configuration.md.
"""


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return str(value)


def render() -> str:
    out = [HEADER]
    for name, cls, purpose, comments in SECTIONS:
        defaults = {f.name: f for f in fields(cls)}
        out.append(f"\n# {purpose}\n[{name}]")
        width = max(len(k) + len(_toml(getattr(cls(), k))) for k in comments) + 4
        for key, comment in comments.items():
            if key not in defaults:
                raise SystemExit(f"[{name}] has no key {key!r} — the example is stale")
            assignment = f"{key} = {_toml(getattr(cls(), key))}"
            out.append(f"{assignment.ljust(width)}# {comment}")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = ap.parse_args()

    text = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"{TARGET.relative_to(ROOT)} is out of date — "
                  "run: uv run python scripts/gen-example-config.py")
            return 1
        print(f"OK — {TARGET.relative_to(ROOT)} matches the defaults.")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
