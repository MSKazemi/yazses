"""ECAPA-TDNN speaker embedder (speechbrain — optional ``voiceprint`` extra).

Produces a d-vector for a mono float32 buffer using the pretrained
``speechbrain/spkrec-ecapa-voxceleb`` encoder (Apache-2.0, ~20 MB, CPU-runnable).
Imported only when ``[voiceprint] enabled`` and the extra is installed — the
factory falls back to None otherwise (so this file's deps are never required in CI).
"""
from __future__ import annotations

import numpy as np

from yazses.system.hfcache import load_cache_first
from yazses.voiceprint.embedding import Embedding


class EcapaEmbedder:
    """speechbrain ECAPA-TDNN speaker encoder."""

    def __init__(self, config) -> None:
        import torch  # noqa: F401  (optional extra)
        from speechbrain.inference.speaker import EncoderClassifier

        self._torch = __import__("torch")
        # Cache-first: speechbrain has no `local_files_only`, and this fires on
        # `yazses meeting enroll` and on any transcript that names a speaker from a
        # voiceprint. See `system/hfcache.py` for why a hub round-trip can hang forever.
        self._model = load_cache_first(
            lambda: EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                run_opts={"device": "cpu"},
            ),
            what="the ECAPA speaker encoder",
        )

    @property
    def name(self) -> str:
        return "ecapa"

    def embed(self, audio: np.ndarray, sample_rate: int = 16000) -> Embedding:
        wav = self._torch.tensor(
            np.asarray(audio, dtype="float32")
        ).unsqueeze(0)
        with self._torch.no_grad():
            emb = self._model.encode_batch(wav).squeeze().detach().cpu().numpy()
        return Embedding(vector=np.asarray(emb, dtype="float32").reshape(-1))
