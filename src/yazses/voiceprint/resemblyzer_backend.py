"""Resemblyzer speaker embedder (optional ``voiceprint-resemblyzer`` extra).

A 256-d d-vector encoder (GE2E, ~17 MB, CPU-runnable) offered alongside the
speechbrain ECAPA embedder in :mod:`yazses.voiceprint.factory`. Selected with
``[voiceprint] backend = "resemblyzer"``; imported only when that backend is
chosen and the extra is installed, so a base install never loads torch.

Why a second embedder exists at all: ECAPA is unreliable on the sub-second
windows the Cocktail Filter scores, which is why that feature defaults OFF
(``design/v2-cognitive-layer/02-cocktail-filter.md``). A lighter encoder is
worth having as a comparison point, not merely as plumbing.

Two Resemblyzer behaviours matter for that use and are handled deliberately
rather than left to defaults, because both *silently* degrade a short frame
instead of failing:

**Partial slicing zero-pads short audio, and cannot be told not to.**
``embed_utterance`` splits the buffer into 1.6 s partials and pads the tail with
zeros; its own docstring notes that when there are not enough frames for even
one partial, the coverage threshold "is ignored so that the function always
returns at least one slice". Handing it a 500 ms Cocktail-Filter window
therefore encodes 0.5 s of speech plus **1.1 s of digital silence** — partly an
embedding of the padding. There is no parameter that disables this. So below the
partial length this adapter bypasses ``embed_utterance`` and runs the encoder
directly on the frame's mel spectrogram: the network is an LSTM and accepts any
frame count, so the short path is the *same model*, just without the padding.

**Silence trimming can empty a short frame.** ``preprocess_wav`` always
normalises volume and runs a webrtcvad silence trim — neither is optional in
this version — so a window that is entirely silence comes back empty. That is
handled rather than left to produce a garbage vector: an empty buffer yields a
zero embedding, which :func:`~yazses.voiceprint.embedding.cosine_similarity`
defines as 0.0, so the Cocktail Filter drops the window instead of matching it
by accident.

Privacy: this returns vectors and nothing else. Embeddings are biometric and
are persisted only by :mod:`yazses.voiceprint.store` into the encrypted
learning corpus (ADR-011/012).
"""
from __future__ import annotations

import logging

import numpy as np

from yazses.voiceprint.embedding import Embedding

log = logging.getLogger(__name__)

# Resemblyzer's native rate, and the partial-utterance window it slices to.
# Both are properties of the pretrained model, not tunables.
_NATIVE_SR = 16000
_PARTIAL_SECONDS = 1.6



class ResemblyzerEmbedder:
    """Resemblyzer GE2E speaker encoder (256-d d-vector)."""

    def __init__(self, config) -> None:
        from resemblyzer import VoiceEncoder  # optional extra

        # device="cpu" is explicit: VoiceEncoder defaults to CUDA when torch sees
        # a GPU, and this project is CPU-only by design (ADR-011) — an implicit
        # GPU grab would surprise a user who enabled a dictation feature.
        self._encoder = VoiceEncoder(device="cpu", verbose=False)

    @property
    def name(self) -> str:
        return "resemblyzer"

    def embed(self, audio: np.ndarray, sample_rate: int = 16000) -> Embedding:
        """Compute a d-vector for *audio* (mono float32)."""
        wav = self._prepare(np.asarray(audio, dtype="float32").reshape(-1), sample_rate)
        if wav.size == 0:
            # Nothing to embed. A zero vector is the honest answer: cosine
            # similarity against it is defined as 0.0 (see embedding.py), so the
            # Cocktail Filter drops the window rather than matching it by accident.
            return Embedding(vector=np.zeros(256, dtype="float32"))

        # See the module docstring: embed_utterance zero-pads anything shorter
        # than one 1.6 s partial, so short frames take the unpadded path.
        if wav.size >= int(_PARTIAL_SECONDS * _NATIVE_SR):
            vector = self._encoder.embed_utterance(wav)
        else:
            vector = self._embed_short(wav)
        return Embedding(vector=np.asarray(vector, dtype="float32").reshape(-1))

    def _embed_short(self, wav: np.ndarray) -> np.ndarray:
        """Embed a sub-partial frame without zero-padding it to 1.6 s.

        Mirrors what ``embed_utterance`` does for a single partial — mel, forward,
        L2-normalise — but over the frame exactly as given. Kept to the encoder's
        public surface (``wav_to_mel_spectrogram`` and calling the module) so it
        does not depend on Resemblyzer internals.
        """
        import torch
        from resemblyzer import audio as rz_audio

        mel = rz_audio.wav_to_mel_spectrogram(wav)
        with torch.no_grad():
            batch = torch.from_numpy(mel[None, ...]).to(self._encoder.device)
            raw = self._encoder(batch).cpu().numpy()[0]
        norm = float(np.linalg.norm(raw, 2))
        # embed_utterance always divides by the norm; guard the degenerate case
        # rather than emitting NaNs into a cosine comparison.
        return raw / norm if norm > 0 else raw

    def _prepare(self, buf: np.ndarray, sample_rate: int) -> np.ndarray:
        """Resample to 16 kHz, normalise volume and drop silence.

        ``preprocess_wav`` does all three and offers no switches for any of them,
        so this is a thin wrapper whose only job is to pass ``source_sr`` only
        when a resample is actually needed — passing it redundantly at 16 kHz
        sends the buffer through librosa for nothing on every gate window.
        """
        from resemblyzer import preprocess_wav

        wav = preprocess_wav(
            buf, source_sr=sample_rate if sample_rate != _NATIVE_SR else None
        )
        return np.asarray(wav, dtype="float32").reshape(-1)
