"""Interruptible Read-Back Proofreading (ADR-v2-108).

Hold the dictation key while a dictated burst is being read back: the word being read is
identified, and the next dictated burst replaces the text from that word to the end of the
burst. ``timeline`` estimates per-word playback times from TTS chunks, ``bargein`` makes
every decision (pure, clock-injected), and ``align`` holds the original fixed-duration
schedule and ``resolve_target``. Wired in ``core/daemon.py``. OFF by default.
"""
