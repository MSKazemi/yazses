"""Diarizer factory (dormancy + graceful degradation) — ADR-v2-125.

``build_diarizer`` returns ``None`` when diarization is not requested, the backend is
``none``, or the optional ``diarization`` extra (sherpa-onnx) / its model files are
absent — callers then produce a plain, unattributed transcript instead of crashing.
Mirrors ``yazses.voiceprint.factory.build_embedder`` (ADR-011: nothing loads or
downloads unless explicitly enabled).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def diarization_status(config) -> dict:
    """Report diarization readiness *without* importing the heavy backend.

    Returns ``{requested, backend, extra_installed, models_present, ready}`` so callers
    (meeting start/status, doctor) can warn about a silent un-attributed transcript
    before it happens, instead of quietly degrading. Pure: only checks whether the
    backend's module is importable and whether its models are on disk.

    **Per backend, because the two answer these questions differently.** This used
    to hard-code ``backend == "sherpa"`` and probe ``sherpa_onnx`` whatever was
    configured, so once pyannote became a real backend a correctly-installed
    pyannote user would have been told, on every ``meeting start``, that their
    transcript would not be attributed — the precise false alarm this function
    exists to avoid.

    Note the honest limit for pyannote: its pipeline is a *gated* download, so a
    cached model means the download succeeded once, and no cache means the first
    run will fetch it — which may still fail if the repo's conditions were never
    accepted. That is only knowable by trying, so a missing cache is reported as
    "models not present" (a true statement, and the actionable one) rather than
    predicting success.
    """
    from yazses.system.deps import missing_modules

    requested = bool(getattr(config, "diarize", False))
    backend = getattr(config, "backend", "sherpa")

    if backend == "pyannote":
        # `pyannote.audio` is dotted: find_spec raises when the parent package is
        # absent, so this must go through missing_modules (see deps.py).
        extra = not missing_modules(["pyannote.audio"])
        models = _pyannote_model_cached()
    elif backend == "sherpa":
        from yazses.recimport.diarizer import models_present

        extra = not missing_modules(["sherpa_onnx"])
        models = models_present(config)
    else:  # "none", or an unrecognised name — nothing to be ready with
        extra = models = False

    ready = bool(requested and backend in ("sherpa", "pyannote") and extra and models)
    return {
        "requested": requested, "backend": backend,
        "extra_installed": extra, "models_present": models, "ready": ready,
    }


def diarization_advice(status: dict) -> str | None:
    """Why speaker labels are unavailable, and **the one command that fixes it**.

    Returns None when nothing is wrong — labels are ready, or were never requested.

    This exists because `diarization_status` already distinguishes *"the Python
    package is missing"* from *"the model files are missing"*, and both callers threw
    that distinction away at the point of giving advice:

    * `yazses meeting status` printed the cause correctly and then recommended
      ``yazses transcribe --download-models`` **for both**. With the extra missing
      that downloads ~45 MB and changes nothing, because the thing that is absent is
      an importable module — so the user pays for a download and gets the identical
      message back.
    * the daemon's `meeting start` warning named both remedies unconditionally, which
      is better but still asks someone to do a step they cannot yet act on.

    So the rule is **name the next action, not the whole path**. When the extra is
    missing, the models are irrelevant until it is installed; `features enable meeting`
    is the one command, and it fetches nothing the user has to think about. Mentioning
    a second step they cannot take yet is how the wrong one gets attempted first.

    Deliberately one string returned to one caller rather than a dict of parts: two
    surfaces phrasing the same fault differently is exactly what this replaces.
    """
    if not status.get("requested") or status.get("ready"):
        return None

    backend = status.get("backend", "sherpa")
    if backend not in ("sherpa", "pyannote"):
        # `[meeting] diarize` is on but `backend` names nothing that can diarize.
        # No install fixes that; the config does.
        return (
            f"Speaker labels are on but the backend is {backend!r}, which cannot "
            "produce them. Set `[meeting] backend` to \"sherpa\" (or \"pyannote\")."
        )

    if not status.get("extra_installed"):
        return (
            "Speaker labels are on but the diarization extra is not installed, so "
            "transcripts will not be attributed. Install it with "
            "`yazses features enable meeting` — the speaker models are fetched after."
        )

    if backend == "pyannote":
        # Its pipeline is a *gated* download, so "not cached" may mean the terms were
        # never accepted rather than that a fetch was never attempted. Saying "run
        # this" would be a prediction; naming both possibilities is the true statement.
        return (
            "Speaker labels are on but the pyannote pipeline is not in your Hugging "
            "Face cache, so transcripts will not be attributed. It downloads on first "
            "use if you have accepted the model's conditions on huggingface.co."
        )

    return (
        "Speaker labels are on but the speaker models are not downloaded, so "
        "transcripts will not be attributed. Fetch them with "
        "`yazses transcribe --download-models`."
    )


def speaker_count_advice(config, remedy: str) -> str | None:
    """Tell the user the one setting that is worth more than every other, or None.

    Separate from `diarization_advice`, which answers *"why are there no speaker
    labels at all"*. This answers a different question: labels will be produced, and
    on real audio they will be poor, and there is a single flag that fixes most of it.

    **The reason changed when the threshold did, and the wording had to change with it.**
    This advice was written against `cluster_threshold = 0.5`, where auto-count scored
    84.09% DER on AMI and giving the count scored 28.55% — a gap so large that "set this
    one flag" was simply correct. ADR-v2-133 raised the defaults, and on the full AMI test
    split (16 recordings, 543.7 min) the ordering **reverses**: auto-count at `1.2` scores
    **26.71%** and `max_speakers = 4` scores **29.42%**. Telling every user to pin the
    count would now make the average result slightly worse, so this no longer claims to be
    the largest improvement available.

    What survives the change is that the estimate is still *wrong*, in both directions and
    without saying so: exact on 2 of 16 AMI meetings (+2.06 on average), and on VoxConverse
    at the `[recimport]` default it under-counts a crowded broadcast recording. A user who
    knows the number can still remove that whole error term, and — because `max_speakers`
    is an exact count on this backend rather than a cap — nobody who does not know it
    should guess. That is what the hint says now.

    Only sherpa is advised about: the pyannote adapter reads the value as a genuine upper
    bound, where leaving it unset is a reasonable default rather than a trap.

    `remedy` is supplied by the caller because `yazses transcribe` and Meeting Mode
    set the count differently, and naming a step the user cannot take from where they
    are is the failure `diarization_advice` was written to end. The *fact* stays in
    one place, which is the half that must not drift.
    """
    if not getattr(config, "diarize", False):
        return None
    backend = (getattr(config, "backend", "sherpa") or "sherpa").strip().lower()
    if backend != "sherpa":
        return None
    if int(getattr(config, "max_speakers", 0) or 0) > 0:
        return None
    return (
        "Speaker count is set to auto, so the clustering will estimate it — measured on "
        "the AMI test split it gets it exactly right in 2 meetings out of 16. If you know "
        "how many people are on this recording, saying so removes that error. Only say so "
        "if you know: this is an exact count, not a maximum. "
        + remedy
    )


def _pyannote_model_cached() -> bool:
    """True when the gated pyannote pipeline is already in the Hugging Face cache.

    A path check, not an import: this runs on the ``meeting status`` path and must
    not pull torch in. Honours ``HF_HOME``/``HF_HUB_CACHE`` so a user who moved
    their cache is not told the model is missing.
    """
    import os
    from pathlib import Path

    from yazses.recimport.pyannote_backend import PIPELINE_ID

    if hub := os.environ.get("HF_HUB_CACHE"):
        root = Path(hub)
    elif home := os.environ.get("HF_HOME"):
        root = Path(home) / "hub"
    else:
        root = Path.home() / ".cache" / "huggingface" / "hub"
    return (root / f"models--{PIPELINE_ID.replace('/', '--')}").is_dir()


def build_diarizer(config):
    """Return a diarizer for *config*, or ``None`` when dormant/unavailable."""
    if not getattr(config, "diarize", False):
        return None

    backend = getattr(config, "backend", "sherpa")
    if backend == "none":
        return None
    try:
        if backend == "sherpa":
            from yazses.recimport.diarizer import SherpaDiarizer

            return SherpaDiarizer(config)
        if backend == "pyannote":
            from yazses.recimport.pyannote_backend import PyannoteDiarizer

            return PyannoteDiarizer(config)
        log.warning("Unknown diarization backend %r; diarization disabled.", backend)
        return None
    except Exception as exc:
        log.warning(
            "Diarization backend %r unavailable: %s. Producing a plain transcript.",
            backend, _unavailable_detail(backend, exc),
        )
        return None


def _unavailable_detail(backend: str, exc: Exception) -> str:
    """Explain *why* a diarization backend failed, without misdirecting the user.

    The backends ship behind *different* extras — ``diarization`` is sherpa-onnx,
    ``diarization-pyannote`` is pyannote.audio — so a blanket "install the
    `diarization` extra" would send a pyannote user after a package that cannot
    supply what they selected. Route the message through the shared probe so each
    case names its own extra.

    Only sherpa gets the ``--download-models`` hint: pyannote fetches its
    pretrained pipeline itself on first construction, so telling a pyannote user
    to run a sherpa model download would be a second wrong instruction.
    """
    try:
        from yazses.system.backends import probe_backend

        adapters = {
            "sherpa": ("yazses.recimport.diarizer", ("sherpa_onnx",), "diarization"),
            "pyannote": (
                "yazses.recimport.pyannote_backend",
                ("pyannote.audio",),
                "diarization-pyannote",
            ),
        }
        if backend in adapters:
            adapter, requires, extra = adapters[backend]
            status = probe_backend(
                backend, adapter=adapter, requires=requires, extra=extra
            )
            if status.available:
                # The adapter imported and its dependencies are installed, so the
                # probe has nothing to report — pasting its "is available" onto an
                # "unavailable:" prefix produced a message that contradicted
                # itself. Whatever went wrong is downstream of the import, and for
                # sherpa that is almost always the ~45 MB of model files not being
                # on disk yet.
                if backend == "sherpa":
                    return (
                        "its models are not downloaded — run "
                        f"`yazses transcribe --download-models` ({exc})"
                    )
                return str(exc)
            if backend == "sherpa" and status.implemented:
                return (
                    f"{status.message} and run `yazses transcribe --download-models`"
                )
            return status.message
    except Exception:  # pragma: no cover - diagnostics must never mask the real error
        pass
    return str(exc)
