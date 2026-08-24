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


def warn_pinned_count(num_speakers: int, threshold: float) -> str:
    """Say so when a pinned speaker count makes ``cluster_threshold`` do nothing.

    `sherpa_onnx.FastClusteringConfig` takes both a `num_clusters` and a `threshold`,
    and uses the threshold **only** when the count is unset: pin the count and the
    agglomeration simply stops at that many clusters, so the threshold is inert.

    That is not a detail. `cluster_threshold` is the setting ADR-v2-133 changed --
    0.5 to 1.2 took corpus DER on the AMI test split from 75.21 % to 26.71 %, the
    largest single improvement on `docs/benchmarks.md` -- and **none of it reaches a
    user who supplies a speaker count.** Measured, not reasoned: threshold 0.5 with
    `max_speakers = 4` and threshold 1.2 with `max_speakers = 4` are **bit-identical
    on all sixteen AMI recordings**, which is how the interaction was found at all.
    Both settings are documented in the same config table with no hint that one
    silences the other.

    Returns the message (so it can be tested and surfaced) or `""` when the two do
    not conflict. Logged rather than raised: a pinned count is a legitimate request
    and the run must proceed -- what was missing was any indication that half of what
    the user configured was being discarded.
    """
    if num_speakers <= 0:
        return ""
    msg = (
        f"max_speakers={num_speakers} pins the cluster count, so cluster_threshold="
        f"{threshold:g} has no effect on this run. Supplying a speaker count is also "
        "not measurably more accurate than letting the clustering estimate it: on the "
        "AMI test split it fixed the speaker count (mean error 2.06 -> 0.06) and left "
        "DER unresolvable either way (7 of 16 recordings better, 7 worse, sign-test "
        "p=1.0), with a per-recording swing from -15.99 to +28.72 points. Use it when "
        "you need the count itself to be right; drop it if you want the tuned threshold."
    )
    log.warning(msg)
    return msg


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
        warn_pinned_count(num, threshold)
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
