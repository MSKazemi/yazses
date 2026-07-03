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
    itn_on, itn_off = _bool("itn")
    rd_on, rd_off = _bool("redaction")
    fa_on, fa_off = _bool("fieldaware")
    cvs_on, cvs_off = _bool("learning", "anonymize_audio")
    cp_on, cp_off = _bool("compose")
    gec_on, gec_off = _bool("gec")
    sg_on, sg_off = _bool("screengrounded")
    hp_on, hp_off = _bool("headpointer")
    lr_on, lr_off = _bool("lipread")
    sn2_on, sn2_off = _bool("sign")
    sym_on, sym_off = _bool("commands", "symbols")
    cv_on, cv_off = _bool("convert")
    tmp_on, tmp_off = _bool("temporal")
    sr_on, sr_off = _bool("commands", "self_repair")
    ss_on, ss_off = _bool("spreadsheet")
    clh_on, clh_off = _bool("cliphistory")
    ag2_on, ag2_off = _bool("audioguard")
    cnd_on, cnd_off = _bool("condense")
    slf_on, slf_off = _bool("slotfill")
    cs2_on, cs2_off = _bool("cmdspotter")
    csf_on, csf_off = _bool("cmdsafety")
    srx_on, srx_off = _bool("spokenregex")
    mk_on, mk_off = _bool("markup")
    fr_on, fr_off = _bool("findreplace")
    hw_on, hw_off = _bool("hotwords")
    wc_on, wc_off = _bool("windowctl")
    ci_on, ci_off = _bool("cite")
    lrt_on, lrt_off = _bool("langroute")
    lat_on, lat_off = _bool("latency")
    diz_on, diz_off = _bool("diarize")
    spl_on, spl_off = _bool("spelling")
    gv_on, gv_off = _bool("gitvoice")
    rk_on, rk_off = _bool("reask")
    vbt_on, vbt_off = _bool("verbatim")
    cdx_on, cdx_off = _bool("corrdict")
    fo_on, fo_off = _bool("fileopen")
    jmp_on, jmp_off = _bool("jump")
    shp_on, shp_off = _bool("shellpipe")
    ri_on, ri_off = _bool("recimport")
    cwp_on, cwp_off = _bool("crowdproof")
    chd_on, chd_off = _bool("chords")
    cmp_on, cmp_off = _bool("compute")
    cst_on, cst_off = _bool("casetransform")
    apr_on, apr_off = _bool("autopair")
    tl_on, tl_off = _bool("timeline")
    bm_on, bm_off = _bool("bookmarks")
    tbl_on, tbl_off = _bool("tablecsv")
    wg_on, wg_off = _bool("wordgoal")
    vt_on, vt_off = _bool("voicetimer")
    fp_on, fp_off = _bool("focusprofile")
    vj_on, vj_off = _bool("vocaljoystick")
    ec_on, ec_off = _bool("earcon")
    sv_on, sv_off = _bool("spatialvad")
    pp_on, pp_off = _bool("prosodypunct")
    hes_on, hes_off = _bool("hesitation")
    cg_on, cg_off = _bool("contour")
    bre_on, bre_off = _bool("breath")
    wm_on, wm_off = _bool("whispermode")
    ms_on, ms_off = _bool("mouthswitch")
    iv_on, iv_off = _bool("involuntary")
    mv_on, mv_off = _bool("morsevox")
    ckd_on, ckd_off = _bool("checkdigit")
    sb_on, sb_off = _bool("sembr")
    ac_on, ac_off = _bool("acronyms")
    stg_on, stg_off = _bool("styleguard")
    sug_on, sug_off = _bool("suggestmode")
    scp_on, scp_off = _bool("screenplay")
    srs_on, srs_off = _bool("srscap")
    dv_on, dv_off = _bool("diagramvox")
    pb_on, pb_off = _bool("proofback")
    hs_on, hs_off = _bool("hatselect")
    trl_on, trl_off = _bool("translit")
    bo_on, bo_off = _bool("brailleout")
    ol_on, ol_off = _bool("outline")

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
        _Def("hatselect", "HatSelect Structural Editing", "[hatselect] — address tokens by spoken label",
             EXPERIMENTAL,
             "Every visible token gets a spoken label so you can edit structurally — 'select alpha to "
             "charlie', 'delete bravo' — without cursor motions (Cursorless-style). Off by default.",
             lambda c: c.hatselect.enabled, hs_on, hs_off),
        _Def("translit", "Transliteration", "[translit] — romanized → native script", OPTIONAL,
             "Dictate your native language in Latin letters ('salam, chetori?') and inject the native "
             "script — Whisper nails romanized phonetics where native audio fails. Off by default.",
             lambda c: c.translit.enabled, trl_on, trl_off),
        _Def("brailleout", "BrailleOut", "[brailleout] — dictation as Unicode Braille", OPTIONAL,
             "Emit Grade-2 (UEB) Unicode Braille cells so a Braille-display or DeafBlind user gets "
             "dictation directly in Braille — no screen-reader round-trip. Off by default.",
             lambda c: c.brailleout.enabled, bo_on, bo_off),
        _Def("outline", "Spoken Outline", "[outline] — voice-driven outline tree", OPTIONAL,
             "Say 'new item / indent / promote / collapse' to drive a live outline tree and render "
             "it as Markdown or OPML — structured idea capture by voice. Off by default.",
             lambda c: c.outline.enabled, ol_on, ol_off),
        _Def("diagramvox", "Diagrams-as-Code by Voice", "[diagramvox] — dictate a flowchart", OPTIONAL,
             "Dictate a flowchart ('start goes to login; login goes to dashboard if success') and get "
             "Mermaid/Graphviz source — draw diagrams without a mouse or canvas. Off by default.",
             lambda c: c.diagramvox.enabled, dv_on, dv_off),
        _Def("proofback", "Interruptible Proofreading", "[proofback] — barge-in read-back editing",
             OPTIONAL,
             "Interrupt the spoken read-back ('stop — change that') and the cursor lands on the exact "
             "word being read — eyes-free proofreading. Off by default.",
             lambda c: c.proofback.enabled, pb_on, pb_off),
        _Def("screenplay", "Screenplay Auto-Format", "[screenplay] — dialogue → Fountain", OPTIONAL,
             "Formats dictated scenes and dialogue as Fountain screenplay markup (scene headings, "
             "character cues, smart curly quotes). For screenwriters and playwrights. Off by default.",
             lambda c: c.screenplay.enabled, scp_on, scp_off),
        _Def("srscap", "Spaced-Repetition Capture", "[srscap] — voice → Anki cloze cards", OPTIONAL,
             "Say 'remember that X is Y' mid-dictation and it makes a local Anki cloze study card, "
             "scheduled by SM-2 — study material captured in the flow of work. Off by default.",
             lambda c: c.srscap.enabled, srs_on, srs_off),
        _Def("styleguard", "Style-Consistency Enforcer", "[styleguard] — apply your house style", OPTIONAL,
             "Applies your style sheet to each dictation ('e-mail' not 'email', US spelling, 'cannot' "
             "not 'can not') so terminology stays consistent — a Vale-lite pass. Off by default.",
             lambda c: c.styleguard.enabled, stg_on, stg_off),
        _Def("suggestmode", "Suggestion-Mode Dictation", "[suggestmode] — edits as tracked changes",
             OPTIONAL,
             "Emits dictated edits as CriticMarkup tracked changes ({++add++}, {--cut--}, {~~old~>"
             "new~~}) for an editor to review later, instead of applying them. Off by default.",
             lambda c: c.suggestmode.enabled, sug_on, sug_off),
        _Def("sembr", "Semantic Line Breaks", "[sembr] — one clause per source line", OPTIONAL,
             "Breaks dictated prose one clause per line so git diffs and merges stay clean — the "
             "rendered output is unchanged. For anyone versioning prose in git. Off by default.",
             lambda c: c.sembr.enabled, sb_on, sb_off),
        _Def("acronyms", "Acronym & Glossary Manager", "[acronyms] — expand on first use", OPTIONAL,
             "Expands an acronym on first mention ('World Health Organization (WHO)'), contracts it "
             "after, and warns about acronyms you never defined. Off by default.",
             lambda c: c.acronyms.enabled, ac_on, ac_off),
        _Def("morsevox", "Vocal Morse", "[morsevox] — two-tone Morse text entry", EXPERIMENTAL,
             "Type by Morse using two vocal sounds (short/long) — full text from a single reliable "
             "vocalization, with adaptive timing. For locked-in/minimal-ability users. Off by default.",
             lambda c: c.morsevox.enabled, mv_on, mv_off),
        _Def("checkdigit", "Checksum-Validated Entry", "[checkdigit] — verify dictated ID numbers",
             RECOMMENDED,
             "Runs dictated account/ID numbers (credit card, IBAN, ISBN) through their check-digit "
             "algorithm and flags a mis-heard digit before it lands — with fix suggestions. Off by "
             "default.",
             lambda c: c.checkdigit.enabled, ckd_on, ckd_off),
        _Def("mouthswitch", "Mouth-Sound Switch Access", "[mouthswitch] — scan-and-select by mouth sounds",
             EXPERIMENTAL,
             "Drive a scanning selector with non-verbal mouth sounds ('pop' = advance, cluck = "
             "select) — the switch-access method for people who can't produce reliable speech. Off "
             "by default.",
             lambda c: c.mouthswitch.enabled, ms_on, ms_off),
        _Def("involuntary", "Involuntary-Vocalization Excision", "[involuntary] — drop coughs & sneezes",
             OPTIONAL,
             "Detects and deletes involuntary sounds (cough, throat-clear, sneeze) from the stream so "
             "they never become garbage tokens or spurious commands. Off by default.",
             lambda c: c.involuntary.enabled, iv_on, iv_off),
        _Def("breath", "Breath-Paced Dictation", "[breath] — segment by natural breath groups", OPTIONAL,
             "Uses your natural breath onsets as sentence/paragraph boundaries, so dictation chunks "
             "the way you actually breathe — even without silent pauses. Off by default.",
             lambda c: c.breath.enabled, bre_on, bre_off),
        _Def("whispermode", "Whisper-Aware Mode", "[whispermode] — accurate whispered dictation",
             OPTIONAL,
             "Detects when you drop to a whisper and adapts gain, VAD, and the STT prompt so quiet "
             "dictation stays accurate in shared or private spaces. Off by default.",
             lambda c: c.whispermode.enabled, wm_on, wm_off),
        _Def("hesitation", "Hesitation-Hold Endpointing", "[hesitation] — don't cut off filled pauses",
             RECOMMENDED,
             "Holds the turn open when you trail off with a filled hesitation ('annnd… uhh…') instead "
             "of cutting you off — for anyone who thinks out loud. Off by default.",
             lambda c: c.hesitation.enabled, hes_on, hes_off),
        _Def("contour", "Pitch-Contour Gestures", "[contour] — hum a shape to run a command",
             EXPERIMENTAL,
             "Hum a pitch shape as a word-free command: rising = confirm, falling = cancel, rise-fall "
             "= undo. Language-independent, works in noise. Off by default.",
             lambda c: c.contour.enabled, cg_on, cg_off),
        _Def("spatialvad", "Beam-Steered Spatial VAD", "[spatialvad] — 2-mic direction gate", OPTIONAL,
             "With a stereo/2-mic input, drops any sound not coming from your seat (a TV, a "
             "colleague) by its arrival direction — enrollment-free, complements Cocktail Filter. "
             "Off by default.",
             lambda c: c.spatialvad.enabled, sv_on, sv_off),
        _Def("prosodypunct", "Prosodic Auto-Punctuation", "[prosodypunct] — punctuation from prosody",
             RECOMMENDED,
             "Inserts periods, commas, and question marks from how you speak (pauses, pitch) — no "
             "need to say 'comma' or 'period'. Off by default.",
             lambda c: c.prosodypunct.enabled, pp_on, pp_off),
        _Def("vocaljoystick", "Vocal Joystick", "[vocaljoystick] — analog cursor control by voice",
             EXPERIMENTAL,
             "Continuous cursor/scroll control by sustaining vowels — 'ahh' right, 'eee' up, louder "
             "= faster, pitch-jump = click. No words. For severe motor impairment. Off by default.",
             lambda c: c.vocaljoystick.enabled, vj_on, vj_off),
        _Def("earcon", "Earcon Feedback", "[earcon] — non-speech state tones", OPTIONAL,
             "Tiny structured tones signal daemon state eyes-free (rising motif = recording, buzz = "
             "low confidence, chime = command done) — faster than spoken read-back. Off by default.",
             lambda c: c.earcon.enabled, ec_on, ec_off),
        _Def("voicetimer", "Local Voice Timer", "[voicetimer] — offline timers & break reminders", OPTIONAL,
             "Set a timer or break reminder by voice ('set a timer for 25 minutes'), announced by "
             "read-back — fully offline, no phone or cloud assistant. Off by default.",
             lambda c: c.voicetimer.enabled, vt_on, vt_off),
        _Def("focusprofile", "Focus-Class Auto-Profile", "[focusprofile] — auto grammar per app class",
             RECOMMENDED,
             "Auto-selects the dictation profile from the focused window's class (terminal→shell, "
             "editor→code, browser→prose) so you never switch profiles by hand. Off by default.",
             lambda c: c.focusprofile.enabled, fp_on, fp_off),
        _Def("tablecsv", "Spoken Table Entry", "[tablecsv] — dictate rows of data", OPTIONAL,
             "Bulk data entry by voice: 'row: Ada, 1815, London' types tab/comma cells and 'next "
             "row' moves down. For spreadsheets and forms. Off by default.",
             lambda c: c.tablecsv.enabled, tbl_on, tbl_off),
        _Def("wordgoal", "Word-Count & Goal Tracker", "[wordgoal] — track your writing goal", OPTIONAL,
             "Counts dictated words and tracks a goal: say 'goal 500 words', then 'how many words "
             "so far?' for spoken progress. Off by default.",
             lambda c: c.wordgoal.enabled, wg_on, wg_off),
        _Def("timeline", "Voice Undo/Redo Timeline", "[timeline] — undo YazSes output by voice", RECOMMENDED,
             "Undo/redo YazSes's own output across bursts by voice — 'undo the last sentence', "
             "'redo' — even where the app's Ctrl+Z is unreliable. Off by default.",
             lambda c: c.timeline.enabled, tl_on, tl_off),
        _Def("bookmarks", "Session Bookmarks", "[bookmarks] — checkpoints in a long session", OPTIONAL,
             "Drop named anchors in a long dictation ('bookmark here as intro') and jump back "
             "('jump to my last bookmark') after a break. Off by default.",
             lambda c: c.bookmarks.enabled, bm_on, bm_off),
        _Def("casetransform", "Voice Case Transform", "[casetransform] — recase the selection", OPTIONAL,
             "Recase the selected text by voice: 'make this snake_case', 'Title Case', 'SHOUT', "
             "'camelCase'. Off by default.",
             lambda c: c.casetransform.enabled, cst_on, cst_off),
        _Def("autopair", "Auto-Pairing & Wrap", "[autopair] — balance brackets, wrap selection", OPTIONAL,
             "Balances brackets/quotes in dictated code and wraps a selection ('wrap this in "
             "parens'). Off by default.",
             lambda c: c.autopair.enabled, apr_on, apr_off),
        _Def("chords", "Chorded Shortcut Synthesis", "[chords] — any keyboard shortcut by voice", RECOMMENDED,
             "Say any shortcut and it's pressed — 'press control shift P', 'escape twice', 'hit "
             "F5' — no macro registration needed. Off by default.",
             lambda c: c.chords.enabled, chd_on, chd_off),
        _Def("compute", "Inline Compute", "[compute] — types the answer", RECOMMENDED,
             "Say 'what's 15% of 240' and it types 36. On-device arithmetic and percentages, no "
             "cloud calculator. Off by default.",
             lambda c: c.compute.enabled, cmp_on, cmp_off),
        _Def("recimport", "Recording Import", "[recimport] — transcribe existing files", OPTIONAL,
             "Batch-transcribe voice memos/lectures/meetings offline to .txt/.srt/.vtt with "
             "timestamps — your audio archive becomes searchable. Off by default.",
             lambda c: c.recimport.enabled, ri_on, ri_off),
        _Def("crowdproof", "Crowd-Proof Dictation", "[crowdproof] — dictate in a crowd", EXPERIMENTAL,
             "Reconstructs your enrolled voice out of overlapping babble before STT, so dictation "
             "survives an open-plan office or café. Needs the crowdproof extra. Off by default.",
             lambda c: c.crowdproof.enabled, cwp_on, cwp_off),
        _Def("jump", "Voice Jump-to-Symbol", "[jump] — navigate code by voice", OPTIONAL,
             "'Jump to function tokenize', 'go to line 240' → the editor moves there (fuzzy symbol "
             "match, or a search fallback). Off by default.",
             lambda c: c.jump.enabled, jmp_on, jmp_off),
        _Def("shellpipe", "Spoken Shell Pipeline Builder", "[shellpipe] — build pipelines, preview first", OPTIONAL,
             "Speak stages ('list files, pipe to grep error, pipe to word count') → renders 'ls | "
             "grep error | wc -l' as text; nothing runs until you say 'run it'. Off by default.",
             lambda c: c.shellpipe.enabled, shp_on, shp_off),
        _Def("corrdict", "Self-Learning Correction Dictionary", "[corrdict] — auto-fix your recurring errors", RECOMMENDED,
             "Learns the ASR errors you keep fixing (e.g. 'yaz says' → 'YazSes') and applies them "
             "automatically to future output. High-precision, from your own edits. Off by default.",
             lambda c: c.corrdict.enabled, cdx_on, cdx_off),
        _Def("fileopen", "Voice Fuzzy File Open", "[fileopen] — open files by voice", OPTIONAL,
             "'Open the notes about the mortgage' → fuzzy-matches your local files and opens the "
             "best one. Mouse-free. Off by default.",
             lambda c: c.fileopen.enabled, fo_on, fo_off),
        _Def("reask", "Confidence-Gated Re-Ask", "[reask] — resolve uncertain words", RECOMMENDED,
             "Instead of injecting a low-confidence guess, holds just the uncertain word and asks "
             "you to pick or repeat it — closing the correction loop. Off by default.",
             lambda c: c.reask.enabled, rk_on, rk_off),
        _Def("verbatim", "Verbatim / Autoformat Toggle", "[verbatim] — freeze formatting on command", RECOMMENDED,
             "Say 'dictate verbatim' to freeze all formatting (ITN, punctuation, reflow) for exact "
             "capture, 'resume formatting' to restore — mid-burst. Off by default.",
             lambda c: c.verbatim.enabled, vbt_on, vbt_off),
        _Def("spelling", "Phonetic Spelling Mode", "[spelling] — NATO → exact characters", RECOMMENDED,
             "A character-exact mode for passwords/codes/IDs: 'capital alpha bravo double lima' → "
             "'Abll'. Handles digits and symbols. Off by default.",
             lambda c: c.spelling.enabled, spl_on, spl_off),
        _Def("gitvoice", "Voice Git Choreographer", "[gitvoice] — safe git by voice", OPTIONAL,
             "Drive git by voice via a structured grammar; destructive ops (force-push, reset "
             "--hard) wait for a spoken confirm and the undo is always spoken. Off by default.",
             lambda c: c.gitvoice.enabled, gv_on, gv_off),
        _Def("latency", "Adaptive Latency Governor", "[latency] — load-aware decode", RECOMMENDED,
             "Keeps dictation responsive under CPU load (lighter model/beam) and losslessly "
             "faster when idle (speculative decoding). Needs the latency extra for a draft model. "
             "Off by default.",
             lambda c: c.latency.enabled, lat_on, lat_off),
        _Def("diarize", "Diarized Conversation Capture", "[diarize] — attributed multi-speaker", OPTIONAL,
             "Capture a live conversation as attributed Markdown (**Alice:** …) and rename "
             "speakers by voice ('call speaker two Alice'). Needs the diarize extra. Off by default.",
             lambda c: c.diarize.enabled, diz_on, diz_off),
        _Def("cite", "Citation-by-Voice", "[cite] — cite from your local .bib", OPTIONAL,
             "Say 'cite Vaswani 2017' and it inserts a formatted citation from your local BibTeX "
             "library, fully offline. Off by default.",
             lambda c: c.cite.enabled, ci_on, ci_off),
        _Def("langroute", "Per-Language Auto Switching", "[langroute] — detect & swap model", OPTIONAL,
             "Detects the language you speak and hot-swaps to its specialized model + punctuation, "
             "no manual toggle. Needs the per-language model files. Off by default.",
             lambda c: c.langroute.enabled, lrt_on, lrt_off),
        _Def("hotwords", "Hard Contextual Biasing", "[hotwords] — names/jargon actually win", RECOMMENDED,
             "Biases recognition toward your vocabulary with a hotword trie (not just a soft "
             "prompt), so rare names and jargon are transcribed right. Off by default.",
             lambda c: c.hotwords.enabled, hw_on, hw_off),
        _Def("windowctl", "Voice Window Management", "[windowctl] — layout by voice", OPTIONAL,
             "Hands-free desktop layout: 'move window left half', 'maximize', 'workspace 3'. "
             "Needs the windowctl extra for your compositor. Off by default.",
             lambda c: c.windowctl.enabled, wc_on, wc_off),
        _Def("markup", "Structured-Markup Dictation", "[markup] — speak lists & tables", OPTIONAL,
             "Speak structure and get Markdown/org: 'bullet list: apples; oranges' → a list; "
             "'table columns Name, Age; row Alice, 30' → a table. Off by default.",
             lambda c: c.markup.enabled, mk_on, mk_off),
        _Def("findreplace", "Document Find-and-Replace", "[findreplace] — edit the whole document", OPTIONAL,
             "Edit the whole document by voice: 'replace every utilise with use'. Not just the "
             "last utterance. Off by default.",
             lambda c: c.findreplace.enabled, fr_on, fr_off),
        _Def("cmdsafety", "Terminal Command Safety Gate", "[cmdsafety] — confirm dangerous commands", RECOMMENDED,
             "In a terminal, holds a destructive command (rm -rf, curl|sh, force-push) until you "
             "say 'confirm', so a misrecognition can't fire it. Off by default.",
             lambda c: c.cmdsafety.enabled, csf_on, csf_off),
        _Def("spokenregex", "Spoken Regex Builder", "[spokenregex] — dictate search patterns", OPTIONAL,
             "Build regexes by voice: 'four digits dash two digits' → \\d{4}-\\d{2}. Feeds find "
             "dialogs and grep. Off by default.",
             lambda c: c.spokenregex.enabled, srx_on, srx_off),
        _Def("slotfill", "Slot-Filling Dictation", "[slotfill] — one utterance → a form", OPTIONAL,
             "Speak once and fill a named-field template: 'bug in login, high priority, affects "
             "Firefox' routes each value to its field. Off by default.",
             lambda c: c.slotfill.enabled, slf_on, slf_off),
        _Def("cmdspotter", "Few-Shot Command Spotter", "[cmdspotter] — enrolled micro-commands", OPTIONAL,
             "Enroll a few examples of short commands ('send', 'stop') that fire instantly "
             "without a full decode. Needs the kws extra. Off by default.",
             lambda c: c.cmdspotter.enabled, cs2_on, cs2_off),
        _Def("audioguard", "Ambient Audio-Event Guard", "[audioguard] — pause on interruptions", OPTIONAL,
             "Auto-pauses dictation (or alerts) when it hears a doorbell, phone, alarm or your "
             "name. Needs the soundawareness extra. Off by default.",
             lambda c: c.audioguard.enabled, ag2_on, ag2_off),
        _Def("condense", "On-Device Condense", "[condense] — summarise your ramble", OPTIONAL,
             "A condense variant inserts a tightened summary of your long dictation instead of "
             "the verbatim text. Local extractive summary. Off by default.",
             lambda c: c.condense.enabled, cnd_on, cnd_off),
        _Def("spreadsheet", "Spoken Spreadsheet", "[spreadsheet] — grid nav + cells", OPTIONAL,
             "Cell-addressed dictation + grid navigation for spreadsheets: 'next row', 'cell "
             "down', 'go to B7'. Hands-free 2D entry. Off by default.",
             lambda c: c.spreadsheet.enabled, ss_on, ss_off),
        _Def("cliphistory", "Clipboard-History by Voice", "[cliphistory] — recall copies", OPTIONAL,
             "Recall recent copies by voice: 'paste the second thing I copied', 'the URL I "
             "copied'. Local in-memory buffer. Off by default.",
             lambda c: c.cliphistory.enabled, clh_on, clh_off),
        _Def("temporal", "Spoken Temporal Normalizer", "[temporal] — dates from speech", OPTIONAL,
             "Resolves spoken dates against the clock: 'next Friday' → a concrete date, "
             "'tomorrow', 'in two weeks'. Uses only the local clock. Off by default.",
             lambda c: c.temporal.enabled, tmp_on, tmp_off),
        _Def("self_repair", "Mid-Utterance Self-Repair", "[commands] self_repair", OPTIONAL,
             "Applies in-burst corrections before typing: 'email Sarah no I mean Sara' → "
             "'email Sara'. Off by default — editing phrases occur in ordinary speech.",
             lambda c: c.commands.self_repair, sr_on, sr_off),
        _Def("symbols", "Emoji & Symbol by Voice", "[commands] symbols", OPTIONAL,
             "Speak emoji, symbols and arrows: 'shrug emoji' → 🤷, 'right arrow' → →, "
             "'degree sign' → °. Off by default — the names occur in ordinary speech.",
             lambda c: c.commands.symbols, sym_on, sym_off),
        _Def("convert", "Voice Unit Conversion", "[convert] — inline conversions", OPTIONAL,
             "Evaluate spoken conversions inline: 'twenty miles in kilometers' → '32.19 "
             "kilometers'. Offline, no cloud. Off by default.",
             lambda c: c.convert.enabled, cv_on, cv_off),
        _Def("lipread", "Silent Lip-Reading", "[lipread] — dictate with no voice", OPTIONAL,
             "Dictate silently — a webcam reads your lips when you can't or shouldn't speak. "
             "Needs a webcam (vsr extra). Off by default.",
             lambda c: c.lipread.enabled, lr_on, lr_off),
        _Def("sign", "Sign-Language Input", "[sign] — sign to the webcam", OPTIONAL,
             "Deaf/HoH signers dictate by signing to the webcam; ASL is recognized on-device "
             "and typed. Needs a webcam (sign extra). Off by default.",
             lambda c: c.sign.enabled, sn2_on, sn2_off),
        _Def("screengrounded", "Screen-Grounded Dictation", "[screengrounded] — bias from screen", OPTIONAL,
             "Primes Whisper with names visible on screen so they transcribe right the first "
             "time — works in any app. Accessibility/clipboard now; OCR via extra. Off by default.",
             lambda c: c.screengrounded.enabled, sg_on, sg_off),
        _Def("headpointer", "Head-Pointer", "[headpointer] — cursor by head pose", OPTIONAL,
             "Move and click the mouse by tilting your head; pair with voice for a fully "
             "hands-free desktop. Needs a webcam (headpointer extra). Off by default.",
             lambda c: c.headpointer.enabled, hp_on, hp_off),
        _Def("compose", "Compose-in-Target-Language", "[compose] — speak L1, type L2", OPTIONAL,
             "Speak your strongest language and inject the text in a target language you write "
             "less fluently. Offline MT (translate extra). Off by default.",
             lambda c: c.compose.enabled, cp_on, cp_off),
        _Def("gec", "Grammar Repair", "[gec] — minimal-edit correction", OPTIONAL,
             "Fixes article/agreement errors in dictated text with minimal edits, tuned for "
             "non-native speakers. Register-preserving; local-only. Off by default.",
             lambda c: c.gec.enabled, gec_on, gec_off),
        _Def("corpus_scrub", "Corpus Voiceprint Scrub", "[learning] anonymize_audio", OPTIONAL,
             "Speaker-anonymizes learning-corpus audio before storage so retained clips keep "
             "what was said but not an identifiable voice. Needs learning on. Off by default.",
             lambda c: c.learning.anonymize_audio, cvs_on, cvs_off),
        _Def("redaction", "Redaction Ink", "[redaction] — mask secrets before typing", OPTIONAL,
             "Detects spoken secrets (card numbers, SSNs, keys, emails) and masks them before "
             "they're typed into another window. Regex + Luhn, local-only. Off by default.",
             lambda c: c.redaction.enabled, rd_on, rd_off),
        _Def("fieldaware", "Field-Aware Dictation", "[fieldaware] — shape output by field", OPTIONAL,
             "Reshapes output to the focused control: number field → digits, search box → no "
             "trailing period, password field → refuses to type. Off by default.",
             lambda c: c.fieldaware.enabled, fa_on, fa_off),
        _Def("itn", "Entity ITN", "[itn] — spoken emails/versions → written", OPTIONAL,
             "Turns spoken structured entities into written form with no command words: "
             "'john dot doe at gmail dot com' → the email, 'version two point one' → v2.1. "
             "Off by default.",
             lambda c: c.itn.enabled, itn_on, itn_off),
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
    "itn": "Say 'john dot doe at gmail dot com' → john.doe@gmail.com.",
    "hatselect": "Say 'delete bravo' and the token labeled bravo is gone — no cursor.",
    "translit": "Dictate 'salam' and it types سلام in Persian script.",
    "brailleout": "Dictate 'hello' and your Braille display gets ⠓⠑⠇⠇⠕ directly.",
    "outline": "Say 'new item groceries, indent, new item milk' → a nested outline.",
    "diagramvox": "Say 'A goes to B; B goes to C' and get a Mermaid flowchart.",
    "proofback": "Interrupt the read-back and the cursor lands on the word being read.",
    "screenplay": "Dictate a scene and it lands as proper INT./EXT. Fountain markup.",
    "srscap": "Say 'remember that the capital of France is Paris' → a flashcard.",
    "styleguard": "Say 'email' and your style sheet rewrites it to 'e-mail' automatically.",
    "suggestmode": "Your edit lands as {~~old~>new~~} for the author to accept later.",
    "sembr": "Dictate a paragraph and each clause lands on its own source line.",
    "acronyms": "Say 'WHO' the first time and it writes out the full name for you.",
    "morsevox": "One short hum, one long — spell a whole word by voice-Morse.",
    "checkdigit": "Dictate a card number and a mis-heard digit is caught instantly.",
    "mouthswitch": "Pop your lips to move the highlight, cluck to select — no words.",
    "involuntary": "Cough mid-sentence and it's dropped before it reaches the text.",
    "breath": "Take a breath and YazSes commits that phrase and starts a new one.",
    "whispermode": "Drop to a whisper and it turns up the gain so it still hears you.",
    "hesitation": "Trail off with 'annnd… uhh…' and it waits instead of cutting you off.",
    "contour": "Hum a rising note to confirm, a falling one to cancel — no words.",
    "spatialvad": "A colleague talks beside you and it's gated out by direction.",
    "prosodypunct": "Speak naturally and the periods and commas appear on their own.",
    "vocaljoystick": "Hum 'eee' and the cursor glides up — louder moves it faster.",
    "earcon": "A rising two-note beep tells you recording started, no glance needed.",
    "voicetimer": "Say 'set a timer for 25 minutes' — it reminds you, fully offline.",
    "focusprofile": "Move from your editor to a terminal and the grammar follows.",
    "tablecsv": "Say 'row: Ada, 1815, London' to fill a spreadsheet row.",
    "wordgoal": "Say 'how many words so far?' and it tells you your progress.",
    "timeline": "Say 'undo the last sentence' to take back what YazSes just typed.",
    "bookmarks": "Say 'bookmark here', then 'jump to my last bookmark' after a break.",
    "casetransform": "Select a name, say 'make this snake_case', and it rewrites.",
    "autopair": "Dictate '(a plus b' and it closes to '(a plus b)'.",
    "chords": "Say 'press control shift P' and the command palette opens.",
    "compute": "Say \"what's 15% of 240\" and it types 36.",
    "recimport": "Drop in a lecture recording and get a searchable .srt transcript.",
    "crowdproof": "Dictate in a noisy café and the interfering voices are stripped out.",
    "jump": "Say 'go to line 240' or 'jump to function tokenize' to navigate.",
    "shellpipe": "Speak 'list files pipe to grep error' to build a previewed pipeline.",
    "corrdict": "You keep fixing 'yaz says'→'YazSes'; soon it's fixed automatically.",
    "fileopen": "Say 'open the mortgage notes' to launch the right file.",
    "reask": "An unsure 'their/there' pops a quick pick instead of guessing wrong.",
    "verbatim": "Say 'dictate verbatim' and 'one hundred dollars' types literally.",
    "spelling": "Say 'capital alpha bravo double lima' to type 'Abll' exactly.",
    "gitvoice": "Say 'force push' and it waits for confirm, and tells you the undo.",
    "latency": "Dictation stays snappy when your CPU is busy, faster when it's idle.",
    "diarize": "A two-person chat is typed as **Alice:** … **Bob:** … you can rename by voice.",
    "cite": "Say 'cite Vaswani 2017' to insert a citation from your .bib.",
    "langroute": "Switch languages mid-session and the right model loads automatically.",
    "hotwords": "Add 'Kubernetes' to vocab and it stops being mis-heard.",
    "windowctl": "Say 'move window left half' or 'workspace 3' to arrange your desktop.",
    "markup": "Say 'bullet list: apples; oranges; pears' to type a Markdown list.",
    "findreplace": "Say 'replace every utilise with use' to edit the whole document.",
    "cmdsafety": "Dictate 'rm -rf' in a terminal and it waits for you to say 'confirm'.",
    "spokenregex": "Say 'four digits dash two digits' to build \\d{4}-\\d{2}.",
    "slotfill": "Say 'high priority, affects Firefox' to fill a bug-report form.",
    "cmdspotter": "Enroll 'send' once, then say it to fire the action instantly.",
    "audioguard": "The doorbell rings mid-dictation and recording auto-pauses.",
    "condense": "Ramble for a paragraph and a tightened 2-sentence summary is typed.",
    "spreadsheet": "Say 'next row' or 'go to B7' to drive a spreadsheet.",
    "cliphistory": "Say 'paste the second thing I copied' to recall a copy.",
    "temporal": "Say 'next Friday' and it types the concrete date.",
    "self_repair": "Say 'email Sarah no I mean Sara' → 'email Sara'.",
    "symbols": "Say 'right arrow' → → or 'shrug emoji' → 🤷.",
    "convert": "Say 'twenty miles in kilometers' → '32.19 kilometers'.",
    "lipread": "Mouth the words silently and a webcam reads your lips into text.",
    "sign": "Sign to the webcam and your ASL is recognized and typed.",
    "screengrounded": "A name shown on screen transcribes right the first time.",
    "headpointer": "Tilt your head to move the cursor; dwell to click.",
    "compose": "Speak Farsi with [compose] target='en' and type English.",
    "gec": "Dictate 'a apple' and it's corrected to 'an apple'.",
    "corpus_scrub": "Stored learning clips are pitch-shifted to hide your voice identity.",
    "redaction": "Speak a card number and it's typed as [CARD], not the digits.",
    "fieldaware": "Focus a number field and 'forty two' is typed as 42.",
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
