"""Recording Import (batch transcription) (ADR-v2-083).

Transcribe existing recordings offline to .txt/.srt/.vtt with timestamps. The ``subtitles`` module
is the pure segmenter + subtitle writers; the Parakeet/NeMo STT backend is deferred behind a
``parakeet`` extra (faster-whisper is the zero-extra fallback). OFF by default.
"""
