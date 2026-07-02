"""Voice Git Choreographer (ADR-v2-076).

Drive git via a structured argv grammar (never free-form shell); gate destructive ops behind a
spoken confirm and always speak the undo. The ``plan`` module is the pure intent builder +
reversibility classifier + undo hints; the executor is a plain ``git`` subprocess. OFF by default.
"""
