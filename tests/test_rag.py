"""Voice-grounded RAG retrieval ranking + cited context (ADR-v2-020) — pure."""
from __future__ import annotations

from yazses.rag.retrieve import Chunk, cosine, format_context, rank_chunks


def test_cosine_identical_is_one():
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_cosine_orthogonal_is_zero():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_zero_vector_is_zero():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_rank_sorts_and_filters_and_limits():
    chunks = [
        Chunk("a.md", "low", 0.1),
        Chunk("b.md", "high", 0.9),
        Chunk("c.md", "mid", 0.5),
    ]
    ranked = rank_chunks(chunks, top_k=2, min_score=0.2)
    assert [c.text for c in ranked] == ["high", "mid"]


def test_rank_top_k_zero_returns_all_passing():
    chunks = [Chunk("a", "x", 0.3), Chunk("b", "y", 0.1)]
    ranked = rank_chunks(chunks, top_k=0, min_score=0.2)
    assert [c.text for c in ranked] == ["x"]


def test_format_context_has_citations_and_sources():
    chunks = [Chunk("notes/a.md", "alpha", 0.9), Chunk("notes/b.md", "beta", 0.8)]
    out = format_context(chunks)
    assert "[1] alpha" in out and "[2] beta" in out
    assert "Sources:" in out and "[1] notes/a.md" in out and "[2] notes/b.md" in out


def test_format_context_empty():
    assert format_context([]) == ""


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "rag" in [f.slug for f in feature_status(Config())]
    assert Config().rag.enabled is False
