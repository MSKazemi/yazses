"""Tests for Context-Primed Dictation core (v2.0.0 Wave A, ADR-v2-004)."""

from yazses.commands.context import (
    ContextSources,
    compose_context_prompt,
    deictic_target,
    extract_terms,
    has_deixis,
)


def test_extract_terms_drops_stopwords_and_dupes():
    terms = extract_terms("the parser and the Parser handle the AST node")
    lowered = [t.lower() for t in terms]
    assert "the" not in lowered and "and" not in lowered
    assert lowered.count("parser") == 1  # case-insensitive dedupe


def test_extract_terms_ranks_identifiers_first():
    terms = extract_terms("we edited parse_config and the Widget and a plain word")
    # identifier-like first, then Capitalized, then plain
    assert terms[0] == "parse_config"
    assert terms.index("Widget") < terms.index("plain")


def test_extract_terms_caps_count():
    text = " ".join(f"term{i}" for i in range(100))
    assert len(extract_terms(text, max_terms=10)) == 10


def test_compose_prompt_lsp_symbols_first():
    src = ContextSources(
        window_title="editing main.py",
        lsp_symbols=["LspContextProvider", "dispatch"],
    )
    out = compose_context_prompt(src)
    assert out.startswith("LspContextProvider, dispatch")


def test_compose_prompt_respects_source_toggles():
    src = ContextSources(window_title="SecretWindow", clipboard="ClipWord")
    # clipboard off by default → ClipWord excluded; window on → SecretWindow present
    out = compose_context_prompt(src, use_clipboard=False)
    assert "SecretWindow" in out and "ClipWord" not in out
    out2 = compose_context_prompt(src, use_clipboard=True)
    assert "ClipWord" in out2


def test_compose_prompt_dedupes_across_sources():
    src = ContextSources(
        window_title="Widget editor", selection="the Widget", lsp_symbols=["Widget"]
    )
    out = compose_context_prompt(src)
    assert out.split(", ").count("Widget") == 1


def test_has_deixis_and_target():
    assert has_deixis("rename this function")
    assert has_deixis("close that") and has_deixis("insert it here")
    assert not has_deixis("rename the function")
    assert deictic_target(ContextSources(selection="  foo_bar  ")) == "foo_bar"
    assert deictic_target(ContextSources()) == ""


def test_extract_terms_empty_text_returns_empty():
    assert extract_terms("") == []
    assert extract_terms("", max_terms=10) == []
