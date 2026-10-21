"""The command-grammar seeds in the fuzz corpus must reach the rules they are named for.

A seed corpus is a claim that each string is worth mutating *from where it lands*.
For the command grammar that place is specific: a seed only helps libFuzzer explore
`go_to_line` if, after the cleaner and the disfluency filter, it is actually claimed
by the `go_to_line` rule. A seed that drifted into plain dictation still "passes"
`tests/test_fuzz_harnesses_still_run.py` -- it does not raise -- while teaching the
fuzzer nothing about the rule it was written for.

So the seeds are named for what they reach, and these tests hold the names to it:

* ``grammar-<lang>-<action>[-variant]`` -- classified as ``<action>`` by that
  language's Tier-1 grammar, in command mode's input (filtered, not punctuated).
* ``edit-<op>`` -- parsed by Spoken Edit Mode (`commands/edit_ops.py`) as ``<op>``.
* ``near-miss-<lang>-...`` -- one edit away from a command, and dictation.

And completeness is derived, not listed: every rule in every registered grammar, and
every edit operation, must have a seed it matches. A new rule added without a seed
fails here, which is the moment someone knows what a good seed for it looks like.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from yazses.commands import edit_ops
from yazses.commands.grammars.registry import get_grammar, registered_languages
from yazses.commands.types import IntentType

FUZZ = Path(__file__).resolve().parent.parent / "fuzz"
CORPUS = FUZZ / "corpus" / "fuzz_text_pipeline"


def _harness() -> ModuleType:
    """Import the harness by path, as `test_fuzz_harnesses_still_run.py` does."""
    spec = importlib.util.spec_from_file_location(
        "_fuzz_fuzz_text_pipeline_seeds", FUZZ / "fuzz_text_pipeline.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HARNESS = _harness()


def _command_input(name: str) -> str:
    """The seed as command mode's `classify` sees it: cleaned, then filtered."""
    p = HARNESS._load()
    raw = (CORPUS / name).read_bytes().decode("utf-8", errors="surrogatepass")
    return p["filter_transcript"](p["clean_text"](raw), p["disfluency_config"]).text


def _seeds(prefix: str) -> list[str]:
    return sorted(path.name for path in CORPUS.glob(f"{prefix}*"))


def _classify(text: str, language: str):
    return HARNESS._load()["classify"](text, "default", language=language)


def test_the_harness_fuzzes_every_registered_command_language() -> None:
    assert tuple(HARNESS.COMMAND_LANGUAGES) == tuple(registered_languages())


def test_each_seed_family_is_present() -> None:
    """Non-vacuity: the parametrised tests below iterate globs, and an empty glob is a
    test that passes by checking nothing."""
    for prefix in ("grammar-en-", "grammar-zh-", "edit-", "near-miss-en-", "near-miss-zh-"):
        assert _seeds(prefix), f"no {prefix}* seeds in {CORPUS}"


@pytest.mark.parametrize("name", _seeds("grammar-"))
def test_a_grammar_seed_is_claimed_by_the_action_it_is_named_for(name: str) -> None:
    _, language, rest = name.split("-", 2)
    action = rest.split("-", 1)[0]
    intent = _classify(_command_input(name), language)
    assert intent.intent is not IntentType.DICTATE, f"{name} is dictation, not a command"
    assert intent.action == action, f"{name} reached {intent.action!r}"


@pytest.mark.parametrize("name", _seeds("edit-"))
def test_an_edit_seed_parses_as_the_operation_it_is_named_for(name: str) -> None:
    op = name.split("-", 1)[1]
    parsed = edit_ops.parse_edit(_command_input(name))
    assert parsed is not None and parsed[0] == op, f"{name} parsed as {parsed!r}"


@pytest.mark.parametrize("name", _seeds("near-miss-"))
def test_a_near_miss_seed_is_dictation(name: str) -> None:
    language = name.split("-")[2]
    text = _command_input(name)
    assert _classify(text, language).intent is IntentType.DICTATE, f"{name} became a command"
    assert edit_ops.parse_edit(text) is None, f"{name} became a spoken edit"


@pytest.mark.parametrize("language", registered_languages())
def test_every_grammar_rule_has_a_seed_that_reaches_it(language: str) -> None:
    grammar = get_grammar(language)
    inputs = [grammar.normalise(_command_input(n)) for n in _seeds(f"grammar-{language}-")]
    unreached = [
        f"{i}: {rule.action} /{rule.pattern.pattern}/"
        for i, rule in enumerate(grammar.rules)
        if not any(rule.pattern.match(text) for text in inputs)
    ]
    assert not unreached, f"{language} rules with no seed in {CORPUS}: {unreached}"


def test_every_spoken_edit_operation_has_a_seed() -> None:
    reached = {
        parsed[0]
        for name in _seeds("edit-")
        if (parsed := edit_ops.parse_edit(_command_input(name))) is not None
    }
    missing = sorted(set(edit_ops._DISPATCH) - reached)
    assert not missing, f"spoken-edit operations with no seed: {missing}"
