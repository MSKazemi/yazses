from __future__ import annotations

import pytest

from yazses.config import SttConfig
from yazses.language import (
    LanguageProfileError,
    derive_status,
    get_profile,
    list_profiles,
    resolve_profile,
)


def _changes(plan):
    return {(m.section, m.key): (m.before, m.after) for m in plan.mutations}


def test_profile_ids_and_aliases_are_stable():
    assert [p.id for p in list_profiles()] == ["en", "zh-CN", "zh-TW"]
    assert get_profile("EN").id == "en"
    assert get_profile("zh-cn").id == "zh-CN"
    assert get_profile("zh_Hans").id == "zh-CN"
    assert get_profile("ZH-tw").id == "zh-TW"
    assert get_profile("zh_hant").id == "zh-TW"


@pytest.mark.parametrize("requested", ["zh-HK", "yue", "yue-HK", "Cantonese"])
def test_cantonese_or_hong_kong_requests_are_not_silently_mapped_to_mandarin(requested):
    with pytest.raises(LanguageProfileError) as exc:
        get_profile(requested)
    assert "Cantonese" in str(exc.value)


def test_bare_zh_requires_an_output_script_choice():
    with pytest.raises(LanguageProfileError) as exc:
        get_profile("zh")
    message = str(exc.value)
    assert "zh-CN" in message
    assert "zh-TW" in message


def test_unknown_profile_lists_the_available_choices():
    with pytest.raises(LanguageProfileError) as exc:
        get_profile("xx")
    message = str(exc.value)
    assert "en" in message
    assert "zh-CN" in message
    assert "zh-TW" in message


def test_default_english_to_simplified_mandarin_repairs_english_only_model():
    plan = resolve_profile("zh-CN", SttConfig())
    changes = _changes(plan)

    assert plan.canonical_profile == "zh-CN"
    assert changes[("stt", "model")] == ("base.en", "small")
    assert changes[("stt", "language")] == ("en", "zh")
    assert changes[("stt", "chinese_script")] == ("", "simplified")
    assert ("stt", "engine") not in changes
    assert plan.model_download == "small"
    assert plan.required_extras == ("chinese",)
    assert plan.restart_required


def test_preserve_mode_keeps_a_compatible_multilingual_model():
    stt = SttConfig(model="base", language="en")
    plan = resolve_profile("zh-CN", stt)
    changes = _changes(plan)

    assert ("stt", "model") not in changes
    assert plan.model_download is None
    assert changes[("stt", "language")] == ("en", "zh")
    assert changes[("stt", "chinese_script")] == ("", "simplified")


def test_preserve_mode_keeps_a_custom_compatible_large_model():
    stt = SttConfig(model="large-v3", language="en")
    plan = resolve_profile("zh-TW", stt)

    assert ("stt", "model") not in _changes(plan)
    assert plan.model_download is None


def test_recommended_mode_reselects_the_profile_baseline():
    stt = SttConfig(model="large-v3", language="zh", chinese_script="simplified")
    plan = resolve_profile("zh-CN", stt, mode="recommended")
    changes = _changes(plan)

    assert changes[("stt", "model")] == ("large-v3", "small")
    assert plan.model_download == "small"


def test_traditional_profile_changes_only_the_script_when_speech_is_already_mandarin():
    stt = SttConfig(model="small", language="zh", chinese_script="simplified")
    plan = resolve_profile("zh-TW", stt)

    assert _changes(plan) == {
        ("stt", "chinese_script"): ("simplified", "traditional"),
    }


def test_switching_back_to_english_preserves_a_multilingual_model_by_default():
    stt = SttConfig(model="small", language="zh", chinese_script="traditional")
    plan = resolve_profile("en", stt)
    changes = _changes(plan)

    assert ("stt", "model") not in changes
    assert changes[("stt", "language")] == ("zh", "en")
    assert changes[("stt", "chinese_script")] == ("traditional", "")
    assert plan.model_download is None
    assert plan.required_extras == ()


def test_recommended_english_mode_can_restore_base_en():
    stt = SttConfig(model="small", language="zh", chinese_script="simplified")
    plan = resolve_profile("en", stt, mode="recommended")

    assert _changes(plan)[("stt", "model")] == ("small", "base.en")
    assert plan.model_download == "base.en"


def test_incompatible_explicit_mandarin_model_is_refused_not_rewritten():
    with pytest.raises(LanguageProfileError) as exc:
        resolve_profile("zh-CN", SttConfig(), model="small.en")
    assert "English-only" in str(exc.value)


def test_incompatible_explicit_mandarin_engine_is_refused_not_rewritten():
    with pytest.raises(LanguageProfileError) as exc:
        resolve_profile("zh-CN", SttConfig(), engine="parakeet")
    assert "faster-whisper" in str(exc.value)


def test_existing_english_only_engine_is_repaired_to_supported_mandarin_baseline():
    stt = SttConfig(engine="parakeet", model="nemo-parakeet-tdt-0.6b-v2")
    plan = resolve_profile("zh-CN", stt)
    changes = _changes(plan)

    assert changes[("stt", "engine")] == ("parakeet", "faster-whisper")
    assert changes[("stt", "model")] == ("nemo-parakeet-tdt-0.6b-v2", "small")


def test_noop_profile_has_no_restart_or_model_requirement():
    plan = resolve_profile("en", SttConfig())

    assert plan.mutations == ()
    assert plan.model_download is None
    assert not plan.restart_required


def test_status_recognises_default_english():
    status = derive_status(SttConfig())

    assert status.coherent
    assert status.profile_match == "en"
    assert not status.custom_model
    assert status.problems == ()


def test_status_recognises_compatible_custom_mandarin_model():
    status = derive_status(
        SttConfig(model="large-v3", language="zh", chinese_script="simplified")
    )

    assert status.coherent
    assert status.profile_match == "zh-CN"
    assert status.custom_model


def test_status_rejects_english_only_model_with_mandarin():
    status = derive_status(
        SttConfig(model="base.en", language="zh", chinese_script="simplified")
    )

    assert not status.coherent
    assert any("English-only" in problem for problem in status.problems)


def test_status_rejects_han_script_on_non_chinese_speech():
    status = derive_status(
        SttConfig(model="base.en", language="en", chinese_script="traditional")
    )

    assert not status.coherent
    assert any("Chinese-output setting" in problem for problem in status.problems)


def test_status_rejects_non_whisper_mandarin_engine():
    status = derive_status(
        SttConfig(
            engine="parakeet",
            model="nemo-parakeet-tdt-0.6b-v2",
            language="zh",
            chinese_script="simplified",
        )
    )

    assert not status.coherent
    assert any("not declared Mandarin-capable" in problem for problem in status.problems)


def test_unpinned_mandarin_script_is_coherent_but_not_a_profile_match():
    status = derive_status(SttConfig(model="small", language="zh", chinese_script=""))

    assert status.coherent
    assert status.profile_match is None


def test_invalid_resolution_mode_is_refused():
    with pytest.raises(ValueError):
        resolve_profile("en", SttConfig(), mode="magic")  # type: ignore[arg-type]


def test_recommended_mode_rejects_explicit_model_or_engine_overrides():
    with pytest.raises(LanguageProfileError):
        resolve_profile("zh-CN", SttConfig(), mode="recommended", model="large-v3")
    with pytest.raises(LanguageProfileError):
        resolve_profile(
            "zh-CN",
            SttConfig(),
            mode="recommended",
            engine="faster-whisper",
        )
