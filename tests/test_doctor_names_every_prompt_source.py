"""`doctor` reported one of the four things that reach Whisper's `initial_prompt`.

Measured on a real machine: `yazses vocab list` printed **24 words** while, in the same
minute, `yazses doctor` printed *"STT prompt: app name only (set [stt] initial_prompt to
add vocabulary)"*. Both were describing the same run. The daemon
(`core/daemon.py::_effective_initial_prompt`) merges the configured prompt, the personal
dictionary, `YAZSES_VOCABULARY` and — when `[personalize]` is on — corpus-mined terms;
`doctor` read the first and described it as the whole.

That is worse than an incomplete row. It told a user who had already added vocabulary,
by the route the product documents, to go and add vocabulary — so the honest reading is
that `yazses vocab add` had done nothing, which would have sent someone debugging a
feature that was working.

The guard at the bottom is the point of the file: it pins the describing surface to the
composing one, so a fifth source cannot be merged into the prompt while the diagnostic
still names four.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from yazses.config import load_config
from yazses.core.daemon import Daemon
from yazses.system import doctor
from yazses.system.vocabulary import prompt_summary

_WORDS = ["YazSes", "NovaFabric", "KubeIntellect", "MSKazemi", "kube-q"]


@pytest.fixture(autouse=True)
def _no_host_vocabulary(monkeypatch):
    """A row that reads the environment must not read the developer's environment."""
    monkeypatch.delenv("YAZSES_VOCABULARY", raising=False)


# --- the summary ------------------------------------------------------------------

def test_an_empty_setup_still_says_the_app_name_is_primed():
    assert prompt_summary("", []) == (
        "app name only — add words with `yazses vocab add <word>`"
    )


def test_a_personal_dictionary_is_never_reported_as_nothing():
    """The defect, stated directly."""
    detail = prompt_summary("", _WORDS)
    assert "only" not in detail
    assert "5 from `yazses vocab`" in detail


def test_it_stops_telling_you_to_do_what_you_have_already_done():
    assert "add words with" not in prompt_summary("", _WORDS)


def test_the_first_few_words_are_named_so_you_recognise_your_own_list():
    detail = prompt_summary("", _WORDS)
    assert "YazSes, NovaFabric, KubeIntellect" in detail
    assert "+2 more" in detail


def test_a_short_list_gains_no_more_suffix():
    assert "more" not in prompt_summary("", ["alpha", "beta"])


def test_blank_entries_do_not_inflate_the_count():
    assert "2 from" in prompt_summary("", ["alpha", "  ", "", "beta"])


def test_the_configured_prompt_is_still_reported():
    assert "kubernetes helm" in prompt_summary("kubernetes helm", [])


def test_a_long_configured_prompt_is_truncated_rather_than_flooding_the_row():
    detail = prompt_summary("w " * 60, [])
    assert "..." in detail
    assert len(detail) < 120


def test_the_environment_variable_is_named_too():
    assert "YAZSES_VOCABULARY" in prompt_summary("", [], ["acme", "widget"])


def test_mined_terms_are_named_only_when_personalize_is_on():
    assert "mined" not in prompt_summary("", _WORDS, mined=False)
    assert "mined" in prompt_summary("", _WORDS, mined=True)


def test_context_priming_is_named_only_when_it_is_on():
    assert "active window" not in prompt_summary("", _WORDS, context=False)
    assert "active window" in prompt_summary("", _WORDS, context=True)


def test_every_source_appears_when_every_source_is_present():
    detail = prompt_summary("helm", _WORDS, ["acme"], mined=True, context=True)
    for expected in (
        "initial_prompt", "yazses vocab", "YAZSES_VOCABULARY", "mined", "active window",
    ):
        assert expected in detail


# --- the row doctor actually prints -------------------------------------------------

def test_the_row_reads_the_dictionary_that_is_on_disk(tmp_path):
    (tmp_path / "vocabulary.txt").write_text("\n".join(_WORDS), encoding="utf-8")
    rows = doctor._config_summary(load_config(None), tmp_path / "config.toml")
    detail = {n: d for n, _s, d in rows}["STT prompt"]
    assert "5 from `yazses vocab`" in detail


def test_the_row_says_app_name_only_when_there_is_genuinely_nothing(tmp_path):
    rows = doctor._config_summary(load_config(None), tmp_path / "config.toml")
    assert {n: d for n, _s, d in rows}["STT prompt"].startswith("app name only")


def test_an_unreadable_dictionary_does_not_break_the_diagnostic(tmp_path):
    """`load_vocab` is tolerant; a diagnostic must not be the thing that raises."""
    (tmp_path / "vocabulary.txt").mkdir()
    rows = doctor._config_summary(load_config(None), tmp_path / "config.toml")
    assert {n: d for n, _s, d in rows}["STT prompt"].startswith("app name only")


def test_the_row_does_not_read_a_dictionary_beside_some_other_config(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "vocabulary.txt").write_text("ghost", encoding="utf-8")
    rows = doctor._config_summary(load_config(None), tmp_path / "config.toml")
    assert "ghost" not in {n: d for n, _s, d in rows}["STT prompt"]


