"""The face switch on the shared camera: when to lease it, and how stale is too stale (pure).

ADR-v2-145 puts one owner behind every camera feature. The face switch was the second feature
(after Glance-Type gaze) that opened its own ``cv2.VideoCapture`` and its own FaceLandmarker, so
with ``[perception]`` on it contended with gaze and the Head-Pointer ("device already busy").
This module is the decision half of the move, mirroring :func:`yazses.gaze.shared.shared_source_for_gaze`;
the loop that reads the lease is in :mod:`yazses.facegesture.backend`.

Nothing here imports OpenCV, MediaPipe or a thread, and nothing is opened: the answer is a value.
"""
from __future__ import annotations

from yazses.gaze.shared import SharedSourceChoice

__all__ = [
    "MAX_SAMPLE_AGE_S",
    "NO_BLENDSHAPE_WARN_AFTER",
    "SharedSourceChoice",
    "shared_source_for_facegesture",
]

#: Oldest observation the switch will still count as a frame. At the source's default 15 fps a
#: fresh sample is ~70 ms old; this leaves room for a slow frame or two and nothing more, and it
#: is the same bound Glance-Type uses (``gaze/shared.py``). Past it the camera is treated as
#: blind: the frame reads as "no reading", which can only count toward *release*, so a camera
#: that stalls mid-hold closes the microphone instead of holding it on the last value.
#: **A starting bound, not a measured threshold.**
MAX_SAMPLE_AGE_S = 0.5

#: Consecutive fresh observations with no usable blendshape channel before the switch says so
#: once. The source is fine and other channels may be flowing; only this feature has nothing to
#: read, and a switch that is silently inert looks exactly like a switch that is working.
NO_BLENDSHAPE_WARN_AFTER = 30


def shared_source_for_facegesture(face_config, perception_config, source) -> SharedSourceChoice:
    """Decide whether the face switch may use *source*; pure, nothing is opened.

    The switch shares the camera only when sharing is *correct*:

    * there is a source at all (``[perception]`` on, or a feature that implies it, with a
      backend wired);
    * both sections name the **same camera**. Different indexes are different physical cameras,
      so two owners there is correct rather than a contention, and the user who pointed the
      face switch at the second webcam meant that webcam.

    Anything else returns ``source=None`` and the backend keeps the own-capture path exactly as
    it has always run.
    """
    if source is None:
        return SharedSourceChoice(None, "no shared camera source is configured")
    face_index = getattr(face_config, "camera_index", 0)
    shared_index = getattr(perception_config, "camera_index", 0)
    if face_index != shared_index:
        return SharedSourceChoice(
            None,
            f"[facegesture] camera_index = {face_index} but [perception] camera_index = "
            f"{shared_index}; they are different cameras, so the face switch keeps its own",
        )
    return SharedSourceChoice(source, "the face switch leases the shared camera source")
