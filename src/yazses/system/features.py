"""Capabilities registry — the single source of truth for `yazses features`.

Each capability knows: its display name, the config it reads to tell on/off, a
recommendation tier (so we can advise what to turn on), and — for the toggleable
ones — exactly which config key(s) `yazses features enable/disable` must write.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# Recommendation tiers (drive the advice column + enable/disable guard).
CORE = "core"            # always on, not toggleable
DEFAULT_ON = "on"        # on out of the box — keep it
RECOMMENDED = "rec"      # safe and useful — worth turning on
OPTIONAL = "opt"         # enable only if you want that capability
EXPERIMENTAL = "exp"     # known rough edges — not advised yet

_TIER_LABEL = {
    CORE: "core",
    DEFAULT_ON: "recommended (on by default)",
    RECOMMENDED: "recommended",
    OPTIONAL: "optional",
    EXPERIMENTAL: "experimental — not advised yet",
}


@dataclass(frozen=True)
class Feature:
    name: str
    on: bool
    note: str = ""
    slug: str = ""
    tier: str = OPTIONAL
    why: str = ""
    # config writes to flip it; empty = not toggleable from the CLI (core).
    on_writes: tuple = ()
    off_writes: tuple = ()

    @property
    def tier_label(self) -> str:
        return _TIER_LABEL.get(self.tier, self.tier)

    @property
    def toggleable(self) -> bool:
        return bool(self.on_writes)


@dataclass(frozen=True)
class _Def:
    slug: str
    name: str
    note: str
    tier: str
    why: str
    status: Callable
    on_writes: tuple = ()
    off_writes: tuple = ()


def _bool(section: str, key: str = "enabled") -> tuple:
    """A single boolean config key: enable writes true, disable writes false."""
    on = ((section, key, "true", False),)
    off = ((section, key, "false", False),)
    return on, off


# One row per capability. `status` reads the live config; `*_writes` are
# (section, key, value, quote) tuples handed to set_config_key.
def _registry() -> list[_Def]:
    s_on, s_off = _bool("streaming")
    c_on, c_off = _bool("commands")
    m_on, m_off = _bool("macros")
    r_on, r_off = _bool("revise")
    p_on, p_off = _bool("punch_in")
    pr_on, pr_off = _bool("prosody")
    e_on, e_off = _bool("endpoint")
    l_on, l_off = _bool("learning")
    o_on, o_off = _bool("overlay")
    pe_on, pe_off = _bool("personalize")
    co_on, co_off = _bool("cocktail")
    g_on, g_off = _bool("gaze")
    pg_on, pg_off = _bool("polyglot")
    llm_on, llm_off = _bool("filters.disfluency", "llm_enabled")
    dys_on, dys_off = _bool("accessibility", "dysfluency_friendly")
    vp_on, vp_off = _bool("commands", "voice_punctuation")
    conf_on, conf_off = _bool("confidence")
    ctx_on, ctx_off = _bool("context")
    se_on, se_off = _bool("commands", "spoken_edit")
    re_on, re_off = _bool("recall")
    ag_on, ag_off = _bool("agent")
    pi_on, pi_off = _bool("pilot")
    md_on, md_off = _bool("modality")
    cn_on, cn_off = _bool("continuum")

    return [
        _Def("dictation", "Dictation core", "always on", CORE,
             "The core hold-to-talk transcription. Can't be turned off.",
             lambda c: True),
        _Def("commands", "Voice commands", "[commands]", DEFAULT_ON,
             "Spoken commands like 'undo', 'save', 'delete last word'. Keep on.",
             lambda c: c.commands.enabled, c_on, c_off),
        _Def("voice-punctuation", "Voice punctuation", "[commands] voice_punctuation", OPTIONAL,
             "Say 'comma', 'period', 'new line', 'question mark' to insert marks. "
             "Off by default — those words also occur in ordinary speech.",
             lambda c: c.commands.voice_punctuation, vp_on, vp_off),
        _Def("undo", "Mid-Thought Undo", "[revise] — say 'scratch that'", DEFAULT_ON,
             "Say 'scratch that' to drop the last phrase. Keep on.",
             lambda c: c.revise.enabled, r_on, r_off),
        _Def("overlay", "Voice-activity overlay", "[overlay] — sonar rings", DEFAULT_ON,
             "Sonar rings near the cursor while you talk. Visual only; safe.",
             lambda c: c.overlay.enabled, o_on, o_off),
        _Def("dysfluency", "Dysfluency-Friendly", "[accessibility]", RECOMMENDED,
             "Collapses stutters/repeats (b-b-because→because). Try it if you "
             "stutter or have dysarthria.",
             lambda c: c.accessibility.dysfluency_friendly, dys_on, dys_off),
        _Def("punch-in", "Punch-In", "[punch_in] — re-speak to fix", OPTIONAL,
             "Re-speak a phrase to correct the last one. Handy, safe.",
             lambda c: c.punch_in.enabled, p_on, p_off),
        _Def("prosody", "Prosody Ink", "[prosody] — pause→¶, emphasis→bold", OPTIONAL,
             "Turns pauses into paragraphs and stressed words into bold.",
             lambda c: c.prosody.enabled, pr_on, pr_off),
        _Def("ghost-ahead", "Ghost Ahead", "[endpoint] — endpoint pre-warm", OPTIONAL,
             "Pre-warms the decoder for slightly faster first words.",
             lambda c: c.endpoint.enabled, e_on, e_off),
        _Def("macros", "Say-Macro", "[macros]", OPTIONAL,
             "Speak a trigger word to expand canned text. Needs setup.",
             lambda c: c.macros.enabled, m_on, m_off),
        _Def("read-back", "Read-Back Loop", "[tts] + [accessibility] read_back", OPTIONAL,
             "Speaks the transcript back to you (accessibility). Downloads a TTS "
             "model on first use.",
             lambda c: c.tts.enabled and c.accessibility.read_back != "off",
             (("tts", "enabled", "true", False), ("accessibility", "read_back", "final", True)),
             (("accessibility", "read_back", "off", True),)),
        _Def("personalize", "Voiceprint Mind (personalize)", "[personalize] — vocab bias", OPTIONAL,
             "Biases STT toward terms you use often. Local only.",
             lambda c: c.personalize.enabled, pe_on, pe_off),
        _Def("polyglot", "Polyglot Switch", "[polyglot] — mixed-language", OPTIONAL,
             "Handles dictation that mixes two languages.",
             lambda c: c.polyglot.enabled, pg_on, pg_off),
        _Def("streaming", "Streaming transcription", "[streaming]", OPTIONAL,
             "Injects words live as you speak (overtype). Off by default because "
             "it can fight some editors; enable if you want live text.",
             lambda c: c.streaming.enabled, s_on, s_off),
        _Def("learning", "Learning loop", "[learning] — yazses tune", OPTIONAL,
             "Records an encrypted local corpus so `yazses tune` can improve "
             "accuracy. Opt-in; nothing leaves your machine.",
             lambda c: c.learning.enabled, l_on, l_off),
        _Def("llm-cleanup", "LLM cleanup", "[filters.disfluency]", OPTIONAL,
             "Reformats dictation with a small offline LLM. Needs a model file.",
             lambda c: c.filters.disfluency.llm_enabled, llm_on, llm_off),
        _Def("confidence", "Confidence Ink", "[confidence] — mark unsure words", OPTIONAL,
             "Marks words Whisper was unsure about so you can re-pick them by voice "
             "instead of re-dictating. Uses Whisper's own confidence; local only.",
             lambda c: c.confidence.enabled, conf_on, conf_off),
        _Def("spoken-edit", "Spoken Edit Mode", "[commands] spoken_edit", OPTIONAL,
             "Edit the last dictation by voice ('change their to there', 'delete the "
             "last sentence'). Command-key gated. Off by default.",
             lambda c: c.commands.spoken_edit, se_on, se_off),
        _Def("context", "Context-Primed Dictation", "[context] — window/selection terms", OPTIONAL,
             "Primes STT with terms from the active window/selection so domain words "
             "are transcribed right. Read transiently, never stored. Off by default.",
             lambda c: c.context.enabled, ctx_on, ctx_off),
        _Def("continuum", "Accessibility Continuum", "[continuum] — quiet-speech mode", OPTIONAL,
             "Whisper/Low-Effort Mode lowers the mic gate so quiet or effortful speech "
             "is still captured (no shouting). Semantic capture is opt-in. Off by default.",
             lambda c: c.continuum.enabled, cn_on, cn_off),
        _Def("recall", "Spoken Recall & Scratch", "[recall] — query past dictation", OPTIONAL,
             "Search your past dictations ('yazses recall …') and capture spoken "
             "notes-to-self. Local corpus only; nothing leaves the machine. Off by default.",
             lambda c: c.recall.enabled, re_on, re_off),
        _Def("agent", "Voice-to-Tool (Spoken MCP)", "[agent] — run tools by voice", OPTIONAL,
             "Speak an intent to run allowlisted tools via MCP; state-changing tools "
             "ask first. Needs the 'agent' extra + a local planner model. Off by default.",
             lambda c: c.agent.enabled, ag_on, ag_off),
        _Def("pilot", "Voice Pilot (AT-SPI)", "[pilot] — click by voice", OPTIONAL,
             "Drive the desktop by voice via the accessibility tree ('click Save', "
             "'focus the terminal'). Linux + pyatspi; labels only, no screenshots. Off by default.",
             lambda c: c.pilot.enabled, pi_on, pi_off),
        _Def("cocktail", "Cocktail Filter (voice focus)", "[cocktail] — experimental", EXPERIMENTAL,
             "Tries to focus on your voice and reject other speakers. Currently "
             "over-rejects your OWN voice — leave off until improved.",
             lambda c: c.cocktail.enabled, co_on, co_off),
        _Def("modality", "Modality Role Router", "[modality] — multi-input, experimental", EXPERIMENTAL,
             "Routes each input to its fastest role (gaze→point, EMG→command, "
             "voice→dictation). Needs EMG/gaze hardware; experimental. Off by default.",
             lambda c: c.modality.enabled, md_on, md_off),
        _Def("gaze", "Glance-Type (camera)", "[gaze] — look-to-pane, experimental", EXPERIMENTAL,
             "Uses the webcam to route dictation to the pane you look at. "
             "Experimental; heavy deps.",
             lambda c: c.gaze.enabled, g_on, g_off),
    ]


def feature_status(cfg) -> list[Feature]:
    """Return every user-facing capability and whether it's enabled in *cfg*."""
    return [
        Feature(
            name=d.name, on=bool(d.status(cfg)), note=d.note, slug=d.slug,
            tier=d.tier, why=d.why, on_writes=d.on_writes, off_writes=d.off_writes,
        )
        for d in _registry()
    ]


def find_feature(cfg, slug: str) -> Feature | None:
    """Look up one capability by its CLI slug (e.g. 'read-back')."""
    slug = slug.strip().lower()
    for f in feature_status(cfg):
        if f.slug == slug:
            return f
    return None


def toggleable_slugs() -> list[str]:
    return [d.slug for d in _registry() if d.on_writes]
