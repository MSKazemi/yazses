"""Fetch the sherpa-onnx diarization models (ADR-v2-125).

Downloads the pyannote segmentation-3.0 ONNX model and a 3D-Speaker embedding extractor
from the k2-fsa GitHub releases into the diarization model dir, under the filenames the
:class:`~yazses.recimport.diarizer.SherpaDiarizer` expects. Explicit, on-demand, one-time
(~45 MB) — nothing downloads unless the user runs ``yazses transcribe --download-models``
(ADR-011). Network/tooling dependent, so exercised manually, not in CI.
"""
from __future__ import annotations

import bz2
import io
import logging
import tarfile
import urllib.request
from pathlib import Path

from yazses.recimport.diarizer import _EMB_MODEL, _SEG_MODEL, model_dir

log = logging.getLogger(__name__)

_SEG_TARBALL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
_EMB_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
)


def download_models(config, *, echo=print) -> Path:
    """Ensure both diarization model files exist in the model dir; return that dir."""
    dest = model_dir(config)
    dest.mkdir(parents=True, exist_ok=True)

    seg = dest / _SEG_MODEL
    if not seg.exists():
        echo(f"Downloading segmentation model → {seg} …")
        _fetch_seg_from_tarball(_SEG_TARBALL, seg)
    else:
        echo(f"Segmentation model present: {seg}")

    emb = dest / _EMB_MODEL
    if not emb.exists():
        echo(f"Downloading embedding model → {emb} …")
        emb.write_bytes(_get(_EMB_URL))
    else:
        echo(f"Embedding model present: {emb}")

    echo("Diarization models ready.")
    return dest


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url) as resp:  # noqa: S310 - fixed https release URLs
        return resp.read()


def _fetch_seg_from_tarball(url: str, out_path: Path) -> None:
    """Download the segmentation tar.bz2 and extract its ``model.onnx`` to *out_path*."""
    raw = bz2.decompress(_get(url))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        member = next((m for m in tar.getmembers() if m.name.endswith("model.onnx")), None)
        if member is None:
            raise RuntimeError("segmentation tarball did not contain model.onnx")
        extracted = tar.extractfile(member)
        if extracted is None:
            raise RuntimeError("could not read model.onnx from segmentation tarball")
        out_path.write_bytes(extracted.read())
