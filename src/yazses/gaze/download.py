"""Fetch the MediaPipe FaceLandmarker model for the gaze backend.

A single ~3.7 MB TFLite model (``face_landmarker.task``) drives the iris-based
gaze estimate. It is cached under the user cache dir and downloaded once on first
use; everything afterwards is fully offline (ADR-011 — nothing leaves the machine
at run time).
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

from platformdirs import PlatformDirs

# Pinned Google-hosted release asset (float16 FaceLandmarker bundle, incl. iris).
FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)


def model_dir() -> Path:
    """Return the per-user cache directory holding gaze models."""
    dirs = PlatformDirs(appname="yazses", appauthor=False, ensure_exists=False)
    return Path(dirs.user_cache_dir) / "models"


def ensure_face_landmarker(dest: Path | None = None, *, echo=None) -> Path:
    """Return the FaceLandmarker model path, downloading it once if absent."""
    dest = dest or (model_dir() / "face_landmarker.task")
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if echo:
        echo(f"Downloading gaze model (~3.7 MB) → {dest} ...")
    urllib.request.urlretrieve(FACE_LANDMARKER_URL, dest)  # noqa: S310 - fixed https asset
    return dest
