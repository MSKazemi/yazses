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
    # A concrete "how to use it" example (spoken trigger or command) shown by
    # `yazses features info <slug>`.
    example: str = ""
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
    example: str = ""


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
    br_on, br_off = _bool("bridge")
    tr_on, tr_off = _bool("translate")
    af_on, af_off = _bool("affect")
    dn_on, dn_off = _bool("denoise")
    pd_on, pd_off = _bool("predict")
    vg_on, vg_off = _bool("voiceguard")
    sc_on, sc_off = _bool("scribe")
    rg_on, rg_off = _bool("rag")
    cd_on, cd_off = _bool("codec")
    hl_on, hl_off = _bool("hallucination")
    sn_on, sn_off = _bool("snippets")
    ph_on, ph_off = _bool("phonetic")
    mp_on, mp_off = _bool("voiceprint", "multi_profile")
    as_on, as_off = _bool("autostop")
    mg_on, mg_off = _bool("mousegrid")
    co_on2, co_off2 = _bool("code")
    ma_on, ma_off = _bool("math")
    ww_on, ww_off = _bool("wakeword")
    vh_on, vh_off = _bool("voicehealth")
    ch_on, ch_off = _bool("coach")
    sp_on, sp_off = _bool("smartpaste")
    scr_on, scr_off = _bool("scrub")
    rf_on, rf_off = _bool("reflow")
    ap_on, ap_off = _bool("acoustic_profiles")
    st_on, st_off = _bool("sentiment")
    pn_on, pn_off = _bool("pronunciation")
    rbc_on, rbc_off = _bool("tts", "clone_voice")
    ge_on, ge_off = _bool("gesture")
    ip_on, ip_off = _bool("interpret")

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
        _Def("wakeword", "Wake-Word Activation", "[wakeword] — 'Hey Yaz', experimental", EXPERIMENTAL,
             "Start dictation hands-free by saying a keyword. Always-listening (local only, "
             "nothing stored until it fires). Needs the wakeword extra. Off by default.",
             lambda c: c.wakeword.enabled, ww_on, ww_off),
        _Def("gesture", "Gesture Chords", "[gesture] — multi-input chords", OPTIONAL,
             "Bind chords (held key + nod / second key / sEMG squeeze) to actions like send or "
             "switch profile. Sensors need their own extras. Off by default.",
             lambda c: c.gesture.enabled, ge_on, ge_off),
        _Def("interpret", "Two-Way Interpreter", "[interpret] — face-to-face translate", OPTIONAL,
             "Face-to-face mode: two speakers alternate and each turn is translated into the "
             "other language. Reuses the offline translate + TTS path. Off by default.",
             lambda c: c.interpret.enabled, ip_on, ip_off),
        _Def("pronunciation", "Pronunciation Feedback", "[pronunciation] — L2 practice", OPTIONAL,
             "Practice mode: dictate a target phrase and get per-phoneme good/fair/poor "
             "feedback for accent training. Needs the pronunciation extra. Off by default.",
             lambda c: c.pronunciation.enabled, pn_on, pn_off),
        _Def("readback_clone", "Personal Read-Back Voice", "[tts] clone_voice — your own voice", OPTIONAL,
             "Read the transcript back in a clone of your own voice from a short enrollment. "
             "Permissive OpenVoice V2 default; embedding stays in the encrypted corpus. Off by default.",
             lambda c: c.tts.clone_voice, rbc_on, rbc_off),
        _Def("acoustic_profiles", "Acoustic Profiles", "[acoustic_profiles] — scene-adaptive", OPTIONAL,
             "Detects your environment (quiet/café/car/meeting) and auto-tunes the mic gate + "
             "noise suppression. Needs the acoustic extra (scene tagger). Off by default.",
             lambda c: c.acoustic_profiles.enabled, ap_on, ap_off),
        _Def("sentiment", "Mood Ledger", "[sentiment] — private mood journal", OPTIONAL,
             "Tags each dictation with an emotion and builds a private mood-over-time view. "
             "Labels stay in the encrypted corpus. Needs the sentiment extra. Off by default.",
             lambda c: c.sentiment.enabled, st_on, st_off),
        _Def("reflow", "Dictation Reflow", "[reflow] — 'structure this' → outline", OPTIONAL,
             "Say 'structure this' to rewrite your last ramble into bullets and action items. "
             "Pure heuristic; a local SLM refines it via the reflow extra. Off by default.",
             lambda c: c.reflow.enabled, rf_on, rf_off),
        _Def("smartpaste", "Smart-Paste", "[smartpaste] — adapt syntax to app", OPTIONAL,
             "Adapts injected syntax to the target app (markdown bullets, code casing, URL "
             "autolinking) using local window info. No model. Off by default.",
             lambda c: c.smartpaste.enabled, sp_on, sp_off),
        _Def("scrub", "Audio-Anchored Scrubbing", "[scrub] — replay/pinpoint a word", OPTIONAL,
             "Keeps word-level timestamps so you can replay what you said or pick a word to "
             "re-dictate just that word. Audio stays in RAM. Off by default.",
             lambda c: c.scrub.enabled, scr_on, scr_off),
        _Def("coach", "Speaking Coach", "[coach] — private speech analytics", OPTIONAL,
             "Private on-device analytics of your dictation: filler rate, words-per-minute, "
             "vocabulary diversity, trend. From the encrypted corpus only. Off by default.",
             lambda c: c.coach.enabled, ch_on, ch_off),
        _Def("voicehealth", "Vocal-Strain Guard", "[voicehealth] — break reminders", OPTIONAL,
             "Advises a break when your voice shows rising strain (jitter/shimmer/HNR) over a "
             "session. Advisory only, not diagnostic. Off by default.",
             lambda c: c.voicehealth.enabled, vh_on, vh_off),
        _Def("code", "Spoken Code Mode", "[code] — dictate code syntax", OPTIONAL,
             "Dictate code: spoken symbols become punctuation and word-groups become cased "
             "identifiers (snake/camel/pascal). Activate via a command key. Off by default.",
             lambda c: c.code.enabled, co_on2, co_off2),
        _Def("math", "Spoken Math (LaTeX)", "[math] — dictate equations", OPTIONAL,
             "Dictate math and inject LaTeX ('x squared plus y squared' -> x^{2} + y^{2}). "
             "Common cases pure; nested expressions need the mathspeech extra. Off by default.",
             lambda c: c.math.enabled, ma_on, ma_off),
        _Def("autostop", "Hands-Free Auto-Stop", "[autostop] — tap & speak", OPTIONAL,
             "Tap once and speak; recording auto-stops when you finish (silence timeout + "
             "duration cap). Semantic end-of-turn needs the turn extra. Off by default.",
             lambda c: c.autostop.enabled, as_on, as_off),
        _Def("mousegrid", "Voice Mouse Grid", "[mousegrid] — click by voice", OPTIONAL,
             "Drive the cursor and click by voice via a numbered grid ('three, seven, click') "
             "where no accessibility tree exists. Reuses the overlay. Off by default.",
             lambda c: c.mousegrid.enabled, mg_on, mg_off),
        _Def("multiprofile", "Multi-User Profiles", "[voiceprint] multi_profile", OPTIONAL,
             "On a shared machine, loads each enrolled speaker's own vocab/hotkey/cleanup "
             "from their voiceprint — no manual switching. Needs the voiceprint extra + 2+ "
             "enrolled profiles. Off by default.",
             lambda c: c.voiceprint.multi_profile, mp_on, mp_off),
        _Def("snippets", "Voice Snippets", "[snippets] — spoken text expander", OPTIONAL,
             "Say a trigger ('insert my signature') to type a stored template. Add entries "
             "under [snippets]. Off by default.",
             lambda c: c.snippets.enabled, sn_on, sn_off),
        _Def("phonetic", "Phonetic Corrector", "[phonetic] — fix mis-heard names", OPTIONAL,
             "Fixes mis-heard proper nouns by sound against your vocabulary "
             "('Cuber Netties'->'Kubernetes'). Pure, conservative. Off by default.",
             lambda c: c.phonetic.enabled, ph_on, ph_off),
        _Def("hallucination", "Hallucination Guard", "[hallucination] — drop ghost text", OPTIONAL,
             "Drops Whisper's fabricated text on silence/noise (the phantom 'Thank you.', "
             "'please subscribe', or looped phrases) before it's typed. Pure, conservative. Off.",
             lambda c: c.hallucination.enabled, hl_on, hl_off),
        _Def("codec", "Codec Streaming (low latency)", "[codec] — Kyutai/Mimi engine", OPTIONAL,
             "Routes decoding to a streaming neural-codec engine for lower latency. "
             "Needs the codec extra (Kyutai/Mimi); English/French-centric. Off by default.",
             lambda c: c.codec.enabled, cd_on, cd_off),
        _Def("rag", "Ask My Notes (voice RAG)", "[rag] — cited answers from local docs", OPTIONAL,
             "Ask a question by voice and get an answer grounded in — and citing — your own "
             "local notes/docs. Needs the rag extra (embeddings + index). Off by default.",
             lambda c: c.rag.enabled, rg_on, rg_off),
        _Def("scribe", "Meeting Scribe", "[scribe] — who-said-what transcript", OPTIONAL,
             "Records a multi-speaker meeting transcript on-device, tagging you as 'You' "
             "and others as Speaker N. Needs the scribe extra (diarization). Off by default.",
             lambda c: c.scribe.enabled, sc_on, sc_off),
        _Def("denoise", "Noise Suppression", "[denoise] — clean mic before STT", OPTIONAL,
             "Removes background noise/echo before transcription so dictation works in "
             "noisy rooms. Needs the denoise extra (DeepFilterNet). Off by default.",
             lambda c: c.denoise.enabled, dn_on, dn_off),
        _Def("predict", "Predictive Completion", "[predict] — voice autosuggest", OPTIONAL,
             "A tiny local model suggests the rest of your sentence; accept by voice. "
             "Needs the predict extra + a model. Off by default.",
             lambda c: c.predict.enabled, pd_on, pd_off),
        _Def("affect", "Tone-Aware Formatting", "[affect] — tone → !/?", OPTIONAL,
             "Adds ! or ? based on your vocal tone (excited/question), beyond pause "
             "punctuation. Needs the affect extra for detection; conservative by default. Off.",
             lambda c: c.affect.enabled, af_on, af_off),
        _Def("translate", "Speech Translation", "[translate] — dictate L1, type English", OPTIONAL,
             "Speak another language and type English (Whisper's built-in translate; no "
             "extra download). Other targets need the seamless extra. Off by default.",
             lambda c: c.translate.enabled, tr_on, tr_off),
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
        _Def("voiceguard", "Voice Guard (biometric + anti-spoof)", "[voiceguard] — experimental", EXPERIMENTAL,
             "Types only when the live speaker matches your enrolled voiceprint and the "
             "audio isn't a recording/synthetic. Needs enrollment + the voiceguard extra; "
             "false-reject risk (fail-open by default). Off by default.",
             lambda c: c.voiceguard.enabled, vg_on, vg_off),
        _Def("bridge", "Glasses↔Desktop Bridge", "[bridge] — phone/glasses mic, experimental", EXPERIMENTAL,
             "Dictate from a paired phone/glasses; the desktop does STT + typing. "
             "Reuses the remote transport; local link only. Experimental. Off by default.",
             lambda c: c.bridge.enabled, br_on, br_off),
        _Def("modality", "Modality Role Router", "[modality] — multi-input, experimental", EXPERIMENTAL,
             "Routes each input to its fastest role (gaze→point, EMG→command, "
             "voice→dictation). Needs EMG/gaze hardware; experimental. Off by default.",
             lambda c: c.modality.enabled, md_on, md_off),
        _Def("gaze", "Glance-Type (camera)", "[gaze] — look-to-pane, experimental", EXPERIMENTAL,
             "Uses the webcam to route dictation to the pane you look at. "
             "Experimental; heavy deps.",
             lambda c: c.gaze.enabled, g_on, g_off),
    ]


