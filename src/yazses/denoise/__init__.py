"""Real-time noise-suppression front-end (ADR-v2-015).

A denoise/dereverb stage between mic capture and STT so dictation survives noisy or
echoey rooms and quiet speech clears the VAD gate. ``frontend.apply_denoise`` is an
identity passthrough unless ``[denoise]`` is enabled with an available backend; the
DeepFilterNet backend is lazy behind the ``denoise`` extra. Never raises — any
failure falls back to the original audio. OFF by default.
"""
