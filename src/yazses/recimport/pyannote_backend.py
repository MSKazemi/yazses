"""pyannote.audio diarization backend (optional ``diarization-pyannote`` extra).

The accuracy option behind ``[recimport] backend = "pyannote"`` / ``[meeting]
backend = "pyannote"``, alongside the default :class:`~yazses.recimport.diarizer
.SherpaDiarizer`. Same contract — :meth:`diarize` takes 16 kHz mono float32 and
returns ``DiarTurn``s sorted by start — so ``recimport/pipeline.py`` and Meeting
Mode's finalize pass need no changes at all.

Choosing between them is a real trade, which is why the seam exists: sherpa-onnx
runs on bundled ONNX Runtime with no torch, no GPU and no token, while pyannote
pulls the full torch stack and a gated model download but is the accuracy
reference in open diarization. For a meeting transcript that is read once and
kept, accuracy usually wins; for anything on the dictation path it does not.

**Speaker ids are normalised.** pyannote emits ``SPEAKER_00``; sherpa emits
integer cluster ids that this project renders as ``speaker_0``. The naming and
alignment stages downstream key off that shape, so this adapter converts rather
than passing pyannote's own labels through — otherwise switching backend would
silently change every label in a stored transcript and break voiceprint naming.

**Nothing about the audio leaves the machine (ADR-011)** — but that took work
here, and the reason is the single most important thing in this file.

pyannote.audio 4.x **ships OpenTelemetry usage tracking that is on by default.**
Its bundled ``telemetry/config.yaml`` reads::

    metrics_enabled: true
    otlp_endpoint: https://otel.pyannote.ai/v1/traces
    telemetry_log_level: CRITICAL

``track_model_init`` / ``track_pipeline_init`` / ``track_pipeline_apply`` POST
spans to that endpoint — including, for every ``apply``, the **duration of the
audio being diarized** and the requested speaker counts. The log level is pinned
to CRITICAL, so a failed or successful export says nothing either way. It is not
an optional extra: ``opentelemetry-exporter-otlp`` and ``pyannoteai-sdk`` are
hard requirements of the package.

For this project that is disqualifying unless it is off, so
:func:`_disable_upstream_telemetry` sets ``PYANNOTE_METRICS_ENABLED=false``
*before* the import. That ordering is the whole mechanism: ``metrics.py``
defaults the variable from ``config.yaml`` only ``if "PYANNOTE_METRICS_ENABLED"
not in os.environ``, so a value set first is left alone, whereas calling
``set_telemetry_metrics(False)`` afterwards would already have let the
import-time tracker fire. No meeting audio was ever sent — but its *length* and
your usage pattern would have been, silently, from a tool whose entire promise
is that nothing leaves the machine.

The only network access this backend then makes is the *one-time model download*
from Hugging Face, because ``pyannote/speaker-diarization-3.1`` is a gated repo
whose conditions must be accepted once. The token is read from the environment
or the standard Hugging Face cache and is **deliberately not a config key** —
``yazses report`` bundles the config, and a credential in ``config.toml`` is a
credential that ends up in diagnostic bundles.
"""
from __future__ import annotations

import logging
import os

import numpy as np

from yazses.recimport.diarizer import DiarTurn

log = logging.getLogger(__name__)

# The gated pretrained pipeline. Pinned rather than tracking "latest": a
# diarization model change alters every speaker boundary, and a stored meeting
# transcript should not shift because an upstream default moved.
_PIPELINE = "pyannote/speaker-diarization-3.1"

# Checked in order; the first non-empty wins. These are the names the
# huggingface_hub tooling itself honours, so a user who has already run
# `huggingface-cli login` needs no extra setup.
_TOKEN_ENV = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN")


# The switch pyannote.audio reads for its usage tracking. See the module
# docstring: it must be set *before* the package is imported.
_TELEMETRY_ENV = "PYANNOTE_METRICS_ENABLED"


