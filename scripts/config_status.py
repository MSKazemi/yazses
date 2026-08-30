#!/usr/bin/env python3
"""Which config keys the code actually reads — the one place that decides.

`[injection] fallback_to_clipboard` appeared in seventeen places across the docs and
the example configs people copy, defaulted to `true`, and nothing read it, so anyone
who turned it off was silently overruled. It was found by hand, and it is the reason
this module exists.

Two readers share it and they must never disagree:

* `tests/test_config_keys_are_read.py` — the ledger gate: no key joins the pile
  silently, and no entry stays once the key is finally wired.
* `scripts/gen-docs.py` — the **Configuration Reference** the user edits by hand.

Splitting them was the point. The detector and the ledger lived only in the test, so
`docs/configuration.md` listed all 447 keys in one undifferentiated `Key | Type |
Default` table: `sample_rate` is read, `channels` is the row directly beneath it and
is not, and nothing on the page told them apart. The test's own docstring left that
open — *"today a reader cannot tell which knobs do anything"* — and a second
hand-written list of inert keys inside the generator would have gone stale the first
time one was wired.
"""

from __future__ import annotations

import ast
import dataclasses
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Keys accepted and validated by the loader that no code outside the config
#: plumbing reads. Sorted; regenerate with ``python3 scripts/config_status.py``.
#:
#: Many belong to capabilities honestly registered as not-yet-wired, where an unread
#: key is the expected state rather than a defect. The pile is allowed to exist; it is
#: not allowed to grow, or to shrink without the ledger noticing.
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
    "ConfidenceConfig.mark_in_overlay",
    "ContextConfig.use_lsp",
    "ContinuumConfig.semantic_capture",
    "EmgConfig.command_map",
    "EndpointConfig.falling_window_ms",
    "EndpointConfig.prefix_stable_ms",
    "EndpointConfig.speculative_finalize",
    # Both were hidden from this detector for as long as it existed, by an import path
    # that spells the field name (`from yazses.gaze.zones import ...`,
    # `from yazses.polyglot.lid import ...`); see `_IMPORT`. They are listed rather
    # than wired because each is a real piece of work, not an oversight:
    # `[gaze] zones` names a zone scheme (`grid3x3 | grid2x2 | windows`) and the only
    # caller, `targeter.resolve_window`, resolves the looked-at *window* and never
    # consults a grid at all -- `zones.grid_zone` exists, is tested, and has no caller.
    # `[polyglot] lid` names a language-ID granularity for a router that stays dormant
    # until `[polyglot] adapter_path` points at a trained adapter that is not shipped.
    "GazeConfig.zones",
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
    "PolyglotConfig.lid",  # see the note beside GazeConfig.zones
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


#: Keys `unread_fields` cannot see, because the match is by **name alone** and the
#: name is shared with a field in another section. One section reading it makes it
#: look read in every section that spells it the same way, so the detector reports a
#: live setting and `docs/configuration.md` tells the user it works.
#:
#: This is the third instance of one collision. A comment naming a key made it look
#: read; `without_comments` fixed that. A dotted module path spelled like an attribute
#: made it look read; `_IMPORT` fixed that. Both were fixable because the noise was
#: *structural* — a comment and an import are recognisable without knowing types. A
#: sibling section's read is not: `config.format` in `postprocess/prosody.py` is a
#: genuine read of `[prosody] format`, and it is character-identical to what a read of
#: `[outline] format` would look like. Telling them apart needs the type of `config`,
#: and the alternative that does not — demanding a section-qualified `cfg.<section>.<key>`
#: — reports `[macros] path` and `[styleguard] path` as dead, because both are really
#: read through a short local (`mc.path`, `sg.path`). A false *inert* is the worse
#: error of the two: it tells someone a working knob does nothing.
#:
#: So the blind spot is enumerated instead of guessed at. Each entry below was read out
#: of every occurrence of its name in the tree, and `tests/test_shared_config_names.py`
#: re-checks that none of them has acquired an attributable read — the same discipline
#: as `KNOWN_UNREAD`, applied to the keys that ledger structurally cannot hold.
#:
#: 32 field names are shared across sections and 216 (class, field) pairs rest on that
#: match, so this set is a floor, not a census.
AMBIGUOUS_UNREAD = {
    # `.mode` is read for `[emg]`, `[redaction]` and `[cocktail]` only.
    "AffectConfig.mode",
    "AutoStopConfig.mode",
    # `.min_confidence` belongs to two unrelated dataclasses -- `gaze.implicit`'s own
    # field and `langroute.route.LangRegistry`, which nothing in `src/` constructs.
    "AffectConfig.min_confidence",
    "LangrouteConfig.min_confidence",
    # `.style` is read once, for `[overlay]`, in `overlay/app.py`.
    "CiteConfig.style",
    # `.max_terms` occurs only as a local parameter of `personalize.prompt_builder`.
    "ContextConfig.max_terms",
    "ScreengroundedConfig.max_terms",
    # `.format` is read once, for `[prosody]`; every other hit is `str.format`.
    "OutlineConfig.format",
    # `.source` is never read from any config: the hits are a RAG chunk's attribute,
    # an AT-SPI event's, and one message string.
    "ComposeConfig.source",
    "HotkeyConfig.source",
    # `.min_score` / `.max_candidates` are read for `[punch_in]`, and are default
    # parameters of `rag.retrieve` / `postprocess.punch_in` otherwise.
    "RagConfig.min_score",
    "WordfindConfig.max_candidates",
    # Read and discarded, which the detector cannot distinguish from used:
    # `tts/kokoro.py` assigns `self._sample_rate = config.sample_rate` and nothing
    # ever reads that attribute. Kokoro emits at its own rate and `speak` uses the
    # rate the model returns, so setting this key changes nothing.
    "TtsConfig.sample_rate",
}