# --- the guard ------------------------------------------------------------------------

#: Every source `_effective_initial_prompt` folds into the prompt, named by the token
#: that appears in its source. `_personal_bias_terms` is the mining call; `doctor`
#: reports its *gate* rather than running it, because mining opens the encrypted corpus
#: and a status row may not pay for that.
#: `compose_context_prompt` is Context-Primed Dictation (ADR-v2-004) — the fifth source,
#: and the one this guard was written without and had to be taught. Like mining, it is
#: reported as its gate: the terms come from the focused window and are gone by the time
#: a status row could print them.
_SOURCES = (
    "initial_prompt",
    "load_vocab",
    "YAZSES_VOCABULARY",
    "_personal_bias_terms",
    "compose_context_prompt",
)

_DOCTOR_EQUIVALENT = {
    "_personal_bias_terms": "personalize.enabled",
    "compose_context_prompt": "context.enabled",
}


def test_the_daemon_still_merges_exactly_these_sources():
    """If this fails, a source was added or renamed — teach the row about it."""
    src = inspect.getsource(Daemon._effective_initial_prompt)
    for token in _SOURCES:
        assert token in src, f"{token} no longer appears in _effective_initial_prompt"


def test_doctor_names_every_prompt_source():
    src = inspect.getsource(doctor._config_summary)
    for token in _SOURCES:
        expected = _DOCTOR_EQUIVALENT.get(token, token)
        assert expected in src, (
            f"the daemon merges {token} into the STT prompt and `doctor` never looks at "
            f"it — the row would describe less than the product does"
        )


def test_the_description_lives_where_a_diagnostic_can_afford_to_import_it():
    """Keeping it out of `stt/` is what lets `doctor` describe a prompt engine-free."""
    src = Path("src/yazses/system/vocabulary.py").read_text(encoding="utf-8")
    assert "prompt_summary" in src
    assert "faster_whisper" not in src


# --- the restart nobody needed ---------------------------------------------------------

def test_the_dictionary_is_re_read_without_a_restart(tmp_path):
    """`vocab add` printed "Apply it: yazses restart". It never needed one.

    `_effective_initial_prompt` is called from `_on_hold_end`, i.e. once per burst, and
    `load_vocab` is uncached — so a word added now is primed on the next dictation. The
    product asked for a daemon restart (and the model reload behind it) five times over
    for a file it re-reads anyway. Proven against the same object, not a fresh one.
    """
    cfg = load_config(None)
    same_daemon = SimpleNamespace(
        _config=cfg,
        _platform=SimpleNamespace(
            paths=SimpleNamespace(config_file=tmp_path / "config.toml")
        ),
        _personal_bias_terms=lambda: [],
    )
    compose = Daemon._effective_initial_prompt

    (tmp_path / "vocabulary.txt").write_text("Zarquon", encoding="utf-8")
    before = compose(same_daemon) or ""
    (tmp_path / "vocabulary.txt").write_text("Zarquon\nBetelgeuse", encoding="utf-8")
    after = compose(same_daemon) or ""

    assert "Betelgeuse" not in before
    assert "Betelgeuse" in after


def test_the_app_name_is_primed_even_with_an_empty_dictionary(tmp_path):
    cfg = load_config(None)
    fake = SimpleNamespace(
        _config=cfg,
        _platform=SimpleNamespace(
            paths=SimpleNamespace(config_file=tmp_path / "config.toml")
        ),
        _personal_bias_terms=lambda: [],
    )
    assert "YazSes" in (Daemon._effective_initial_prompt(fake) or "")


def _vocab_command_sources() -> dict[str, str]:
    """Every ``yazses vocab`` subcommand's source, decorators included.

    Sliced by AST rather than by hand. The first version of this guard indexed between
    two literal `@vocab_app.command(` occurrences and so covered add/list/remove and
    silently skipped `import` and `export` -- where a sixth "Run `yazses restart` to
    apply" was sitting the whole time. A guard that names the region it checks is a
    guard that stops checking the moment a command is added after it.
    """
    src = Path("src/yazses/cli.py").read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    out: dict[str, str] = {}
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("vocab_"):
            continue
        first = min([node.lineno] + [d.lineno for d in node.decorator_list])
        out[node.name] = "".join(lines[first - 1:node.end_lineno])
    return out


def test_the_guard_can_see_every_vocab_subcommand():
    """If this shrinks, the guard below is checking less than it claims."""
    found = set(_vocab_command_sources())
    assert {"vocab_add", "vocab_list", "vocab_remove", "vocab_import", "vocab_export"} <= found


def test_no_vocabulary_surface_still_demands_a_restart():
    """Six places said so — the sixth only after the first guard was widened."""
    for name, body in _vocab_command_sources().items():
        assert "yazses restart" not in body, (
            f"{name} still asks for a restart the daemon does not need"
        )

    for doc in ("docs/how-to/personal-vocabulary.md", "docs/cli-reference.md"):
        text = Path(doc).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "yazses restart" in line and "vocab" in line:
                raise AssertionError(f"{doc}: still pairs vocab with a restart — {line!r}")
