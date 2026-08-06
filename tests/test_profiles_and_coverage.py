"""Coverage hardening: command profiles, grammar SLM-router fallback, feature tier_label."""
from __future__ import annotations

from yazses.commands.grammar import CommandIntent, IntentType, classify
from yazses.commands.profiles import ProfileRegistry, load_profiles
from yazses.config import CommandsConfig

# ---- profiles --------------------------------------------------------------

def test_load_profiles_returns_registry():
    reg = load_profiles(CommandsConfig())
    assert isinstance(reg, ProfileRegistry)


def test_profile_resolve_falls_back_to_default():
    assert ProfileRegistry().resolve("unknown") == "default"


def test_profile_resolve_uses_mapping_hit():
    reg = ProfileRegistry(profiles={"nvim": "neovim"})
    assert reg.resolve("nvim") == "neovim"


# ---- grammar SLM-router fallback path --------------------------------------

class _StubRouter:
    def __init__(self, result):
        self._result = result

    def classify(self, text, profile):
        return self._result


def test_classify_uses_slm_router_result_when_tier1_misses():
    intent = CommandIntent(intent=IntentType.DICTATE, action="inject", raw_text="x")
    out = classify("some unrecognised phrase", slm_router=_StubRouter(intent))
    assert out is intent


def test_classify_falls_through_when_slm_router_returns_none():
    out = classify("some unrecognised phrase", slm_router=_StubRouter(None))
    assert out.intent is IntentType.DICTATE and out.action == "inject"


# ---- feature tier_label property -------------------------------------------

def test_feature_tier_label_resolves():
    from yazses.config import Config
    from yazses.system.features import feature_status
    feats = feature_status(Config())
    # every feature exposes a non-empty tier label
    assert all(f.tier_label for f in feats)
