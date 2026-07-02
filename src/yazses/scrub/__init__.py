"""Audio-Anchored Scrubbing (ADR-v2-037).

Keep word-level timestamps with a dictation so the user can replay a slice or pick a word to
re-dictate. The ``index`` module is the pure word→audio index + selection logic; playback
reuses sounddevice. Audio slices stay in RAM (persisted only under the existing encrypted
opt-in). OFF by default.
"""
