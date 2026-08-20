"""`config.py` documents closed sets that `configcheck` does not check.

`yazses doctor` reports `configcheck`'s verdict as **"Config validity: every setting is a
usable value"**. That table held two entries while `config.py` declared twenty-three more
closed sets in trailing `# a | b | c` comments, none of them checked -- so a typo was
accepted in silence and its consequence was decided by whichever consumer eventually read
the value. Measured on 2026-08-20, four plausible typos through the real loader:

    [gaze] backend       = "mediapip"    -> accepted, gaze silently never runs
    [stt] engine         = "whisper"     -> accepted, warned at build time
    [voiceprint] backend = "ecapa-tdnn"  -> accepted, voiceprint silently disabled
    [meeting] output_format = "markdown" -> accepted, the post-pass later RAISES
    [injection] backend  = "xdotol"      -> caught (the one entry that existed)

The silent-disable cases are the worst of the three: the log line goes to a daemon log
nobody reads, `yazses features` still shows the capability as ON, and it simply never runs.

This file exists so the table cannot fall behind `config.py` again. It does **not** demand
that every documented set be enforced -- validating against a *wrong* list rejects a
working config, which is worse than the silence. It demands that each one be either
enforced or recorded as unenforceable with a reason, so the choice is deliberate and a new
enum field cannot be added without meeting one of the two.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
import re

import pytest

from yazses import config as C
from yazses.configcheck import _ENUMS, enum_values

REPO = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PY = REPO / "src" / "yazses" / "config.py"

#: Documented closed sets that are deliberately **not** enforced, and why. Every entry is
#: a claim that there is no set to enforce -- not a backlog of unfinished work.
_UNENFORCEABLE: dict[str, str] = {
    "commands.lsp_editor": (
        "inert: nothing in src/ consumes it, and its comment (auto|neovim|vscode) and "
        "the architecture reference (neovim|none) disagree, so there is no set to hold"
    ),
}

#: Documented closed sets not yet enforced because the consumer has not been read.
#:
#: This is a **backlog**, and it is written down rather than fixed in one sweep on
#: purpose: enforcing a set that turns out to be wrong rejects a working config, which is
#: worse than the silence it replaces. `commands.lsp_editor` is why the caution is not
#: theoretical -- its comment and the architecture reference disagree about what its
#: values even are.
#:
#: An attempt to enforce these in bulk was abandoned in the same pass that found them:
#: the shortcut used to decide "does this field have a consumer?" grepped for `\.<field>`,
#: which matches any attribute of that name anywhere, so four unrelated `.mode` settings
#: reported the identical reader list. Each of these needs its own consumer read.
#:
#: `_MAX_UNVERIFIED` ratchets: the list may shrink, never grow. A *new* enum field must be
#: enforced, or explicitly justified in `_UNENFORCEABLE`.
_UNVERIFIED: frozenset[str] = frozenset({
    "affect.mode",
    "agent.confirm",
    "autostop.mode",
    "cocktail.mode",
    "codec.backend",
    "denoise.backend",
    "emg.mode",
    "gaze.zones",
    "meeting.vad_backend",
    "modality.preset",
    "overlay.position",
    "pilot.backend",
    "prosody.format",
    "redaction.mode",
    "scribe.backend",
    "translate.backend",
    "tts.clone_backend",
    "tts.engine",
})
_MAX_UNVERIFIED = 18

_FIELD = re.compile(r'^\s+(\w+):\s*str\s*=\s*"([^"]*)"\s*#\s*(.+?)\s*$')


def _sections() -> dict[str, str]:
    """Dataclass name -> the `[section]` name it is loaded from."""
    base = C.Config()
    out = {}
    for f in dataclasses.fields(base):
        sub = getattr(base, f.name)
        if dataclasses.is_dataclass(sub):
            out[type(sub).__name__] = f.name
    return out


def documented_sets() -> dict[str, tuple[str, ...]]:
    """Every `section.key` whose trailing comment declares a closed set.

    Derived from the file rather than listed, so a new field is covered the day it is
    written. The field's own default must appear among the alternatives -- that is what
    separates a choice list from prose that happens to contain a pipe (`curl | sh`).
    """
    source = CONFIG_PY.read_text(encoding="utf-8")
    lines = source.splitlines()
    by_class = _sections()
    found: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef) or node.name not in by_class:
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign):
                continue
            match = _FIELD.match(lines[stmt.lineno - 1])
            if not match:
                continue
            key, default, comment = match.groups()
            if "|" not in comment:
                continue
            values = []
            for part in comment.split("|"):
                word = re.match(r"\s*`?([a-z][a-z0-9_.-]*)`?", part)
                if word:
                    values.append(word.group(1))
            if default not in values:
                continue
            found[f"{by_class[node.name]}.{key}"] = tuple(values)
    return found


DOCUMENTED = documented_sets()


def test_the_derivation_finds_the_sets_it_is_meant_to():
    """A guard that iterates is green on an empty collection."""
    assert len(DOCUMENTED) >= 20, sorted(DOCUMENTED)
    assert DOCUMENTED.get("gaze.zones") == ("grid3x3", "grid2x2", "windows")
    assert "commands.lsp_editor" in DOCUMENTED


def test_prose_containing_a_pipe_is_not_mistaken_for_a_choice_list():
    """`cmdsafety`'s docstring names `curl | sh` as a dangerous command."""
    assert "cmdsafety.confirm_word" not in DOCUMENTED
    for key, values in DOCUMENTED.items():
        assert all(v.strip() for v in values), (key, values)


