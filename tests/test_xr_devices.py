"""Device profiles: unknown stays unknown, presets never lean on None, evidence is present."""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from yazses.modality.router import PRESETS
from yazses.xr import devices
from yazses.xr.devices import DeviceProfile, get, keys, render_table, suggest_preset

_ROOT = Path(__file__).resolve().parents[1]
_CAPS = ("has_eye_tracking", "has_hand_tracking", "has_microphone_stream")


def _p(eye=None, hand=None, mic=None) -> DeviceProfile:
    return DeviceProfile("k", "K", eye, hand, mic, "c", "n", "e")


def test_keys_unique_and_every_key_resolvable():
    ks = keys()
    assert len(ks) == len(set(ks))
    for k in ks:
        assert get(k).key == k


def test_required_keys_present():
    assert {"phone-companion", "generic-openxr", "meta-quest", "ray-ban-meta",
            "android-xr", "vision-pro"} <= set(keys())


def test_unknown_key_error_lists_known_keys():
    with pytest.raises(KeyError) as e:
        get("nokia-3310")
    for k in keys():
        assert k in str(e.value)
    with pytest.raises(KeyError):
        get(None)  # type: ignore[arg-type]


def test_profile_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        get("vision-pro").has_eye_tracking = False  # type: ignore[misc]


def test_every_profile_has_nonempty_evidence():
    for k in keys():
        assert get(k).evidence.strip()


def test_no_true_capability_without_nontrivial_evidence():
    for k in keys():
        p = get(k)
        if any(getattr(p, c) is True for c in _CAPS):
            assert len(p.evidence.strip()) >= 40, k
            assert "ADR" in p.evidence or "03-ar-wearables" in p.evidence, k


def test_phone_and_generic_baselines():
    phone = get("phone-companion")
    assert phone.has_microphone_stream is True
    assert phone.has_eye_tracking is None  # ADR-v2-013 never mentions eye/gaze
    assert "ADR-v2-013" in phone.evidence
    g = get("generic-openxr")
    assert all(getattr(g, c) is None for c in _CAPS)
    assert "queried at runtime" in g.evidence


def test_unstated_hardware_is_unknown_not_false():
    for k in ("meta-quest", "ray-ban-meta"):
        assert all(getattr(get(k), c) is None for c in _CAPS), k
    for k in ("android-xr", "vision-pro"):
        assert get(k).has_microphone_stream is None


def test_render_table_is_deterministic_and_complete():
    assert render_table() == render_table()
    text = render_table()
    for k in keys():
        assert k in text


def test_render_shows_unknown_never_false():
    text = render_table()
    assert "unknown" in text
    row = next(r for r in text.splitlines() if r.startswith("generic-openxr"))
    assert row.split()[1:4] == ["unknown", "unknown", "unknown"]
    assert "False" not in text and "None" not in text
    phone = next(r for r in text.splitlines() if r.startswith("phone-companion"))
    assert phone.split()[1:4] == ["unknown", "unknown", "yes"]


def test_preset_names_exist_in_router():
    for name in (devices.PRESET_BALANCED, devices.PRESET_HANDS_FREE, devices.PRESET_VOICE_ONLY):
        assert name in PRESETS
    for k in keys():
        assert suggest_preset(get(k)) in PRESETS


@pytest.mark.parametrize("eye", [None, False])
@pytest.mark.parametrize("hand", [None, False])
@pytest.mark.parametrize("mic", [None, False, True])
def test_unknown_or_false_never_upgrades(eye, hand, mic):
    assert suggest_preset(_p(eye, hand, mic)) == "voice-only"


def test_known_true_capabilities_upgrade():
    assert suggest_preset(_p(eye=True)) == "hands-free"
    assert suggest_preset(_p(eye=True, hand=None)) == "hands-free"
    assert suggest_preset(_p(hand=True)) == "balanced"
    assert suggest_preset(_p(eye=False, hand=True)) == "balanced"


def test_unknown_equals_false_for_preset():
    assert suggest_preset(_p(None, None, None)) == suggest_preset(_p(False, False, False))


def test_real_profiles_presets():
    assert suggest_preset(get("generic-openxr")) == "voice-only"
    assert suggest_preset(get("phone-companion")) == "voice-only"
    # Eye tracking is unknown for both headsets (the research only supports OS-level
    # gaze+pinch), so unknown must not upgrade them to hands-free.
    for k in ("vision-pro", "android-xr"):
        assert get(k).has_eye_tracking is None
        assert suggest_preset(get(k)) == "balanced"  # known hand input only


def _collapse(text: str) -> str:
    return " ".join(text.split())


_KEYWORDS = {
    "has_eye_tracking": ("eye", "gaze"),
    "has_hand_tracking": ("hand", "pinch"),
    "has_microphone_stream": ("mic",),
}


def test_every_true_or_false_capability_has_a_literally_supporting_source():
    """Grep the cited text: the quote must exist verbatim in the cited repo file."""
    for k in keys():
        p = get(k)
        for cap in _CAPS:
            if getattr(p, cap) is None:
                continue
            srcs = [s for s in p.sources if s.capability == cap]
            assert srcs, f"{k}.{cap} is {getattr(p, cap)!r} with no source"
            for s in srcs:
                path = _ROOT / s.path
                assert path.is_file(), f"{k}: {s.path} does not exist"
                assert _collapse(s.quote) in _collapse(path.read_text(encoding="utf-8")), (
                    f"{k}.{cap}: quote not found in {s.path}: {s.quote!r}")
                assert any(w in s.quote.lower() for w in _KEYWORDS[cap]), (
                    f"{k}.{cap}: quote {s.quote!r} does not speak about the capability")


def test_sources_only_back_known_capabilities():
    for k in keys():
        p = get(k)
        for s in p.sources:
            assert s.capability in _CAPS
            assert getattr(p, s.capability) is not None, f"{k}: source for an unknown value"


def test_regression_no_profile_claims_eye_tracking_the_repo_does_not_state():
    """Phone was False citing ADR-v2-013, vision-pro/android-xr True from OS-level gaze+pinch.

    ADR-v2-013 never mentions eye or gaze; the research text speaks only of OS-level
    gaze+pinch / gaze+hand+voice fusion, not of an app receiving a gaze ray.
    """
    adr = (_ROOT / "design/adr/adr-v2-013-glasses-desktop-bridge.md").read_text(encoding="utf-8")
    assert not re.search(r"\b(eye|eyes|gaze)", adr, re.IGNORECASE)
    for k in keys():
        assert get(k).has_eye_tracking is None, k
