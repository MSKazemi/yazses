"""Speaker diarization backend (lazy, heavy tier) — ADR-v2-125.

``SherpaDiarizer`` runs sherpa-onnx's offline diarization (pyannote segmentation-3.0 +
a speaker-embedding extractor + fast clustering) entirely on CPU via bundled ONNX
Runtime — no PyTorch, no GPU, no Hugging-Face token (research §1). It is imported
lazily and constructed only through :func:`yazses.recimport.factory.build_diarizer`, so
the base install and CI never load it. ``PyannoteDiarizer`` is a dormant backend name.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Filenames sherpa-onnx models are stored under in the diarization model dir.
_SEG_MODEL = "sherpa-onnx-pyannote-segmentation-3-0.onnx"
_EMB_MODEL = "3dspeaker-eres2net-base.onnx"


@dataclass(frozen=True)
class DiarTurn:
    """One diarized speaker turn (seconds); ``speaker`` is a canonical cluster id."""
    start: float
    end: float
    speaker: str


def model_dir(config) -> Path:
    """Directory holding the sherpa diarization model files."""
    override = getattr(config, "model_dir", "") or ""
    if override:
        return Path(override).expanduser()
    from yazses.platform import get_platform

    return get_platform().paths.data_dir / "diarization"


def models_present(config) -> bool:
    """True when both sherpa model files exist locally."""
    d = model_dir(config)
    return (d / _SEG_MODEL).exists() and (d / _EMB_MODEL).exists()


class SherpaDiarizer:
    """Offline CPU diarizer backed by sherpa-onnx."""

    def __init__(self, config) -> None:
        import sherpa_onnx  # optional `diarization` extra

        d = model_dir(config)
        seg = d / _SEG_MODEL
        emb = d / _EMB_MODEL
        if not (seg.exists() and emb.exists()):
            raise FileNotFoundError(
                f"Diarization models not found in {d}. Run "
                "`yazses transcribe --download-models` first."
            )

        num = int(getattr(config, "max_speakers", 0) or 0)
        threshold = float(getattr(config, "cluster_threshold", 0.5) or 0.5)
        sd_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(seg),
                ),
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb)),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=num if num > 0 else -1,
                threshold=threshold,
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not sd_config.validate():
            raise ValueError("Invalid sherpa-onnx diarization configuration.")
        self._sd = sherpa_onnx.OfflineSpeakerDiarization(sd_config)
        self._expected_sr = self._sd.sample_rate

    def diarize(self, audio, sample_rate: int = 16000):
        """Return diarized turns for 16 kHz mono float32 ``audio``. Sorted by start."""
        result = self._sd.process(audio).sort_by_start_time()
        return [
            DiarTurn(float(seg.start), float(seg.end), f"speaker_{seg.speaker}")
            for seg in result
        ]
