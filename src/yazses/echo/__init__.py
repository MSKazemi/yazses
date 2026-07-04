"""Echo — replay your own captured audio for a text span (ADR-v2-119).

"Play that back" replays the *original captured audio* aligned to a chosen text span (not TTS), so
homophone/ASR errors are caught eyes-free by ear. The ``span`` module is the pure span-index
builder + playback-target resolver; audio playback is the only I/O. OFF by default.
"""
