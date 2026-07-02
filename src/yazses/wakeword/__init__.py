"""Wake-Word Activation (ADR-v2-033).

A low-power always-listening keyword spotter ("Hey Yaz") starts a dictation turn with no
key — a zero-touch activation modality. The ``detector`` module is the pure debounce/
threshold decision; the openWakeWord model is lazy behind the ``wakeword`` extra and runs
only on a short rolling buffer. EXPERIMENTAL, OFF by default.
"""
