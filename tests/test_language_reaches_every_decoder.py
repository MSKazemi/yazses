"""`[stt] language` reaches the decoder through one argument, and four callers dropped it.

`FasterWhisperEngine.__init__` takes `language: str = "en"` and stores it; `_decode_kwargs`
pins it on every decode. That default is the trap — a construction site that simply omits
the argument does not get auto-detection, it gets **English**, silently, for a user who
configured something else.

`stt/factory.py` threads it. Nothing else did:

* `yazses verify` built `FasterWhisperEngine` directly, so it also ignored `[stt] engine`.
  That command's whole claim is that it runs *the chain the daemon runs* and is "the only
  honest answer to 'is it definitely going to work when I press the key?'" — and it
  certified faster-whisper for a Parakeet user and English for a Persian one, then blamed
  the model: *"the model returned nothing… try a larger one with `[stt] model`"*.
* `yazses tune --retranscribe` re-transcribed the corpus to build **ground truth**. Decoded
  in the wrong language, every proposal drawn from it — vocabulary, thresholds, the model —
  was drawn from noise.
* `recimport/pipeline.py` (so `yazses transcribe` **and** `yazses meeting`'s post-pass) read
  `language` only to decide `task="translate"`. `--language fa` set nothing else, so Persian
  audio was transcribed as English with no error.

So the guard is not "these four are fixed". It is that **every** construction of the engine
in the tree passes the argument, which a new call site fails until it does.
"""
from __future__ import annotations

import ast
import pathlib
import types

import pytest

# The transcription stack cannot be installed on every platform this project runs on:
# `ctranslate2` (via faster-whisper) publishes no FreeBSD wheel and no sdist at all, so
# `pip install -e .` cannot bring it in there. Skipping here rather than keeping a
# hand-maintained ignore list in the CI job means a new decoder test that forgets this
# line fails loudly on that platform instead of silently reducing coverage (#306).
pytest.importorskip("faster_whisper", reason="the decoder stack has no FreeBSD build")

from yazses.config import MeetingConfig, RecimportConfig

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "yazses"

#: Non-vacuity: three sites exist today. A traversal that finds none would make the
#: assertion below true of a tree with the bug fully restored.
_MIN_SITES = 3


def _construction_sites() -> list[tuple[str, int, set[str]]]:
    """Every `FasterWhisperEngine(...)` call in the package, with its keyword names."""
    sites = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "FasterWhisperEngine":
                sites.append((
                    path.relative_to(SRC.parent.parent).as_posix(),
                    node.lineno,
                    {k.arg for k in node.keywords if k.arg},
                ))
    return sites


@pytest.fixture
def stub_model(monkeypatch):
    """Construct engines without loading a model — the language is set before any load."""
    import yazses.stt.faster_whisper as fw

    monkeypatch.setattr(
        fw, "_load_model",
        lambda *a, **k: types.SimpleNamespace(transcribe=lambda *a, **k: ([], None)),
    )


# --- every site, not the four that were wrong -----------------------------------


def test_there_are_construction_sites_to_check():
    assert len(_construction_sites()) >= _MIN_SITES


def test_every_engine_is_built_with_a_language():
    missing = [
        f"{path}:{line}" for path, line, kws in _construction_sites()
        if "language" not in kws
    ]
    assert not missing, (
        f"these build the decoder without a language, so it pins 'en' whatever the "
        f"user configured: {missing}"
    )


# --- verify runs the daemon's chain, which means the daemon's factory -----------


def _called_names(path: pathlib.Path, function: str) -> set[str]:
    """Every name *function* actually calls -- read from the AST, not the text.

    Structurally, because a first draft of this grepped the function's source and was
    tripped by the comment *explaining* the fix, which names the class it forbids. A
    comment cannot construct an engine.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function),
        None,
    )
    assert node is not None, f"{function} not found in {path}"
    return {
        (c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", ""))
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
    }


def test_verify_builds_its_engine_through_the_factory():
    """Otherwise `[stt] engine` is ignored and a Parakeet user is told Whisper works."""
    called = _called_names(SRC / "cli.py", "verify")
    assert "build_engine" in called
    assert "FasterWhisperEngine" not in called, (
        "verify must not construct a concrete engine -- the daemon calls "
        "build_engine(cfg.stt), and a check that claims to run the daemon's chain has "
        "to build what the daemon builds"
    )


def test_the_daemon_still_uses_the_factory():
    """The other half of the same comparison; it is what makes the first one mean anything."""
    daemon = (SRC / "core" / "daemon.py").read_text(encoding="utf-8")
    assert "build_engine(cfg.stt)" in daemon


# --- what the decoder ends up pinned to -----------------------------------------


@pytest.mark.parametrize("cls", [RecimportConfig, MeetingConfig])
def test_a_configured_language_reaches_the_decoder(stub_model, cls):
    from yazses.recimport.pipeline import _build_engine

    assert _build_engine(cls(language="fa", model="small"))._language == "fa"


def test_translate_is_not_a_language(stub_model):
    """It must auto-detect the source, which downstream spells as the empty string."""
    from yazses.recimport.pipeline import _build_engine

    assert _build_engine(RecimportConfig(language="translate", model="small"))._language == ""


def test_an_empty_language_still_means_auto_detect(stub_model):
    from yazses.recimport.pipeline import _build_engine

    assert _build_engine(RecimportConfig(language="", model="small"))._language == ""


def test_the_default_is_unchanged(stub_model):
    """The fix may only affect values that previously did nothing."""
    from yazses.recimport.pipeline import _build_engine

    assert _build_engine(RecimportConfig())._language == "en"


def test_a_foreign_language_on_an_english_checkpoint_warns(stub_model, caplog):
    """`.en` has no language tokens: it answers Persian with fluent English nonsense."""
    from yazses.recimport.pipeline import _build_engine

    with caplog.at_level("WARNING"):
        _build_engine(RecimportConfig(language="fa", model="small.en"))
    assert any("fa" in r.getMessage() for r in caplog.records), caplog.text


def test_a_matching_pair_says_nothing(stub_model, caplog):
    from yazses.recimport.pipeline import _build_engine

    with caplog.at_level("WARNING"):
        _build_engine(RecimportConfig(language="fa", model="small"))
    assert not caplog.records, caplog.text


def test_the_factory_and_the_pipeline_agree_on_the_same_wish(stub_model):
    """Two builders, one behaviour -- the drift this whole file exists to stop."""
    from yazses.config import SttConfig
    from yazses.recimport.pipeline import _build_engine
    from yazses.stt.factory import build_engine

    assert (
        build_engine(SttConfig(language="fa", model="small"))._language
        == _build_engine(RecimportConfig(language="fa", model="small"))._language
    )
