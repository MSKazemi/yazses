"""Where does dictated text go in XR? A bounded registry of panels plus a sticky pin (pure).

The companion app reports the panels it can see; this module remembers them, forgets the
ones that stopped being reported, and holds the one target the user chose explicitly.

* The registry is **bounded** (``max_panels``): the companion is untrusted input, so a
  flood of distinct ids evicts the least-recently-seen panel rather than growing memory.
* A panel that left the scene must stop receiving text: anything not refreshed for
  ``stale_after_s`` is dropped by :meth:`PanelRegistry.expire`. The window is half-open —
  a panel last seen exactly ``stale_after_s`` ago is already stale, so doubt resolves to
  "do not type there".
* :class:`DictationTarget` is an explicit, user-chosen pin that wins over gaze and
  auto-expires. It never returns an id whose panel is gone, and it also drops the pin if
  the panel under that id has been re-posed materially since it was pinned (see below).
* **Panel ids are canonicalised.** The companion is untrusted, so an id is NFC-normalised
  and stripped, then must match ``^[A-Za-z0-9._:-]{1,128}$``; anything else is a
  ``ValueError`` on ``upsert`` (homoglyphs, NFC/NFD twins, blank or padded ids are not
  silently kept as separate entries). ``get``/``remove``/``is_fresh``/``pin`` apply the
  same normalisation, so an id that is invalid simply finds nothing. The stored panel
  carries the canonical id.
* ``last_seen`` is monotonic: an out-of-order, older ``now_s`` never rewinds it.

Time is injected (``now_s``, desktop-clock seconds); nothing here reads a clock.
"""
from __future__ import annotations

import dataclasses
import math
import re
import unicodedata
from collections.abc import Sequence

from yazses.xr.types import Panel

# A spoken label is read aloud, so it stays short; longer labels end in an ellipsis.
_MAX_SPOKEN_LABEL = 40


_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def _canonical_id(panel_id: object) -> str | None:
    """NFC-normalise and strip an id; None if it is not a valid canonical id."""
    if not isinstance(panel_id, str):
        return None
    nid = unicodedata.normalize("NFC", panel_id).strip()
    return nid if _ID_RE.fullmatch(nid) else None


