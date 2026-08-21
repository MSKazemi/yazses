"""Config keys the loader accepts, validates, documents — and no code ever reads.

`[injection] fallback_to_clipboard` was one of these until v2.24.0: it appeared in
seventeen places across the docs and the example configs people copy, defaulted to
`true`, and nothing read it — so anyone who turned it off was silently overruled.
It was found by hand. This is the mechanical version of that search.

Two confirmed by reading the code that should have used them:

* `[audio] channels` — documented with default `1`; `audio/recorder.py` passes a
  literal `channels=1` to sounddevice. Setting `2` gets you mono.
* `[tray] poll_interval_s` — documented with default `1.0`; `tray/app.py` polls on
  a module-level `_FAST_POLL_INTERVAL_S = 0.15`.

Every one of the 63 below appears in `docs/configuration.md`, in the same
`Key | Type | Default` tables as the keys that work, with nothing to tell them
apart. `sample_rate` is read and `channels` is the row beneath it.

**A ledger, not a gate**, following `test_orphan_modules.py` and for the same
reason it gives: listing the known set means the suite passes today and fails the
moment a 64th appears, or when one is finally wired and its entry goes stale.
Demanding 63 fixes in one commit would just get the test deleted. Many of these
belong to features honestly registered as not-yet-wired, where an unread key is
the expected state rather than a defect; the point is that the pile stops growing
silently.

Whether the documentation should mark them is a separate question, and a real one:
today a reader cannot tell which knobs do anything.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Keys accepted and validated by the loader that no code outside the config
#: plumbing reads. Sorted; regenerate by running this module's `_unread()`.
KNOWN_UNREAD = {
    "AccessibilityConfig.confirm_timeout_s",
    "AccessibilityConfig.vad_source",
    "AcousticProfilesConfig.min_stable",
    "ActivationConfig.confirm_threshold",
    "ActivationConfig.reject_floor",
    "AgentConfig.allowlist",
    "AudioConfig.channels",
    "AudioguardConfig.cooldown_frames",
    "BrailleoutConfig.grade",
    "BreathConfig.min_gap_s",
    "BreathConfig.onset_threshold",
    "BridgeConfig.pair_token",
    "CiteConfig.bib_path",
    "CliphistoryConfig.capacity",
    "CodecConfig.max_delay_ms",
    "CommandsConfig.lsp_editor",
    "CommandsConfig.lsp_enabled",
    "CommandsConfig.rewrite_timeout_s",
    "CommandsConfig.slm_confidence_threshold",
    "CondenseConfig.max_sentences",
    "ConfidenceConfig.mark_in_overlay",
    "ContextConfig.use_lsp",
    "ContinuumConfig.semantic_capture",
    "CorrdictConfig.min_support",
    "EmgConfig.command_map",
    "EndpointConfig.falling_window_ms",
    "EndpointConfig.prefix_stable_ms",
    "EndpointConfig.speculative_finalize",
    "HesitationConfig.commit_ms",
    "HesitationConfig.hold_extra_ms",
    "HotkeyConfig.evdev_device",
    "HotwordsConfig.boost",
    "LipreadConfig.mouth_threshold",
    "MouthswitchConfig.dwell_s",
    "PersonalizeConfig.lora",
    "PersonalizeConfig.lora_base_model",
    "PersonalizeConfig.lora_min_events",
    "PersonalizeConfig.lora_min_improvement",
    "PhoneticConfig.max_distance",
    "PilotConfig.confirm_ambiguous",
    "PronunciationConfig.good_threshold",
    "ProsodyConfig.experimental_pitch_question",
    "ProsodypunctConfig.comma_pause_ms",
    "ProsodypunctConfig.sentence_pause_ms",
    "RagConfig.embed_model",
    "RagConfig.store_path",
    "RagConfig.top_k",
    "RecimportConfig.batched",
    "RemoteConfig.default_host",
    "SembrConfig.max_len",
    "SignConfig.pause_frames",
    "SnippetsConfig.entries",
    "SpatialvadConfig.mic_distance_m",
    "SpatialvadConfig.target_angle",
    "SpatialvadConfig.tolerance_deg",
    "StagedConfig.show_in_overlay",
    "StreamingConfig.partial_marker",
    "TablecsvConfig.delimiter",
    "TrayConfig.poll_interval_s",
    "VocaljoystickConfig.click_pitch",
    "VocaljoystickConfig.max_speed",
    "VoiceprintConfig.profile_min_similarity",
    "WakewordConfig.keyword",
}


def _config_fields() -> list[tuple[str, str]]:
    tree = ast.parse((ROOT / "src/yazses/config.py").read_text(encoding="utf-8"))
    return [
        (node.name, st.target.id)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for st in node.body
        if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
    ]


def _without_comments(source: str) -> str:
    """*source* with ``#`` comments removed, everything else untouched.

    The match below is `[."']name` — an attribute access or a string key — which is
    a good proxy for "this key is read". Its one flaw was that it ran over the raw
    file, so **a comment mentioning a key made that key count as read**, which is
    exactly the reachability this guard exists to detect.

    Hit for real: a comment in `system/report.py` noting that the snippets table is
    unwired was itself enough to register that field as wired. A comment cannot read
    a config key.

    Stripping only comments, rather than switching to an AST walk over attributes and
    keywords. That was tried and is worse in both directions: `channels=1` passed to
    `sd.InputStream` is an `ast.keyword` named `channels`, which would mark
    `AudioConfig.channels` as read by an unrelated call — five fields flipped that way
    on the first run.
    """
    import io
    import tokenize

    lines = source.splitlines()
    try:
        comments = [
            tok.start for tok in tokenize.generate_tokens(io.StringIO(source).readline)
            if tok.type == tokenize.COMMENT
        ]
    except (tokenize.TokenError, IndentationError):  # pragma: no cover - defensive
        return source
    # Blanked **in place**, keeping every other character where it was. Rebuilding
    # from token strings instead (joined with newlines) tore `cfg.audio.device` into
    # three lines, so `.device` no longer matched and forty genuinely-read keys were
    # reported as unread. A comment always runs to end of line, so a slice is enough.
    for row, col in comments:
        if 1 <= row <= len(lines):
            lines[row - 1] = lines[row - 1][:col]
    return "\n".join(lines)


def _unread() -> set[str]:
    """Fields never referenced as an attribute or key outside the config plumbing.

    `config.py` and `configcheck.py` are excluded because both walk the dataclass
    annotations generically — every field is "used" there by construction, which
    is exactly the reachability that hides an unread key.
    """
    src = ROOT / "src/yazses"
    code = "\n".join(
        _without_comments(p.read_text(encoding="utf-8", errors="ignore"))
        for p in src.rglob("*.py")
        if p.name not in ("config.py", "configcheck.py")
    )
    return {
        f"{cls}.{name}"
        for cls, name in _config_fields()
        if not re.search(r"[.\"']" + re.escape(name) + r"\b", code)
    }


def test_no_new_config_key_joins_the_unread_pile():
    new = sorted(_unread() - KNOWN_UNREAD)
    assert not new, (
        "config keys the loader accepts and documents but nothing reads:\n  "
        + "\n  ".join(new)
        + "\n\nWire it, or add it to KNOWN_UNREAD with the reason."
    )


def test_the_ledger_has_no_stale_entries():
    """A key that has since been wired must leave, or the ledger stops meaning anything."""
    fixed = sorted(KNOWN_UNREAD - _unread())
    assert not fixed, (
        "these are now read by code and should be removed from KNOWN_UNREAD:\n  "
        + "\n  ".join(fixed)
    )


def test_the_detector_finds_a_key_that_is_genuinely_read():
    """Proves the sweep can return a negative, rather than flagging everything.

    `[accessibility] vad_threshold` is read on the dictation hot path, so it must
    never appear as unread. Without this the two tests above would still pass if
    the regex silently matched nothing.
    """
    unread = _unread()
    for live in ("AccessibilityConfig.vad_threshold", "SttConfig.model", "HotkeyConfig.key"):
        assert live not in unread, f"{live} is read by real code but was called unread"


def test_a_comment_cannot_make_an_unread_key_look_wired():
    """The flaw this guard had, and the reason it was worth fixing here.

    The match ran over raw file text, so a comment naming a key registered it as
    read — in a guard whose entire job is to notice keys nothing reads. Hit for
    real: a comment in `system/report.py` saying the snippets table is *unwired*
    was itself enough to mark that field as wired.
    """
    stripped = _without_comments(
        "x = cfg.audio.device  # also mentions .max_record_seconds\n"
    )
    assert ".max_record_seconds" not in stripped
    assert "cfg.audio.device" in stripped, "the attribute access must survive intact"


def test_stripping_comments_does_not_damage_code_or_strings():
    """Rebuilding from token strings tore `cfg.audio.device` into three lines, so
    `.device` stopped matching and forty genuinely-read keys were reported unread.

    A `#` inside a string literal is not a comment, and cutting there would remove
    real references.
    """
    stripped = _without_comments('y = "a # not a comment"\nz = obj.real_attr\n')
    assert 'a # not a comment' in stripped
    assert "obj.real_attr" in stripped
