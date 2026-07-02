"""Screen-Grounded Dictation (ADR-v2-051).

Bias Whisper's initial_prompt from on-screen text so visible names transcribe correctly. The
``harvest`` module is the pure term-mining core over accessibility/clipboard text; the OCR VLM
pixel path is deferred behind the ``screenocr`` extra. OFF by default.
"""
