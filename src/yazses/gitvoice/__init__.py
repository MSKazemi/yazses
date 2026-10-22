"""Voice Git Choreographer (ADR-v2-076).

Turn a spoken git phrase into a git argv via a structured grammar (never free-form shell). The
``plan`` module is the pure intent builder + reversibility classifier + undo hints.

Reachable only through the CLI, ``yazses gitvoice "<text>"``: it prints the argv and its undo,
runs it (a plain ``git`` subprocess) only with ``--run``, and a destructive one only with
``--yes`` as well. Nothing is spoken, there is no spoken confirm, no dictation path runs git,
and ``[gitvoice] enabled`` is read by nothing.
"""