def _check_time(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


class PanelRegistry:
    """Panels keyed by ``panel_id`` with last-seen times; bounded and self-expiring."""

    def __init__(self, max_panels: int = 64, stale_after_s: float = 30.0) -> None:
        if isinstance(max_panels, bool) or not isinstance(max_panels, int) or max_panels < 1:
            raise ValueError("max_panels must be an integer >= 1")
        _check_time("stale_after_s", stale_after_s)
        if stale_after_s <= 0:
            raise ValueError("stale_after_s must be > 0")
        self._max = max_panels
        self._stale_after_s = float(stale_after_s)
        self._items: dict[str, tuple[Panel, float]] = {}

    def __len__(self) -> int:
        return len(self._items)

    def upsert(self, panel: Panel, now_s: float) -> None:
        """Insert or refresh ``panel``; at capacity the least-recently-seen one is evicted."""
        _check_time("now_s", now_s)
        nid = _canonical_id(panel.panel_id)
        if nid is None:
            raise ValueError(
                f"panel_id {panel.panel_id!r} is not valid: after NFC normalisation and "
                "stripping it must match [A-Za-z0-9._:-]{1,128}")
        if nid != panel.panel_id:
            panel = dataclasses.replace(panel, panel_id=nid)
        old = self._items.get(nid)
        if old is None and len(self._items) >= self._max:
            # Oldest last-seen goes; the id breaks ties so the choice is deterministic.
            oldest = min(self._items, key=lambda pid: (self._items[pid][1], pid))
            del self._items[oldest]
        # Monotonic: an older now_s (reordered or replayed report) must not make a
        # panel look staler than it already was.
        seen = float(now_s) if old is None else max(old[1], float(now_s))
        self._items[nid] = (panel, seen)

    def remove(self, panel_id: str) -> bool:
        """Forget a panel; True if it was present."""
        nid = _canonical_id(panel_id)
        return nid is not None and self._items.pop(nid, None) is not None

    def is_fresh(self, panel_id: str, now_s: float) -> bool:
        """True if the panel is held and was seen less than ``stale_after_s`` ago."""
        _check_time("now_s", now_s)
        nid = _canonical_id(panel_id)
        item = None if nid is None else self._items.get(nid)
        return item is not None and now_s - item[1] < self._stale_after_s

    def expire(self, now_s: float) -> list[str]:
        """Drop panels not refreshed within ``stale_after_s``; return their ids, sorted.

        A clock that steps backwards (``now_s`` earlier than a last-seen) leaves the
        panel alone rather than expiring it on a negative age.
        """
        _check_time("now_s", now_s)
        gone = sorted(pid for pid, (_, seen) in self._items.items()
                      if now_s - seen >= self._stale_after_s)
        for pid in gone:
            del self._items[pid]
        return gone

    def panels(self) -> tuple[Panel, ...]:
        """Held panels in stable ``panel_id`` order."""
        return tuple(self._items[pid][0] for pid in sorted(self._items))

    def get(self, panel_id: str) -> Panel | None:
        nid = _canonical_id(panel_id)
        item = None if nid is None else self._items.get(nid)
        return item[0] if item is not None else None


# What a pin remembers about the panel it was made on: centre (x, y, z), normal (x, y, z),
# width, height. Centre and sizes are rounded to 1 mm so sensor jitter does not matter.
_Fingerprint = tuple[float, float, float, float, float, float, float, float]

# A pinned panel whose width or height changes by more than this fraction is another surface.
_PIN_SIZE_TOLERANCE = 0.20


def _fingerprint(panel: Panel) -> _Fingerprint:
    c, n = panel.center, panel.normal
    return (round(c.x, 3), round(c.y, 3), round(c.z, 3), n.x, n.y, n.z,
            round(panel.width, 3), round(panel.height, 3))


class DictationTarget:
    """One explicit, sticky dictation target chosen by the user over a registry's panels.

    The pin is an id **plus the geometry the id had when it was pinned**. The companion is
    untrusted and could re-point a pinned id at a different surface (text then lands
    somewhere the user never chose). So :meth:`current` returns ``None`` and drops the pin
    when the panel now under that id has a materially different pose: its centre is more
    than ``pin_move_tolerance_m`` metres (default 0.5) from where it was pinned, its normal
    turned by more than ``pin_turn_tolerance_rad`` (default 0.5 rad, about 29 degrees), or
    its width or height changed by more than 20 %. A panel that legitimately moves or
    resizes a little (a window being nudged, tracking drift) keeps its pin. The comparison
    is always against the pose at pin time, not the previous update, so a slow creep in
    small steps still ends the pin once the total drift passes the tolerance.
    """

    def __init__(self, registry: PanelRegistry, pin_move_tolerance_m: float = 0.5,
                 pin_turn_tolerance_rad: float = 0.5) -> None:
        for name, value in (("pin_move_tolerance_m", pin_move_tolerance_m),
                            ("pin_turn_tolerance_rad", pin_turn_tolerance_rad)):
            _check_time(name, value)
            if value <= 0:
                raise ValueError(f"{name} must be > 0")
        self._registry = registry
        self.pin_move_tolerance_m = float(pin_move_tolerance_m)
        self.pin_turn_tolerance_rad = float(pin_turn_tolerance_rad)
        self._panel_id: str | None = None
        self._pinned: _Fingerprint | None = None
        self._expires_at = 0.0

    def pin(self, panel_id: str, now_s: float, ttl_s: float = 60.0) -> None:
        """Pin a held, fresh panel for ``ttl_s``; KeyError if it is missing or stale."""
        _check_time("now_s", now_s)
        _check_time("ttl_s", ttl_s)
        if ttl_s <= 0:
            raise ValueError("ttl_s must be > 0")
        nid = _canonical_id(panel_id)
        panel = None if nid is None else self._registry.get(nid)
        if nid is None or panel is None or not self._registry.is_fresh(nid, now_s):
            raise KeyError(panel_id)
        self._panel_id = nid
        self._pinned = _fingerprint(panel)
        self._expires_at = now_s + ttl_s

    def _moved(self, then: _Fingerprint, now: Panel) -> bool:
        cx, cy, cz, nx, ny, nz, w, h = then
        n, c = now.normal, now.center
        if math.hypot(round(c.x, 3) - cx, round(c.y, 3) - cy, round(c.z, 3) - cz) > self.pin_move_tolerance_m:
            return True
        dot = nx * n.x + ny * n.y + nz * n.z
        if math.acos(max(-1.0, min(1.0, dot))) > self.pin_turn_tolerance_rad:
            return True
        for old, new in ((w, round(now.width, 3)), (h, round(now.height, 3))):
            old = max(old, 0.001)
            if abs(new - old) > _PIN_SIZE_TOLERANCE * old:
                return True
        return False

    def current(self, now_s: float) -> str | None:
        """The pinned panel id, or None once the pin lapsed or its panel is gone or moved.

        Never a dangling id: a removed, expired or stale panel clears the pin, and so does
        a panel that was re-posed beyond the documented tolerance.
        """
        _check_time("now_s", now_s)
        pid = self._panel_id
        if pid is None:
            return None
        panel = self._registry.get(pid)
        if (now_s >= self._expires_at or panel is None or not self._registry.is_fresh(pid, now_s)
                or self._pinned is None or self._moved(self._pinned, panel)):
            self.unpin()
            return None
        return pid

    def unpin(self) -> None:
        self._panel_id = None
        self._pinned = None


_QUOTES = frozenset('"\u201c\u201d\u201e\u201f\u00ab\u00bb\u2033\uff02')
_MAX_COMBINING_RUN = 2
# Beyond this many centimetres (1 km) a width is spoken as a bound, not a number.
_MAX_SPOKEN_CM = 100_000
_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
             "ninth", "tenth")