# A concrete "how to use it" example per capability, keyed by slug. Kept beside the
# registry (still a single source of truth) and enforced complete by
# tests/test_features_examples.py so every new feature ships with a usage example.
_EXAMPLES: dict[str, str] = {
    "dictation": "Hold your hotkey and speak; release to type.",
    "commands": "Hold the command key and say 'undo' or 'save'.",
    "voice-punctuation": "Say 'hello comma world period' → 'hello, world.'",
    "undo": "Say 'scratch that' to drop the last phrase.",
    "overlay": "Watch the sonar rings near the cursor while you talk.",
    "dysfluency": "Say 'b-b-because' → 'because' (stutters collapsed).",
    "punch-in": "Re-speak a phrase right after to correct the last one.",
    "prosody": "Pause between thoughts → a new paragraph; stress a word → bold.",
    "ghost-ahead": "Nothing to do — the decoder pre-warms for faster first words.",
    "macros": "Say your trigger word to expand canned text (configure [macros]).",
    "read-back": "yazses features enable read-back — then it speaks the transcript back.",
    "personalize": "yazses features enable personalize — biases STT to your frequent terms.",
    "polyglot": "Set [polyglot] pair='fa-en'; dictate mixing the two languages.",
    "streaming": "yazses features enable streaming — text appears as you speak.",
    "learning": "yazses features enable learning; then 'yazses tune' to review proposals.",
    "llm-cleanup": "yazses features enable llm-cleanup — offline LLM tidies dictation.",
    "confidence": "See the low-confidence word count in 'yazses status'.",
    "spoken-edit": "Say 'delete last sentence' or 'capitalize that'.",
    "context": "Open a file in your editor; dictation is primed from its LSP context.",
    "continuum": "yazses features enable continuum — whisper-quiet speech still registers.",
    "wakeword": "Say your wake word to start dictation hands-free (--force).",
    "gesture": "Hold the hotkey and nod to send (bind chords in [gesture]).",
    "interpret": "Set [interpret] pair='en-es'; each speaker's turn is translated.",
    "pronunciation": "Practice mode: dictate a phrase, see per-phoneme good/fair/poor.",
    "readback_clone": "Enroll once; read-back then uses a clone of your own voice.",
    "acoustic_profiles": "Move to a café — the mic gate + denoise auto-adapt.",
    "sentiment": "yazses features enable sentiment — builds a private mood-over-time view.",
    "reflow": "Ramble, then say 'structure this' → a bulleted outline.",
    "smartpaste": "Dictate into markdown vs a terminal — syntax adapts to the app.",
    "scrub": "Say a word to replay its audio or re-dictate just that word.",
    "coach": "yazses features enable coach — see filler rate + words-per-minute.",
    "voicehealth": "Get a break reminder when your voice shows rising strain.",
    "code": "Dictate 'def foo open paren' → 'def foo(' in code mode.",
    "math": "Say 'x squared plus y squared' → 'x^{2} + y^{2}'.",
    "autostop": "Tap once and speak; recording stops when you finish.",
    "mousegrid": "Say a grid number to move the cursor, then 'click'.",
    "multiprofile": "Each enrolled speaker loads their own vocab/hotkey automatically.",
    "snippets": "Say 'insert my signature' to type a stored template.",
    "phonetic": "'Cuber Netties' is auto-corrected to 'Kubernetes'.",
    "hallucination": "Nothing to do — fabricated silence transcripts are dropped.",
    "codec": "yazses features enable codec — streaming decode engine selection.",
    "rag": "Ask 'what did I note about the budget?' to recall past dictation.",
    "scribe": "Meeting mode: turns are diarized into a labelled transcript.",
    "denoise": "yazses features enable denoise — background noise is filtered pre-STT.",
    "predict": "Accept the greyed-ahead completion by continuing to speak.",
    "affect": "Excited speech → an exclamation mark; questions → a question mark.",
    "translate": "yazses features enable translate — speak any language, type English.",
    "recall": "yazses recall 'the address I dictated yesterday'.",
    "agent": "Say 'create a calendar event tomorrow at 3' (allowlisted tools).",
    "pilot": "Say 'click the Save button' to drive the focused app via AT-SPI.",
    "cocktail": "yazses features enable cocktail --force — filters other voices (experimental).",
    "voiceguard": "yazses features enable voiceguard --force — only your voice dictates.",
    "bridge": "Pair smart glasses to relay audio to the desktop (experimental).",
    "modality": "Route dictation vs commands to different targets by role.",
    "gaze": "Glance at a screen zone to choose where the next dictation lands.",
}


def feature_status(cfg) -> list[Feature]:
    """Return every user-facing capability and whether it's enabled in *cfg*."""
    return [
        Feature(
            name=d.name, on=bool(d.status(cfg)), note=d.note, slug=d.slug,
            tier=d.tier, why=d.why, on_writes=d.on_writes, off_writes=d.off_writes,
            example=_EXAMPLES.get(d.slug, ""),
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
