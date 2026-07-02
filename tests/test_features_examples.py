"""Guard: every capability ships a usage example, so `yazses features info`/`-h` stay complete.

Enforces the user requirement that the CLI document EVERY feature with an example. When a new
feature is added to the registry, this test fails until an example is provided.
"""
from __future__ import annotations

from yazses.config import Config
from yazses.system.features import feature_status


def test_every_feature_has_a_nonempty_example():
    missing = [f.slug for f in feature_status(Config()) if not (f.example or "").strip()]
    assert not missing, f"features missing a usage example: {missing}"


def test_examples_are_reasonably_descriptive():
    # a one-word example is almost certainly a placeholder
    thin = [f.slug for f in feature_status(Config()) if len((f.example or "").split()) < 3]
    assert not thin, f"features with a too-thin example: {thin}"
