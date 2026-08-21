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
    "CommandsConfig.slm_confidence_threshold",
    "CondenseConfig.max_sentences",
    "ConfidenceConfig.mark_in_overlay",
    "ContextConfig.use_lsp",
    "ContinuumConfig.semantic_capture",
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


def without_comments(source: str) -> str:
    """*source* with ``#`` comments removed, everything else untouched.

    The match below is `[."']name` — an attribute access or a string key — which is
    a good proxy for "this key is read". Its one flaw was that it ran over the raw
    file, so **a comment mentioning a key made that key count as read**, which is
    exactly the reachability this detector exists to find. Hit for real: a comment in
    `system/report.py` noting that the snippets table is unwired was itself enough to
    register that field as wired. A comment cannot read a config key.

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
    return "\n".join(lines)


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

    The ledger is keyed by **class** name and the reference is written in **section**
    names, so one of the two has to translate. It is done here, against a real object,
    for the reason `test_docs_config_keys_exist.py` gives for doing the same: a guessed
    section↔class mapping resolves nothing and silently marks nothing.
    """
    out: set[str] = set()
    for fld in dataclasses.fields(cfg):  # type: ignore[arg-type]
        inst = getattr(cfg, fld.name)
        if not dataclasses.is_dataclass(inst):
            continue
        for sub in dataclasses.fields(inst):
            val = getattr(inst, sub.name)
            if dataclasses.is_dataclass(val):
                for leaf in dataclasses.fields(val):
                    if f"{type(val).__name__}.{leaf.name}" in KNOWN_UNREAD:
                        out.add(f"{fld.name}.{sub.name}.{leaf.name}")
            elif f"{type(inst).__name__}.{sub.name}" in KNOWN_UNREAD:
                out.add(f"{fld.name}.{sub.name}")
    return out


if __name__ == "__main__":  # pragma: no cover - maintainer helper
    for entry in sorted(unread_fields()):
        print(f'    "{entry}",')
