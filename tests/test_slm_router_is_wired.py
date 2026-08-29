"""Tier 2 must be reachable, and must stay off unless it is configured (#164).

`commands/grammar.py::classify` has taken an `slm_router` parameter since v0.4.0 and
**no caller ever passed one**. So `[commands] slm_model_path` and
`slm_confidence_threshold` were documented settings that could not have an effect
however they were set — the architecture reference marked both "⚠ inert" — and
`yazses tune` wrote a `few_shots.toml` that nothing read.

The risk in fixing that is the opposite one, and it is the more serious of the two:
Tier 2 loads a local language model and runs it on the dictation path. It must stay
completely absent for the overwhelming majority of users who configure no model, and
it must never turn a working Tier 1 into a broken burst when the model is missing or
llama-cpp-python is not installed. These tests pin both directions.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from yazses.commands.grammar import CommandIntent, IntentType, classify

ROOT = Path(__file__).resolve().parent.parent
DAEMON = ROOT / "src" / "yazses" / "core" / "daemon.py"


class _Daemon:
    """Enough of a daemon for the factory: it reads `_platform.paths.data_dir`."""

    def __init__(self, data_dir: Path) -> None:
        class _Paths:
            pass

        class _Platform:
            pass

        paths = _Paths()
        paths.data_dir = data_dir          # type: ignore[attr-defined]
        platform = _Platform()
        platform.paths = paths             # type: ignore[attr-defined]
        self._platform = platform


def _cfg(**commands):
    class _Commands:
        slm_model_path = commands.get("slm_model_path", "")
        slm_confidence_threshold = commands.get("slm_confidence_threshold", 0.6)

    class _Cfg:
        commands = _Commands()

    return _Cfg()


def _build(tmp_path: Path, **commands):
    from yazses.core.daemon import Daemon as RealDaemon

    return RealDaemon._build_slm_router(_Daemon(tmp_path), _cfg(**commands))


# ── it must stay off by default ──────────────────────────────────────────────

def test_no_model_path_means_no_router_at_all(tmp_path: Path) -> None:
    """The default. Tier 2 loads a language model; it must not appear uninvited."""
    assert _build(tmp_path) is None


def test_a_whitespace_path_is_not_a_path(tmp_path: Path) -> None:
    assert _build(tmp_path, slm_model_path="   ") is None


def test_a_configured_but_missing_model_degrades_to_tier_one(tmp_path: Path) -> None:
    """SLMRouter disables itself when the file is absent; we must return None then.

    Returning a disabled router would work — `classify` treats a None answer as a
    fall-through — but it would also log nothing and leave the user believing Tier 2
    was running. None is the honest value, and the factory logs the reason once.
    """
    assert _build(tmp_path, slm_model_path=str(tmp_path / "nope.gguf")) is None


def test_a_raising_constructor_cannot_break_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yazses.commands.slm_router as mod

    class _Boom:
        def __init__(self, *a, **k) -> None:
            raise RuntimeError("llama exploded")

    monkeypatch.setattr(mod, "SLMRouter", _Boom)
    assert _build(tmp_path, slm_model_path=str(tmp_path / "m.gguf")) is None


def test_an_unreadable_few_shots_file_does_not_cost_the_user_tier_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt tune artefact must not disable a model that would have worked."""
    import yazses.commands.slm_router as mod
    import yazses.learning.analysis as analysis

    def _boom(_path):
        raise OSError("unreadable")

    class _Router:
        _enabled = True

        def __init__(self, *a, **k) -> None:
            self.examples = k.get("extra_examples")

    monkeypatch.setattr(analysis, "load_few_shots", _boom)
    monkeypatch.setattr(mod, "SLMRouter", _Router)
    router = _build(tmp_path, slm_model_path=str(tmp_path / "m.gguf"))
    assert router is not None
    assert router.examples == []


def test_tuned_examples_reach_the_router(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`yazses tune` writes few_shots.toml; before this it was written for nobody."""
    (tmp_path / "few_shots.toml").write_text(
        "# a comment\n"
        '"open the file" -> {"intent": "navigate"}\n'
        "\n",
        encoding="utf-8",
    )
    import yazses.commands.slm_router as mod

    class _Router:
        _enabled = True

        def __init__(self, path, threshold=0.6, extra_examples=None) -> None:
            self.path = path
            self.threshold = threshold
            self.examples = extra_examples

    monkeypatch.setattr(mod, "SLMRouter", _Router)
    router = _build(
        tmp_path, slm_model_path=str(tmp_path / "m.gguf"), slm_confidence_threshold=0.81
    )
    assert router is not None
    assert router.examples == ['"open the file" -> {"intent": "navigate"}']
    assert router.threshold == 0.81, "the documented threshold must reach the router"


# ── and when it is on, it must actually be consulted ─────────────────────────

def test_the_daemon_passes_the_router_to_every_classify_call() -> None:
    """The whole defect in one line: the parameter existed and nobody filled it.

    Both call sites matter — command mode and the `[commands] enabled` dictation
    path — because wiring one and not the other is the shape this codebase has hit
    before (the cmdsafety gate guarded dictation and not the branch that executes).
    """
    text = DAEMON.read_text(encoding="utf-8")
    calls = [ln for ln in text.splitlines() if "classify(text, self._config.commands.profile" in ln]
    assert len(calls) == 2, f"expected two classify call sites, found {len(calls)}"
    assert text.count("slm_router=self._slm_router") == 2, (
        "a classify() call site does not pass the router — Tier 2 is unreachable "
        "from that path, which is exactly what this feature shipped as."
    )


def test_tier_two_only_runs_when_tier_one_found_no_command() -> None:
    """Tier 1 is regex and sub-millisecond; Tier 2 loads a model. Order matters."""
    seen: list[str] = []

    class _Router:
        def classify(self, text: str, profile: str = "default"):
            seen.append(text)
            return None

    # "save" is a Tier 1 command — the router must not be consulted.
    got = classify("save", slm_router=_Router())
    assert got.intent is not IntentType.DICTATE
    assert seen == [], "Tier 2 ran even though the regex grammar matched"

    # Ordinary prose is Tier 1 DICTATE, so Tier 2 gets its turn.
    classify("some words that match nothing", slm_router=_Router())
    assert seen == ["some words that match nothing"]


def test_a_router_that_answers_none_leaves_the_text_as_dictation() -> None:
    class _Silent:
        def classify(self, text: str, profile: str = "default"):
            return None

    got = classify("some words that match nothing", slm_router=_Silent())
    assert got.intent is IntentType.DICTATE


def test_a_router_that_raises_does_not_lose_the_burst() -> None:
    """A model failure mid-utterance must not swallow what the user said."""
    class _Broken:
        def classify(self, text: str, profile: str = "default"):
            raise RuntimeError("model died")

    try:
        got = classify("some words that match nothing", slm_router=_Broken())
    except RuntimeError:
        pytest.fail("a raising Tier 2 router propagated into the dictation path")
    assert got.intent is IntentType.DICTATE
    assert got.raw_text == "some words that match nothing"


def test_a_router_answer_is_used_when_it_gives_one() -> None:
    class _Router:
        def classify(self, text: str, profile: str = "default"):
            return CommandIntent(
                intent=IntentType.TERMINAL, action="run_tests", raw_text=text
            )

    got = classify("please run the tests for me", slm_router=_Router())
    assert got.intent is IntentType.TERMINAL
    assert got.action == "run_tests"