def _disable_upstream_telemetry(env: dict | None = None) -> None:
    """Turn off pyannote.audio's OpenTelemetry export before it can initialise.

    Unconditional, and deliberately not a config option: ADR-011 is not a
    preference users toggle. If someone has explicitly exported the variable
    themselves it is still overwritten — an environment variable set by a
    third-party tool is not informed consent to transmit dictation metadata,
    and the honest place to change this is a fork, not an env var.
    """
    target = os.environ if env is None else env
    target[_TELEMETRY_ENV] = "false"


def _auth_token() -> str | bool:
    """Return an explicit HF token, or ``True`` to use the cached login."""
    for name in _TOKEN_ENV:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    # True tells huggingface_hub to use the token stored by `huggingface-cli
    # login`. Returning None instead would silently attempt an anonymous fetch
    # of a gated repo and fail with a bare 401.
    return True


class PyannoteDiarizer:
    """Speaker diarization via pyannote.audio's pretrained pipeline."""

    def __init__(self, config) -> None:
        # MUST precede the pyannote import — see the module docstring.
        _disable_upstream_telemetry()

        import torch
        from pyannote.audio import Pipeline

        self._torch = torch
        pipeline = Pipeline.from_pretrained(_PIPELINE, use_auth_token=_auth_token())
        if pipeline is None:
            # from_pretrained returns None (rather than raising) when the repo is
            # gated and the token is missing or has not accepted the conditions.
            # Say which of those it is, because the fixes are different.
            raise RuntimeError(
                f"Could not load {_PIPELINE}. Accept the model conditions at "
                f"https://hf.co/{_PIPELINE} with your Hugging Face account, then "
                "either run `huggingface-cli login` or set HF_TOKEN. The download "
                "happens once; diarization itself runs offline."
            )
        # CPU is explicit for the same reason as the voiceprint backends: this
        # project is CPU-only by design and should not silently claim a GPU.
        self._pipeline = pipeline.to(torch.device("cpu"))

        self._min_speakers = int(getattr(config, "min_speakers", 0) or 0)
        self._max_speakers = int(getattr(config, "max_speakers", 0) or 0)

    def _speaker_bounds(self) -> dict:
        """Translate the config's 0-means-auto convention to pyannote kwargs."""
        bounds = {}
        if self._min_speakers > 0:
            bounds["min_speakers"] = self._min_speakers
        if self._max_speakers > 0:
            bounds["max_speakers"] = self._max_speakers
        # Both set and equal means the count is known exactly; pyannote wants
        # num_speakers for that case and rejects the redundant min/max pair.
        if bounds.get("min_speakers") == bounds.get("max_speakers") and bounds:
            return {"num_speakers": self._min_speakers}
        return bounds

    def diarize(self, audio, sample_rate: int = 16000) -> list[DiarTurn]:
        """Return diarized turns for 16 kHz mono float32 ``audio``, sorted by start."""
        buf = np.asarray(audio, dtype="float32").reshape(1, -1)  # (channel, time)
        waveform = self._torch.from_numpy(buf)

        with self._torch.no_grad():
            annotation = self._pipeline(
                {"waveform": waveform, "sample_rate": int(sample_rate)},
                **self._speaker_bounds(),
            )

        # pyannote labels are arbitrary strings (SPEAKER_00, SPEAKER_01, …) and
        # are not guaranteed to be dense or ordered. Map them to the dense
        # speaker_<n> ids the rest of the pipeline expects, in first-appearance
        # order so the numbering is stable and reads naturally in a transcript.
        ids: dict[str, int] = {}
        turns: list[DiarTurn] = []
        for segment, _, label in annotation.itertracks(yield_label=True):
            index = ids.setdefault(label, len(ids))
            turns.append(
                DiarTurn(float(segment.start), float(segment.end), f"speaker_{index}")
            )
        turns.sort(key=lambda t: t.start)
        return turns
