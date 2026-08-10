from unittest.mock import MagicMock

from yazses.config import ProfilesConfig
from yazses.core.daemon import _TONE_INSTRUCTIONS, Daemon
from yazses.postprocess.profiles import resolve_profile


def test_resolve_profile_match():
    config = ProfilesConfig(app={"*code*": "formal", "*slack*": "casual", "*term*": "verbatim"})

    prof = resolve_profile("VSCode", config)
    assert prof.tone == "formal"

    prof = resolve_profile("slack", config)
    assert prof.tone == "casual"

    prof = resolve_profile("gnome-terminal", config)
    assert prof.tone == "verbatim"


def test_resolve_profile_unknown_app():
    config = ProfilesConfig(app={"*code*": "formal", "*slack*": "casual"})

    prof = resolve_profile("chrome", config)
    assert prof.tone == ""


def test_resolve_profile_empty_config():
    config = ProfilesConfig()

    prof = resolve_profile("chrome", config)
    assert prof.tone == ""


# --- the tone reaches the LLM as an extension, never a replacement ----------------


def _cleaner_daemon(tone: str):
    """A Daemon stub with just enough wiring to observe the prompt `_clean_dictation` builds."""
    daemon = Daemon.__new__(Daemon)
    cleaner = MagicMock()
    cleaner.cleanup.return_value = "out"
    daemon._cleaner = cleaner
    daemon._config = MagicMock()
    daemon._config.filters.disfluency.llm_system_prompt = "BASE RULES."
    Daemon._clean_dictation(daemon, "in", {}, tone)
    return cleaner.cleanup.call_args[0][1]


def test_a_known_tone_extends_the_base_prompt():
    prompt = _cleaner_daemon("casual")
    assert prompt.startswith("BASE RULES.")
    assert _TONE_INSTRUCTIONS["casual"] in prompt


def test_a_non_tone_value_is_used_as_a_complete_custom_prompt():
    """Section 4 of docs/how-to/app-profiles.md — a profile value may *be* the prompt.

    `"*obsidian*" = "Format as a bulleted markdown list..."` is documented to replace
    the system prompt rather than extend it, and nothing pinned that. Replacing is safe
    because `LlmCleaner`'s guards are output-side (`_length_ratio_ok`,
    `_tokens_preserved` compare input to output and never read the prompt), so a custom
    prompt cannot widen what cleanup may do to the user's words.
    """
    custom = "Format as a bulleted markdown list with short actionable items."
    assert _cleaner_daemon(custom) == custom


def test_verbatim_and_default_send_no_custom_prompt():
    assert _cleaner_daemon("verbatim") is None
    assert _cleaner_daemon("default") is None
    assert _cleaner_daemon("") is None