def _spoken_label(label: str) -> str:
    """Make a companion-supplied label safe to be read aloud *as quoted data*.

    NFKC-normalised; control, format (incl. bidi controls, zero-width) and unassigned
    characters removed; whitespace collapsed; ``<``, ``>``, ``&`` and double-quote-like
    characters neutralised so the label cannot close its own quotes or look like markup;
    strong right-to-left characters become ``?`` (a screen reader's voice switch inside a
    sentence is a spoofing channel); a run of more than two combining marks becomes one
    ``?``; then truncated to 40 characters.
    """
    text = unicodedata.normalize("NFKC", label)
    kept: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch.isspace() or cat in ("Zs", "Zl", "Zp") or ch in "<>&":
            kept.append(" ")
        elif ch in _QUOTES:
            kept.append("'")
        elif cat[0] == "C":  # control, format (bidi, zero-width), surrogate, private, unassigned
            continue
        elif unicodedata.bidirectional(ch) in ("R", "AL"):
            kept.append("?")
        else:
            kept.append(ch)
    out: list[str] = []
    run = 0
    for ch in kept:
        if unicodedata.category(ch)[0] == "M":
            run += 1
            if run == _MAX_COMBINING_RUN + 1:  # the run is too long: collapse it to one '?'
                del out[len(out) - _MAX_COMBINING_RUN:]
                out.append("?")
            elif run > _MAX_COMBINING_RUN + 1:
                continue
            else:
                out.append(ch)
        else:
            run = 0
            out.append(ch)
    cleaned = " ".join("".join(out).split())
    if len(cleaned) > _MAX_SPOKEN_LABEL:
        cleaned = cleaned[: _MAX_SPOKEN_LABEL - 3].rstrip() + "..."
    return cleaned


def _spoken_width(width: float) -> str:
    try:
        cm = max(1, round(width * 100))
    except (OverflowError, ValueError):  # width * 100 overflowed to inf
        cm = _MAX_SPOKEN_CM + 1
    if cm > _MAX_SPOKEN_CM:
        return "over 1000 metres wide"
    return f"{cm} {'centimetre' if cm == 1 else 'centimetres'} wide"


def _describe(name: str, width: float, ordinal: str = "") -> str:
    head = f'Panel labelled "{name}"' if name else "Unlabelled panel"
    return f"{head}{ordinal}, {_spoken_width(width)}"


def describe(panel: Panel) -> str:
    """Short spoken-style description, e.g. ``'Panel labelled "Notes", 40 centimetres wide'``.

    The label is companion-controlled, so it is spoken as quoted, sanitised data (see
    :func:`_spoken_label`) and never as running prose. Two panels can share a label; use
    :func:`describe_all` to tell them apart.
    """
    return _describe(_spoken_label(panel.label), panel.width)


def describe_all(panels: Sequence[Panel]) -> tuple[str, ...]:
    """Descriptions in input order; panels with the same spoken label get an ordinal.

    The ordinal (``first``, ``second``, ... then ``number 11``) follows ``panel_id`` order,
    so it is stable however the caller sorts the list, and reads ``first of 2`` so the
    listener knows more exist. Unlabelled panels count as sharing one (empty) label.
    """
    names = [_spoken_label(p.label) for p in panels]
    groups: dict[str, list[int]] = {}
    for i, name in enumerate(names):
        groups.setdefault(name, []).append(i)
    ordinal = [""] * len(panels)
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        for rank, i in enumerate(sorted(idxs, key=lambda j: (panels[j].panel_id, j))):
            word = _ORDINALS[rank] if rank < len(_ORDINALS) else f"number {rank + 1}"
            ordinal[i] = f", {word} of {len(idxs)}"
    return tuple(_describe(names[i], panels[i].width, ordinal[i]) for i in range(len(panels)))
