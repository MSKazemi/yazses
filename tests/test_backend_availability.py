"""Backends must report *why* they are unavailable without misdirecting the user.

Three configurable backends have no adapter module in this build — ``deepfilternet``,
``resemblyzer`` and ``pyannote``. Each factory used to answer "install the `X` extra",
which cannot work: there is no ``denoise`` extra at all, and the ``voiceprint`` /
``diarization`` extras ship speechbrain / sherpa-onnx respectively, never the other
two. These tests pin the honest message and the once-per-backend denoise warning.
"""
from __future__ import annotations

import logging
from dataclasses import replace

import numpy as np

from yazses.config import DenoiseConfig
from yazses.denoise import frontend
from yazses.denoise.frontend import apply_denoise
from yazses.system.backends import BackendStatus, probe_backend


def _absent(*names: str):
    """A `missing_modules` stand-in reporting exactly *names* as unimportable."""
    absent = set(names)
    return lambda mods: [m for m in mods if m in absent]


# --- probe_backend -------------------------------------------------------------

def test_missing_adapter_reports_not_implemented_and_offers_no_remedy():
    status = probe_backend(
        "deepfilternet",
        adapter="yazses.denoise.deepfilter",
        requires=("df",),
        extra="denoise",
        missing=_absent("yazses.denoise.deepfilter", "df"),
    )
    assert not status.available
    assert not status.implemented
    assert "not implemented in this build" in status.reason
    assert status.remedy == ""                       # nothing to install — don't lie
    assert "extra" not in status.message


def test_missing_dependency_names_the_extra_that_actually_provides_it():
    status = probe_backend(
        "ecapa",
        adapter="yazses.voiceprint.ecapa",
        requires=("speechbrain",),
        extra="voiceprint",
        missing=_absent("speechbrain"),
    )
    assert not status.available
    assert status.implemented                        # adapter ships; deps don't
    assert "needs speechbrain" in status.reason
    assert status.remedy == "install the `voiceprint` extra"
    assert status.missing == ("speechbrain",)


def test_missing_dependency_without_an_extra_lists_the_packages():
    status = probe_backend(
        "x", adapter="pkg.x", requires=("libx",), extra=None, missing=_absent("libx")
    )
    assert status.remedy == "install: libx"


def test_available_when_adapter_and_dependencies_are_present():
    status = probe_backend(
        "sherpa",
        adapter="yazses.recimport.diarizer",
        requires=("sherpa_onnx",),
        extra="diarization",
        missing=_absent(),                            # nothing missing
    )
    assert status.available and status.implemented
    assert status.message == "backend 'sherpa' is available"


def test_a_missing_adapter_outranks_missing_dependencies():
    """No install can fix an unshipped adapter, so deps must not be blamed."""
    status = probe_backend(
        "pyannote",
        adapter="yazses.recimport.pyannote_backend",
        requires=("pyannote.audio",),
        extra="diarization",
        missing=_absent("yazses.recimport.pyannote_backend", "pyannote.audio"),
    )
    assert status.missing == ("yazses.recimport.pyannote_backend",)
    assert "diarization" not in status.message


def test_status_message_joins_reason_and_remedy():
    s = BackendStatus("b", False, reason="r", remedy="do it")
    assert s.message == "r; do it"


# --- denoise front-end ---------------------------------------------------------

def _audio() -> np.ndarray:
    return np.ones(16, dtype=np.float32)


def test_denoise_off_is_a_silent_identity_passthrough(caplog):
    frontend._warned.clear()
    audio = _audio()
    with caplog.at_level(logging.WARNING):
        assert apply_denoise(audio, DenoiseConfig()) is audio
    assert caplog.records == []                       # dormant must stay quiet


def test_enabling_denoise_without_a_backend_warns_instead_of_degrading_silently(caplog):
    """The bug: enabling denoise returned raw audio with no indication at all."""
    frontend._warned.clear()
    cfg = replace(DenoiseConfig(), enabled=True, backend="deepfilternet")
    audio = _audio()

    with caplog.at_level(logging.WARNING):
        assert apply_denoise(audio, cfg) is audio     # still never breaks dictation

    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert "not implemented in this build" in msg
    assert "passed through unprocessed" in msg
    assert "extra" not in msg                         # no impossible remedy


def test_the_denoise_warning_fires_once_not_once_per_burst(caplog):
    """apply_denoise runs on every hold — the warning must not spam the log."""
    frontend._warned.clear()
    cfg = replace(DenoiseConfig(), enabled=True, backend="deepfilternet")
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            apply_denoise(_audio(), cfg)
    assert len(caplog.records) == 1


def test_denoise_backend_none_is_a_passthrough_without_warning(caplog):
    frontend._warned.clear()
    cfg = replace(DenoiseConfig(), enabled=True, backend="none")
    with caplog.at_level(logging.WARNING):
        apply_denoise(_audio(), cfg)
    assert caplog.records == []


# --- factories -----------------------------------------------------------------

def test_voiceprint_resemblyzer_advises_its_own_extra_not_the_neighbouring_one(caplog):
    """The adapter ships now (#70), so the honest answer changed from "never" to "not yet".

    What must not change is the extra it names: `voiceprint` is speechbrain/ECAPA
    and cannot supply Resemblyzer, so advising it would still send the user after
    a package that cannot help. The backend degrades to dormant either way.
    """
    from yazses.config import VoiceprintConfig
    from yazses.voiceprint.factory import build_embedder

    cfg = replace(VoiceprintConfig(), enabled=True, backend="resemblyzer")
    with caplog.at_level(logging.WARNING):
        assert build_embedder(cfg) is None            # still degrades to dormant
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "not implemented in this build" not in msg
    assert "`voiceprint-resemblyzer` extra" in msg
    assert "`voiceprint` extra" not in msg


def test_diarization_pyannote_advises_its_own_extra_not_the_neighbouring_one(caplog):
    """As above for #71: `diarization` is sherpa-onnx and cannot supply pyannote."""
    from yazses.config import RecimportConfig
    from yazses.recimport.factory import build_diarizer

    cfg = replace(RecimportConfig(), diarize=True, backend="pyannote")
    with caplog.at_level(logging.WARNING):
        assert build_diarizer(cfg) is None
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "not implemented in this build" not in msg
    assert "`diarization-pyannote` extra" in msg
    assert "`diarization` extra" not in msg
    # The sherpa-only model download would be a second wrong instruction.
    assert "--download-models" not in msg


def test_deepfilternet_still_reports_the_one_backend_that_cannot_be_shipped(caplog):
    """#69 is not "not yet" — it is "not ever", and the message must not soften.

    Every DeepFilterNet release caps numpy<2.0 while this project requires
    numpy>=2.4.6, so no extra can be offered without lying. If someone later adds
    a `denoise` extra, this fails and they have to justify it.
    """
    frontend._warned.clear()
    cfg = replace(DenoiseConfig(), enabled=True, backend="deepfilternet")
    with caplog.at_level(logging.WARNING):
        apply_denoise(_audio(), cfg)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "not implemented in this build" in msg
    assert "extra" not in msg, "there is no installable denoise extra to advise"
