"""Glasses↔Desktop Dictation Bridge (ADR-v2-013).

A companion device (phone-as-mic now, smart glasses when they expose an audio
stream) pairs with the desktop over a shared token and streams audio frames; the
desktop runs STT + injection (so no model ships to the companion). This package's
``session`` (pairing state machine) and ``frame`` (framing) modules are pure and
testable; the socket transport reuses the ``remote/`` patterns and is opt-in. OFF
by default — nothing leaves the paired local link (ADR-011).
"""
