"""Hard Contextual Biasing (ADR-v2-069) + Voice Window Management (ADR-v2-070) — pure cores."""
from __future__ import annotations

from yazses.biasing.trie import build_hotword_trie, rescore_nbest
from yazses.windowctl.commands import WmAction, parse_wm_command

# ---- hotword trie ----------------------------------------------------------

def test_trie_membership_and_prefix():
    trie = build_hotword_trie(["Kubernetes", "YazSes", "  ", ""])
    assert trie.is_term("kubernetes") is True
    assert trie.is_term("YAZSES") is True
    assert trie.is_term("kube") is False
    assert trie.has_prefix("kube") is True
    assert trie.has_prefix("xyz") is False
    assert bool(trie) is True
    assert bool(build_hotword_trie([])) is False


def test_rescore_promotes_hotword_hypothesis():
    trie = build_hotword_trie(["Kubernetes"])
    hyps = [("cuber netties cluster", -0.5), ("kubernetes cluster", -1.0)]
    ranked = rescore_nbest(hyps, trie, boost=2.0)
    assert ranked[0][0] == "kubernetes cluster"     # boosted above the higher raw score


def test_rescore_no_hits_keeps_order():
    trie = build_hotword_trie(["Kubernetes"])
    hyps = [("hello world", -0.1), ("goodbye", -0.2)]
    ranked = rescore_nbest(hyps, trie)
    assert [h[0] for h in ranked] == ["hello world", "goodbye"]


# ---- window management -----------------------------------------------------

def test_snap_halves():
    assert parse_wm_command("move window left half") == WmAction("snap", "left")
    assert parse_wm_command("snap right") == WmAction("snap", "right")
    assert parse_wm_command("tile window up") == WmAction("snap", "top")


def test_snap_quarters():
    assert parse_wm_command("move window top left") == WmAction("snap", "top-left")
    assert parse_wm_command("snap bottom right") == WmAction("snap", "bottom-right")


def test_state_actions():
    assert parse_wm_command("maximize the window") == WmAction("maximize")
    assert parse_wm_command("minimise").kind == "minimize"
    assert parse_wm_command("go full screen") == WmAction("fullscreen")
    assert parse_wm_command("center window") == WmAction("center")
    assert parse_wm_command("close the window") == WmAction("close")


def test_workspace_actions():
    assert parse_wm_command("workspace 3") == WmAction("workspace", 3)
    assert parse_wm_command("go to desktop 2") == WmAction("workspace", 2)
    assert parse_wm_command("next workspace") == WmAction("workspace_rel", 1)
    assert parse_wm_command("previous desktop") == WmAction("workspace_rel", -1)


def test_wm_none():
    assert parse_wm_command("hello there") is None
    assert parse_wm_command("") is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "hotwords" in slugs and "windowctl" in slugs
    assert Config().hotwords.enabled is False and Config().windowctl.enabled is False
