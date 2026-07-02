"""Voice Undo/Redo Timeline (ADR-v2-089).

A ring of YazSes's own injection events so its output can be undone/redone across bursts by voice.
The ``history`` module is the pure timeline; the injector applies the backspace/retype delta.
OFF by default.
"""
