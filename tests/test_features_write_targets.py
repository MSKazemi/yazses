"""Guard: every toggleable feature's enable/disable writes target its own config section.

Regression test for the variable-name-collision class in ``_registry()`` (e.g. ``pr_on``
reused across prosody/predict/pronunciation), which silently made one feature's toggle write
to another feature's section.
"""
from __future__ import annotations

from yazses.system.features import _registry

# Features whose predicate reads a section that differs from the write target by design
# (nested/aliased keys). Map slug -> the section its writes are EXPECTED to touch.
_ALIASES = {
    "voice-punctuation": "commands",
    "spoken-edit": "commands",
    "symbols": "commands",
    "undo": "revise",
    "ghost-ahead": "endpoint",
    "read-back": "tts",            # + accessibility
    "dysfluency": "accessibility",
    "multiprofile": "voiceprint",
    "corpus_scrub": "learning",
    "readback_clone": "tts",
    "llm-cleanup": "filters.disfluency",
}


def test_each_toggle_writes_expected_section():
    for d in _registry():
        if not d.on_writes:
            continue
        sections = {w[0] for w in d.on_writes} | {w[0] for w in d.off_writes}
        expected = _ALIASES.get(d.slug, d.slug.replace("-", "_"))
        assert expected in sections, (
            f"feature {d.slug!r} writes {sorted(sections)} but should touch {expected!r} "
            f"— likely a variable-name collision in _registry()"
        )


def test_registry_has_no_duplicate_slugs():
    slugs = [d.slug for d in _registry()]
    assert len(slugs) == len(set(slugs)), "duplicate feature slug in _registry()"
