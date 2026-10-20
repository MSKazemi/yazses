"""Persist the gaze→screen calibration map (ADR-011: a coarse geometric map only).

The fitted :class:`~yazses.gaze.calibrate.CalibrationMap` is a 2x3 affine matrix —
no biometric data, no frames. It is written as plain JSON to ``data_dir`` so the
daemon can load it at startup without re-calibrating each session.

Since ADR-v2-149 the file also carries the **calibration context**: which monitors
were attached, where, at what size and scale, and which camera produced the samples
(:mod:`yazses.gaze.topology`). Those coefficients are meaningless against a different
desktop, and without the context nothing can tell a good map from one calibrated on
a laptop that has since been docked to two 4K panels.

**A file written before that field existed still loads.** It simply has no context,
which reads as *unverified* rather than *stale* — see
:func:`yazses.gaze.topology.check_context`. Discarding a working calibration because
this schema grew a field would be the worst of the available answers.

## Provenance, promotion and rollback (#398)

The file also says **where the map came from**: ``source`` is ``"explicit"`` for the
wizard and ``"implicit"`` for a refinement from clicks that won the held-out comparison
(``gaze/refine.py``). Every write here is **atomic** — a temporary file in the same
directory, flushed, then ``os.replace`` — so a crash or an I/O error can leave the old
file or the new one, never half of one. The tests inject exactly that failure and compare
bytes.

Promoting a refinement keeps the artifact it replaced, byte for byte, as
``gaze_calibration.previous.json`` *before* touching the live file. That one backup is
what makes :func:`rollback_calibration` an exact restore rather than an approximation,
and it is deleted whenever the wizard runs again: a backup of a map from before a new
explicit calibration describes a setup the user has just replaced.

A file written before ``source`` existed is read as ``"explicit"`` — that is what every
such file was.

## A damaged file never reads as a valid one (#415)

Three layers, each refusing rather than guessing:

* **The map.** ``A`` must be exactly two rows of three finite JSON numbers. ``NaN`` and
  ``Infinity`` are legal to Python's ``json`` module and would route every gaze sample to
  a NaN coordinate; strings and booleans would be silently coerced by numpy. Any of them
  makes the whole file unreadable, so there is no map to route with.
* **The binding.** Every writer since ADR-v2-149 stores ``context_fingerprint`` beside the
  context. On load the *stored* context is hashed exactly as it was at save time and must
  match; a mismatch, a fingerprint whose context is gone, or a context the strict
  constructors refuse all mark the binding damaged -- UNVERIFIED with that reason, never
  VALID. (Hashing the stored dict rather than a rebuilt one is what keeps a file from an
  older schema verifiable: its fingerprint covered its own fields, not today's.)
* **The space.** A file whose top-level ``space`` names a different coordinate space holds
  coefficients that mean something else, and is STALE.

A file that exists but cannot be read at all yields no map and a STALE verdict that says
so, rather than the "never calibrated" a missing file gets. Nothing here raises: a
corrupt file costs a recalibration, never the daemon.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.topology import (
    CANONICAL_SPACE,
    CalibrationContext,
    ContextCheck,
    Validity,
    check_context,
    digest,
)

FILENAME = "gaze_calibration.json"

#: The file the previous calibration is kept in while a refinement is live.
PREVIOUS_FILENAME = "gaze_calibration.previous.json"

#: Bumped from 1 when the context field was added, and from 2 when source/saved_at/
#: refinement were. Older versions still load.
SCHEMA_VERSION = 3

#: Where a calibration came from.
SOURCE_EXPLICIT = "explicit"
SOURCE_IMPLICIT = "implicit"


class CalibrationWriteError(RuntimeError):
    """A calibration could not be promoted or restored; the live file is unchanged."""


@dataclass(frozen=True)
class RefinementInfo:
    """The evidence a promoted refinement was approved on — derived numbers only."""

    train_samples: int
    holdout_samples: int
    baseline_error_px: float
    candidate_error_px: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "train_samples": self.train_samples,
            "holdout_samples": self.holdout_samples,
            "baseline_error_px": self.baseline_error_px,
            "candidate_error_px": self.candidate_error_px,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> RefinementInfo:
        if not isinstance(raw, dict):
            raise ValueError("refinement info is not an object")
        return cls(
            train_samples=int(raw["train_samples"]),
            holdout_samples=int(raw["holdout_samples"]),
            baseline_error_px=float(raw["baseline_error_px"]),
            candidate_error_px=float(raw["candidate_error_px"]),
        )


@dataclass(frozen=True)
class CalibrationRecord:
    """A stored calibration and the setup it was made on (``None`` = legacy file)."""

    calibration: CalibrationMap
    context: CalibrationContext | None = None
    #: ``"explicit"`` (the wizard) or ``"implicit"`` (a promoted refinement).
    source: str = SOURCE_EXPLICIT
    #: UTC ISO-8601 time of the write; ``""`` for a file that predates the field.
    saved_at: str = ""
    #: The evidence the map was promoted on; ``None`` for an explicit calibration.
    refinement: RefinementInfo | None = None
    #: True when the file *has* a ``context`` entry that could not be read. Distinct from
    #: ``context is None`` on a legacy file, which never had one: telling the user "saved
    #: before YazSes recorded which screens it was made on" about a file that did record
    #: them would be false, and would hide that something damaged the binding.
    context_unreadable: bool = False
    #: The coordinate space the file says ``A`` maps into. Files that predate the field
    #: (schema 1) read as the canonical one -- it is the only space there has ever been.
    space: str = CANONICAL_SPACE


def calibration_path(data_dir: Path) -> Path:
    """Return the calibration file path under *data_dir*."""
    return Path(data_dir) / FILENAME


def previous_calibration_path(data_dir: Path) -> Path:
    """Return the path of the one-level rollback copy under *data_dir*."""
    return Path(data_dir) / PREVIOUS_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write *data* to *path* so that *path* is always either the old file or the new one.

    The temporary file lives in the same directory (``os.replace`` is only atomic within a
    filesystem), is flushed and fsynced before the rename, and is removed on any failure so
    a failed write leaves no litter beside the calibration.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    # Persist the rename itself where the OS lets a directory be opened (not Windows).
    with contextlib.suppress(OSError):
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _payload(
    cal: CalibrationMap,
    context: CalibrationContext | None,
    source: str,
    saved_at: str,
    refinement: RefinementInfo | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "space": CANONICAL_SPACE,
        "source": source,
        "saved_at": saved_at,
        "A": cal.A.tolist(),
    }
    if context is not None:
        payload["context"] = context.as_dict()
        payload["context_fingerprint"] = context.fingerprint()
    if refinement is not None:
        payload["refinement"] = refinement.as_dict()
    return payload


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2).encode("utf-8")


def save_calibration(
    cal: CalibrationMap,
    data_dir: Path,
    context: CalibrationContext | None = None,
) -> Path:
    """Write an **explicit** calibration to ``data_dir/gaze_calibration.json``; return the path.

    *context* records the desktop/camera the map was fitted against; omitting it
    writes a map nothing can later validate, so callers that can describe the
    machine should.

    A fresh wizard run supersedes any refinement, so the rollback copy of the map it
    replaces is removed first — restoring it later would put back a calibration made on a
    setup the user has just recalibrated. (Removed *before* the write: a crash in between
    costs the rollback, never a stale map restored over a new calibration.)
    """
    path = calibration_path(data_dir)
    with contextlib.suppress(OSError):
        previous_calibration_path(data_dir).unlink(missing_ok=True)
    _atomic_write_bytes(path, _encode(_payload(cal, context, SOURCE_EXPLICIT, _now(), None)))
    return path


def promote_refinement(
    data_dir: Path,
    candidate: CalibrationMap,
    info: RefinementInfo,
    *,
    expected_baseline: CalibrationMap | None = None,
) -> CalibrationRecord:
    """Make *candidate* the stored calibration, keeping the one it replaces for rollback.

    Order is the safety property: the current artifact is first copied **byte for byte** to
    the rollback file, and only then replaced. If either step fails the live file is
    untouched (and an unreadable or missing baseline refuses the promotion outright —
    there is nothing to refine). The display/camera context is carried over unchanged:
    a refinement is valid only for the context it was collected under, never a new one.

    *expected_baseline* is the map the candidate was **measured against** (the running
    process's live one). When given, the stored map must be that map: the file can change
    under a running daemon -- `yazses gaze rollback`, a recalibration -- and a candidate
    that beat the in-memory map says nothing about the one now on disk. Promoting it would
    silently undo the rollback the user just asked for, and keep as "previous" a file the
    refinement never touched. Compared by value (the JSON round-trip of a float64 is
    exact), never by "a file exists".

    Raises :class:`CalibrationWriteError`.
    """
    path = calibration_path(data_dir)
    try:
        current_bytes = path.read_bytes()
    except OSError as exc:
        raise CalibrationWriteError(f"no stored calibration to refine ({type(exc).__name__})") from exc
    record = _parse(current_bytes)
    if record is None:
        raise CalibrationWriteError("the stored calibration is unreadable; refusing to replace it")
    if expected_baseline is not None and not np.allclose(
        record.calibration.A, expected_baseline.A, rtol=1e-9, atol=1e-9
    ):
        raise CalibrationWriteError(
            "the stored calibration is no longer the map this refinement was measured "
            "against (it was rolled back or recalibrated while the daemon ran); not "
            "replacing it. Restart the daemon to pick up the stored calibration"
        )
    try:
        _atomic_write_bytes(previous_calibration_path(data_dir), current_bytes)
        _atomic_write_bytes(
            path,
            _encode(_payload(candidate, record.context, SOURCE_IMPLICIT, _now(), info)),
        )
    except OSError as exc:
        raise CalibrationWriteError(f"could not write the refined calibration ({type(exc).__name__})") from exc
    refreshed = load_calibration_record(data_dir)
    if refreshed is None:  # pragma: no cover - we just wrote it
        raise CalibrationWriteError("the refined calibration was written but cannot be read back")
    return refreshed


def rollback_available(data_dir: Path) -> bool:
    """Whether a readable rollback copy exists."""
    try:
        return _parse(previous_calibration_path(data_dir).read_bytes()) is not None
    except OSError:
        return False


def rollback_calibration(data_dir: Path) -> CalibrationRecord | None:
    """Restore the calibration a promotion replaced, exactly; ``None`` if there is none.

    The rollback copy is written back **byte for byte** (atomically) and then removed, so
    the restored file is the one that existed before the refinement — not a re-encoding of
    it. A rollback copy that cannot be read is refused and left alone, and the live file is
    not touched: replacing a working calibration with an unreadable one is the one outcome
    worse than not rolling back.

    Raises :class:`CalibrationWriteError`.
    """
    previous = previous_calibration_path(data_dir)
    try:
        data = previous.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CalibrationWriteError(f"the rollback copy cannot be read ({type(exc).__name__})") from exc
    if _parse(data) is None:
        raise CalibrationWriteError("the rollback copy is unreadable; the live calibration was left alone")
    try:
        _atomic_write_bytes(calibration_path(data_dir), data)
    except OSError as exc:
        raise CalibrationWriteError(f"could not restore the previous calibration ({type(exc).__name__})") from exc
    with contextlib.suppress(OSError):
        previous.unlink()
    return load_calibration_record(data_dir)


def load_calibration(data_dir: Path) -> CalibrationMap | None:
    """Load the calibration map from *data_dir*, or ``None`` if absent/unreadable."""
    record = load_calibration_record(data_dir)
    return None if record is None else record.calibration


def load_calibration_record(data_dir: Path) -> CalibrationRecord | None:
    """Load the map *and* its stored context, or ``None`` if absent/unreadable.

    A malformed or absent context is not fatal: the map still loads with
    ``context=None``. Losing the ability to *verify* a calibration is a smaller
    harm than throwing away the calibration, and the verdict the caller gets for a
    missing context already says the binding is unchecked.
    """
    try:
        data = calibration_path(data_dir).read_bytes()
    except OSError:
        return None
    return _parse(data)


def _matrix(raw: Any) -> np.ndarray | None:
    """``A`` as a 2x3 float64 matrix, or None unless it is exactly 2 rows of 3 finite numbers.

    Checked element by element *before* numpy sees it: ``np.array(..., dtype="float64")``
    converts ``"1e999"`` to infinity and ``true`` to 1.0 without complaint, and ``json``
    itself accepts the bare tokens ``NaN`` and ``Infinity``.
    """
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    for row in raw:
        if not isinstance(row, list) or len(row) != 3:
            return None
        for value in row:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            if not math.isfinite(value):
                return None
    return np.array(raw, dtype="float64")


#: The exceptions a hostile-shaped but bounded file can raise while being decoded or
#: rebuilt. RecursionError: ``[[[[...]]]]`` nested past the interpreter's limit.
#: OverflowError: ``int(float("inf"))`` and kin. Anything else is a bug and should surface.
_DECODE_ERRORS = (ValueError, KeyError, TypeError, RecursionError, OverflowError)


def _parse(data: bytes) -> CalibrationRecord | None:
    try:
        raw = json.loads(data.decode("utf-8"))
    except _DECODE_ERRORS:
        # UnicodeDecodeError and json.JSONDecodeError are ValueErrors.
        return None
    if not isinstance(raw, dict):
        # Valid JSON of the wrong shape (a string, a list) is unreadable too.
        return None
    A = _matrix(raw.get("A"))
    if A is None:
        return None
    context = None
    context_unreadable = False
    stored = raw.get("context")
    recorded = raw.get("context_fingerprint")
    if stored is not None:
        try:
            context = CalibrationContext.from_dict(stored)
            # Hash what is on disk, not a rebuild of it: a file from an older context
            # schema was fingerprinted over *its* fields, and today's as_dict() would add
            # defaults it never had. Absent (only hand-written files lack it): nothing to
            # compare, the strict rebuild above is the whole check.
            if recorded is not None and recorded != digest(stored):
                raise ValueError("the stored context does not match its recorded fingerprint")
        except _DECODE_ERRORS:
            context = None
            context_unreadable = True
    elif recorded is not None:
        # A fingerprint with no context beside it: the binding was written and is gone.
        context_unreadable = True
    space = raw.get("space", CANONICAL_SPACE)
    source = raw.get("source")
    saved_at = raw.get("saved_at")
    refinement = None
    if raw.get("refinement") is not None:
        try:
            refinement = RefinementInfo.from_dict(raw["refinement"])
        except _DECODE_ERRORS:
            refinement = None
    return CalibrationRecord(
        calibration=CalibrationMap(A=A),
        context=context,
        # Anything but the one other known value is "explicit": a file from before the
        # field existed, or one this build does not understand, was never a refinement.
        source=SOURCE_IMPLICIT if source == SOURCE_IMPLICIT else SOURCE_EXPLICIT,
        saved_at=saved_at if isinstance(saved_at, str) else "",
        refinement=refinement,
        context_unreadable=context_unreadable,
        # A non-string space is not a space anyone wrote; record it as unknown so the
        # comparison below refuses it rather than it reading as the canonical one.
        space=space if isinstance(space, str) else "?",
    )


def calibration_state(
    data_dir: Path, current: CalibrationContext | None
) -> tuple[CalibrationMap | None, ContextCheck]:
    """Load the calibration and judge it against *current*.

    One call for every caller that needs both halves — the daemon deciding whether
    to build a targeter and ``yazses gaze status`` printing why it did not. Returns
    ``(None, verdict)`` when there is no calibration at all; the verdict is still
    meaningful (it reports what could be checked). When the file *exists* but cannot be
    read, the verdict is STALE and says the file is damaged, so no caller can tell the user
    they never calibrated.
    """
    record = load_calibration_record(data_dir)
    if record is None:
        path = calibration_path(data_dir)
        if path.exists():
            # Present but unreadable is not "never calibrated": the user did calibrate, and
            # being sent to a wizard with no reason reads as YazSes forgetting it. No map is
            # returned, so nothing routes with it either way.
            return None, ContextCheck(
                Validity.STALE,
                f"the stored calibration ({path.name}) is damaged or unreadable and is not "
                "used; run `yazses gaze calibrate` to replace it",
            )
        return None, check_context(None, current)
    if record.space != CANONICAL_SPACE:
        return record.calibration, ContextCheck(
            Validity.STALE,
            f"the calibration maps into the {record.space!r} coordinate space, not "
            f"{CANONICAL_SPACE!r}; its coefficients mean something else here",
            (f"the coordinate space changed {record.space} -> {CANONICAL_SPACE}",),
        )
    check = check_context(record.context, current)
    if record.context_unreadable:
        # Still UNVERIFIED (losing the binding is a smaller harm than losing the map), but
        # the reason must be the true one: the binding existed and is damaged.
        check = ContextCheck(
            Validity.UNVERIFIED,
            "the screen layout recorded with this calibration is damaged or unreadable, so "
            "it cannot be checked against this desktop; recalibrate to bind it",
        )
    return record.calibration, check
