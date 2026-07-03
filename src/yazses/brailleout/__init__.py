"""BrailleOut — dictation to Unicode Braille output (ADR-v2-117).

Emit Grade-1/Grade-2 (UEB) Unicode Braille so a Braille-display or DeafBlind user receives
dictation directly in Braille. The ``ueb`` module is the pure table-driven translator; liblouis
stays an optional heavy backend. OFF by default.
"""
