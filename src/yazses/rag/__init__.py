"""Voice-grounded RAG over personal notes (ADR-v2-020).

Ask by voice, answer grounded in — and citing — your own local documents. Distinct
from Spoken Recall (which searches past dictations). This package's ``retrieve`` module
is the pure retrieval-ranking + cited-context layer; the embedding model, the
``sqlite-vec`` index, and the answer LLM are lazy behind the ``rag`` extra. OFF by default.
"""