def config_fields() -> list[tuple[str, str]]:
    """``(ClassName, field)`` for every annotated field in `config.py`."""
    tree = ast.parse((ROOT / "src/yazses/config.py").read_text(encoding="utf-8"))
    return [
        (node.name, st.target.id)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for st in node.body
        if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
    ]


#: An `import`/`from ... import ...` line. Blanked for the same reason comments are:
#: it cannot read a config key, and its dotted module path looks exactly like one.
#: `from yazses.gaze.zones import resolve_window` contains `.zones`, which marked
#: `GazeConfig.zones` as read — and nothing in the tree reads it. Same for
#: `from yazses.polyglot.lid import ...` and `PolyglotConfig.lid`. Both were reported
#: as live settings in `docs/configuration.md` while being inert, which is precisely
#: the state this detector exists to expose. The collision is structural rather than
#: unlucky: config sections are named after the subsystems they configure, so a field
#: sharing a name with a module in that subsystem is the *likely* case, not the freak
#: one.
_IMPORT = re.compile(r"\s*(?:from|import)\s")


def without_comments(source: str) -> str:
    """*source* with ``#`` comments and ``import`` lines removed, else untouched.

    The match below is `[."']name` — an attribute access or a string key — which is
    a good proxy for "this key is read". Its one flaw was that it ran over the raw
    file, so **a comment mentioning a key made that key count as read**, which is
    exactly the reachability this detector exists to find. Hit for real: a comment in
    `system/report.py` noting that the snippets table is unwired was itself enough to
    register that field as wired. A comment cannot read a config key. Neither can an
    import; see `_IMPORT`.

    Stripping only comments, rather than switching to an AST walk over attributes and
    keywords. That was tried and is worse in both directions: `channels=1` passed to
    `sd.InputStream` is an `ast.keyword` named `channels`, which would mark
    `AudioConfig.channels` as read by an unrelated call — five fields flipped that way
    on the first run.
    """
    lines = source.splitlines()
    try:
        comments = [
            tok.start
            for tok in tokenize.generate_tokens(io.StringIO(source).readline)
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
    # Blanked, not dropped, for the same reason: line positions stay put, and a
    # multi-line parenthesised import keeps its continuation lines intact -- those
    # carry only imported names, never a dotted path, so they cannot collide.
    return "\n".join("" if _IMPORT.match(ln) else ln for ln in lines)


def unread_fields() -> set[str]:
    """``ClassName.field`` never referenced as an attribute or key outside the plumbing.

    `config.py` and `configcheck.py` are excluded because both walk the dataclass
    annotations generically — every field is "used" there by construction, which is
    exactly the reachability that hides an unread key.
    """
    src = ROOT / "src/yazses"
    code = "\n".join(
        without_comments(p.read_text(encoding="utf-8", errors="ignore"))
        for p in src.rglob("*.py")
        if p.name not in ("config.py", "configcheck.py")
    )
    return {
        f"{cls}.{name}"
        for cls, name in config_fields()
        if not re.search(r"[.\"']" + re.escape(name) + r"\b", code)
    }


def inert_dotted_keys(cfg: object) -> set[str]:
    """``section.key`` (TOML spelling) for every ledger entry, resolved on a live `Config`.

    Both ledgers: `KNOWN_UNREAD`, which the detector finds, and `AMBIGUOUS_UNREAD`,
    which it structurally cannot. The page makes no distinction because the user
    cannot act on one -- either way the key does nothing.

    The ledger is keyed by **class** name and the reference is written in **section**
    names, so one of the two has to translate. It is done here, against a real object,
    for the reason `test_docs_config_keys_exist.py` gives for doing the same: a guessed
    section↔class mapping resolves nothing and silently marks nothing.
    """
    ledger = KNOWN_UNREAD | AMBIGUOUS_UNREAD
    out: set[str] = set()
    for fld in dataclasses.fields(cfg):  # type: ignore[arg-type]
        inst = getattr(cfg, fld.name)
        if not dataclasses.is_dataclass(inst):
            continue
        for sub in dataclasses.fields(inst):
            val = getattr(inst, sub.name)
            if dataclasses.is_dataclass(val):
                for leaf in dataclasses.fields(val):
                    if f"{type(val).__name__}.{leaf.name}" in ledger:
                        out.add(f"{fld.name}.{sub.name}.{leaf.name}")
            elif f"{type(inst).__name__}.{sub.name}" in ledger:
                out.add(f"{fld.name}.{sub.name}")
    return out


if __name__ == "__main__":  # pragma: no cover - maintainer helper
    for entry in sorted(unread_fields()):
        print(f'    "{entry}",')
