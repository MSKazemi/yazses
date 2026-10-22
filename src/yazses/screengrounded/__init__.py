"""Screen-Grounded Dictation (ADR-v2-051).

Bias Whisper's initial_prompt from on-screen text so visible names transcribe correctly. The
``harvest`` module is the pure term-mining core; ``sampler`` reads the focused window's
accessibility labels at hold start (AT-SPI on Linux) and hands their terms to one burst's
decode. The OCR VLM pixel path is deferred behind the ``screenocr`` extra. OFF by default.
"""