def test_the_backlog_only_shrinks():
    """A ratchet, so the unenforced list cannot quietly absorb new settings.

    Without it `_UNVERIFIED` is just a permission slip: every new enum field would be
    added to it and the gate would stay green forever.
    """
    # Two assertions, because one is not enough. `_MAX_UNVERIFIED` *is* the claim, so
    # `len(...) <= _MAX_UNVERIFIED` alone is repaired by raising the number -- the same
    # circularity that made a floor constant unmutatable in the advised-commands guard.
    # Pinning the ceiling to the list's actual length means raising it without adding an
    # entry fails here, and the literal below is the historical high-water mark, so
    # adding an entry fails too. Both edits stay visible in a diff.
    assert _MAX_UNVERIFIED == len(_UNVERIFIED), (
        f"the ceiling ({_MAX_UNVERIFIED}) must equal the backlog ({len(_UNVERIFIED)}); "
        "lower it as entries are verified"
    )
    assert len(_UNVERIFIED) <= 18, (
        f"{len(_UNVERIFIED)} unverified sets, up from the 18 found on 2026-08-20. "
        "A new closed set must be enforced in configcheck._ENUMS, or justified in "
        "_UNENFORCEABLE -- not parked here."
    )
    assert not (_UNVERIFIED & set(_ENUMS)), (
        f"already enforced, so remove from the backlog and lower _MAX_UNVERIFIED: "
        f"{sorted(_UNVERIFIED & set(_ENUMS))}"
    )
    assert _UNVERIFIED <= set(DOCUMENTED), (
        f"backlog names settings config.py no longer documents: "
        f"{sorted(_UNVERIFIED - set(DOCUMENTED))}"
    )


@pytest.mark.parametrize("key", sorted(DOCUMENTED))
def test_every_documented_set_is_enforced_or_explained(key):
    if key in _UNENFORCEABLE:
        assert _UNENFORCEABLE[key].strip(), f"{key} needs a reason, not a blank"
        assert key not in _ENUMS, f"{key} is both enforced and listed as unenforceable"
        return
    if key in _UNVERIFIED:
        pytest.skip("consumer not yet read; tracked by test_the_backlog_only_shrinks")
    assert enum_values(*key.split(".", 1)) is not None, (
        f"[{key.split('.')[0]}] {key.split('.')[1]} documents a closed set that nothing "
        "checks, so a typo is accepted in silence. Read the consumer, confirm the set, "
        "and add it to configcheck._ENUMS -- or record why it cannot be enforced in "
        "_UNENFORCEABLE in this file."
    )


@pytest.mark.parametrize("key", sorted(k for k in _ENUMS if k in DOCUMENTED))
def test_an_enforced_set_matches_what_the_field_documents(key):
    """Two lists again. The comment is what a reader believes; the table is what runs."""
    documented = set(DOCUMENTED[key])
    enforced = {v for v in _ENUMS[key] if v}
    assert documented == enforced, (
        f"{key}: config.py documents {sorted(documented)} but configcheck enforces "
        f"{sorted(enforced)}"
    )


def test_the_output_formats_come_from_the_renderer():
    """`render_transcript` owns this set and raises on anything outside it."""
    from yazses.recimport.render import VALID_FORMATS

    for key in ("recimport.output_format", "meeting.output_format"):
        assert _ENUMS[key] == VALID_FORMATS, (
            f"{key} must equal render.VALID_FORMATS, the constant that decides whether "
            "the post-pass raises"
        )


def test_the_rejection_message_names_the_values_readably():
    """The message is the whole point -- it is what the user reads in `doctor`.

    `stt.engine` accepts `""` ("use the default"), and joining the raw tuple rendered it
    as a stray leading comma: *"is not one of , faster-whisper, parakeet, moonshine"*.
    """
    import dataclasses
    import tempfile

    d = pathlib.Path(tempfile.mkdtemp(prefix="yazses-enum-msg-"))
    path = d / "config.toml"
    path.write_text('[stt]\nengine = "whisper"\n', encoding="utf-8")
    problems = C.load_config_checked(path).problems
    assert len(problems) == 1, problems
    message = dataclasses.astuple(problems[0])[2]
    assert ", ," not in message and "one of ," not in message, message
    assert "faster-whisper, parakeet, moonshine" in message, message
    assert "empty" in message, f"the empty option vanished from the message: {message}"


@pytest.mark.parametrize("key", sorted(_ENUMS))
def test_every_enforced_default_is_itself_a_valid_value(key):
    """A typo in the table would reject the shipped default on every machine."""
    section, field = key.split(".", 1)
    default = getattr(getattr(C.Config(), section), field)
    assert default in _ENUMS[key], (
        f"the default for [{section}] {field} is {default!r}, which the table rejects"
    )
