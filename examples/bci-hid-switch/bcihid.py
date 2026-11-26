"""Device-free parser for Apple's BCI HID reports (usage page 0x60). Research example only.

This is the reference code for ADR-v2-157 (research record only; the ADR-030 breadth
freeze stands). It turns **synthetic** report bytes into switch events shaped like
``yazses.biosignal.types.BioEvent``. It is not a YazSes feature: nothing under
``src/yazses/`` imports it, it imports nothing outside the standard library, it never
opens a device, never types and never opens a socket.

Report layout, from Apple's "Brain-computer interface HID reference for connecting to
Apple platforms" (developer.apple.com/documentation/accessibility/
brain-computer-interface-hid-reference-for-connecting-to-apple-platforms, read
2026-11-20). Every length below includes the leading report-ID byte, which is how
Linux hidraw ``read()`` and Windows ``ReadFile`` deliver numbered reports:

======  ======  =====  ==============================================================
ID      dir     bytes  fields
======  ======  =====  ==============================================================
1       in      3      signalQuality[0] = button number ID, [1] = strength 0..255
2       in      5      buttons[4]: 32 bits, bit i = button i, 1 = down; absolute state
3       in      4      position[3]: int8 x, y, z in -127..127; -128 = axis absent
4       in      2      itemIndex 0..255
4       out     7      selectedItem, numberOfItems, seed, itemControlType,
                       uiScanningLatencyInt, uiScanningLatencyFrac (x/255)
======  ======  =====  ==============================================================

Run ``python examples/bci-hid-switch/bcihid.py 020100000002000000`` style hex
arguments (one report per argument) to see the events a sequence would produce.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

# -- constants from Apple's reference -------------------------------------------------

USAGE_PAGE_BCI = 0x60
USAGE_BCI_APPLICATION = 0x01
USAGE_SIGNAL_QUALITY = 0x02
USAGE_NUMBER_OF_ITEMS = 0x03
USAGE_ITEM_SELECTION = 0x04
USAGE_PAGE_BUTTON = 0x09
USAGE_PAGE_GENERIC_DESKTOP = 0x01

REPORT_SIGNAL_QUALITY = 1
REPORT_BUTTONS = 2
REPORT_POINTER = 3
REPORT_ITEM_SELECTION = 4  # input
REPORT_SCAN_INFO = 4  # output (same ID, other direction)

#: Report length in bytes *including* the report-ID byte, keyed by (direction, id).
REPORT_LENGTHS: dict[tuple[str, int], int] = {
    ("input", REPORT_SIGNAL_QUALITY): 3,
    ("input", REPORT_BUTTONS): 5,
    ("input", REPORT_POINTER): 4,
    ("input", REPORT_ITEM_SELECTION): 2,
    ("output", REPORT_SCAN_INFO): 7,
}

N_BUTTONS = 32
AXIS_ABSENT = -128

#: Apple's descriptor comment: "button 0 = select, button 1 = next, button 2 = previous,
#: button 3 = menu". Apple names no default button for any other action.
APPLE_DEFAULT_BUTTONS: dict[int, str] = {0: "select", 1: "next", 2: "previous", 3: "menu"}

#: Apple's "List of actions" for iOS, in Apple's order, renamed to snake_case. The page
#: does not say that list position is a button index, so this is a vocabulary only.
APPLE_ACTIONS: tuple[str, ...] = (
    "select",  # Select
    "move_to_next_item",  # MoveToNextItem
    "move_to_previous_item",  # MoveToPreviousItem
    "toggle_assistive_technology_menu",  # ToggleAssistiveTechnologyMenu
    "activate",  # Activate
    "start_sequential_navigation",  # StartSequentialNavigation
    "stop_sequential_navigation",  # StopSequentialNavigation
    "trigger_automation",  # TriggerAutomation
    "toggle_app_switcher",  # ToggleAppSwitcher
    "home",  # Home
    "toggle_notifications_view",  # ToggleNotificationsView
    "assistant",  # Assistant
    "volume_down",  # VolumeDown
    "volume_up",  # VolumeUp
    "toggle_dictation",  # ToggleDictation
    "toggle_accessibility_feature",  # ToggleAccessibilityFeature
    "toggle_quick_settings_view",  # ToggleQuickSettingsView
    "escape",  # Escape
    "scroll_up",  # ScrollUp
    "scroll_down",  # ScrollDown
    "scroll_left",  # ScrollLeft
    "scroll_right",  # ScrollRight
)

#: Apple's example report descriptor, byte for byte (the reference's Appendix). Kept so
#: the report lengths above can be checked against it rather than trusted.
APPLE_EXAMPLE_DESCRIPTOR = bytes([
    0x05, 0x60, 0x09, 0x01, 0xA1, 0x01,                    # BCI page, BCI application
    0x05, 0x60, 0x09, 0x02, 0x85, 0x01, 0xA1, 0x02,        # signal quality, report 1
    0x09, 0x02, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x75, 0x08, 0x95, 0x02, 0x81, 0x06, 0xC0,
    0x05, 0x09, 0x09, 0x01, 0x85, 0x02, 0xA1, 0x00,        # buttons, report 2
    0x19, 0x01, 0x29, 0x20, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x20, 0x81, 0x02, 0xC0,
    0x05, 0x01, 0x09, 0x01, 0x85, 0x03, 0xA1, 0x00,        # pointer, report 3
    0x09, 0x30, 0x09, 0x31, 0x09, 0x32, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x03,
    0x81, 0x06, 0xC0,
    0x05, 0x60, 0x09, 0x04, 0x85, 0x04, 0xA1, 0x02,        # item selection, input 4
    0x09, 0x04, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06, 0xC0,
    0x05, 0x60, 0xA1, 0x02, 0x85, 0x04,                    # scan info, output 4
    0x09, 0x03, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x75, 0x08, 0x95, 0x06, 0x91, 0x03, 0xC0,
    0xC0,
])

# -- YazSes side: design choices of ADR-v2-157, not facts about the protocol ------------

#: Event kinds this example emits. The first two are the existing
#: ``yazses.biosignal.types.EventKind`` values (the mode pair the runner already turns
#: into ``on_mode_start`` / ``on_mode_end``). ``switch_press`` is the one kind ADR-v2-157
#: proposes adding to ``EventKind`` at build time; it does not exist in the product.
KIND_MODE_ON = "squeeze_on"
KIND_MODE_OFF = "squeeze_off"
KIND_SWITCH_PRESS = "switch_press"
PROPOSED_KINDS = frozenset({KIND_SWITCH_PRESS})

#: Design default: refuse a press whose button's last reported strength is below this
#: raw value (64/255, about 25 %). Changed with data, never guessed upward.
QUALITY_FLOOR_DEFAULT = 64

#: Which YazSes command-grammar label each Apple action may become, by default. Only
#: labels that ``commands/grammars/en.py`` already parses. ``select`` (would be Enter)
#: and ``previous`` (no shift-tab command exists) are deliberately unmapped: inert.
DEFAULT_ACTION_LABELS: dict[str, str] = {
    "next": "press tab",
    "move_to_next_item": "press tab",
    "escape": "press escape",
}

#: The one action that is a mode, not an intent.
TOGGLE_DICTATION = "toggle_dictation"


class ReportError(ValueError):
    """A report that does not match Apple's layout. ``reason`` is a short stable key."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


# -- parsed reports -------------------------------------------------------------------


@dataclass(frozen=True)
class SignalQuality:
    button: int
    strength: int  # 0..255


@dataclass(frozen=True)
class ButtonState:
    bits: int  # bit i set = button i down

    def pressed(self) -> frozenset[int]:
        return frozenset(i for i in range(N_BUTTONS) if self.bits >> i & 1)


@dataclass(frozen=True)
class Pointer:
    x: int
    y: int | None
    z: int | None

    @property
    def dimensions(self) -> int:
        return 1 + (self.y is not None) + (self.z is not None)


@dataclass(frozen=True)
class ItemSelection:
    index: int


@dataclass(frozen=True)
class ScanInfo:
    selected_item: int
    number_of_items: int
    seed: int
    item_control_type: int  # 0 discrete, 1 continuous
    latency_s: float


Report = SignalQuality | ButtonState | Pointer | ItemSelection


def _int8(b: int) -> int:
    return b - 256 if b > 127 else b


def parse_input_report(data: bytes) -> Report:
    """Parse one input report, report-ID byte first. Strict: the length must be exact."""
    if not data:
        raise ReportError("empty")
    rid = data[0]
    expected = REPORT_LENGTHS.get(("input", rid))
    if expected is None:
        raise ReportError("unknown_report_id", str(rid))
    if len(data) != expected:
        raise ReportError("bad_length", f"report {rid}: {len(data)} != {expected}")
    if rid == REPORT_SIGNAL_QUALITY:
        return SignalQuality(button=data[1], strength=data[2])
    if rid == REPORT_BUTTONS:
        return ButtonState(bits=int.from_bytes(data[1:5], "little"))
    if rid == REPORT_POINTER:
        x, y, z = (_int8(b) for b in data[1:4])
        # Apple: x must be valid, and the valid axes must be x, x+y or x+y+z;
        # the host ignores any other shape.
        if x == AXIS_ABSENT or (y == AXIS_ABSENT and z != AXIS_ABSENT):
            raise ReportError("pointer_shape", f"x={x} y={y} z={z}")
        return Pointer(
            x=x,
            y=None if y == AXIS_ABSENT else y,
            z=None if z == AXIS_ABSENT else z,
        )
    return ItemSelection(index=data[1])


def parse_scan_info(data: bytes) -> ScanInfo:
    """Parse the host-to-device output report 4 (report-ID byte first)."""
    if len(data) != REPORT_LENGTHS[("output", REPORT_SCAN_INFO)] or data[0] != REPORT_SCAN_INFO:
        raise ReportError("bad_scan_info", data.hex())
    return ScanInfo(data[1], data[2], data[3], data[4], data[5] + data[6] / 255.0)


# -- encoders for synthetic test bytes (what a device, or a host, would send) ---------


def encode_signal_quality(button: int, percent: int) -> bytes:
    """Apple's scaling: ``(uint8_t)((float)percent * 255.0 / 100.0)``, i.e. truncation."""
    if not 0 <= button <= 255 or not 0 <= percent <= 100:
        raise ValueError("button 0..255, percent 0..100")
    return bytes([REPORT_SIGNAL_QUALITY, button, int(percent * 255.0 / 100.0)])


def encode_buttons(pressed: Iterable[int]) -> bytes:
    bits = 0
    for i in pressed:
        if not 0 <= i < N_BUTTONS:
            raise ValueError(f"button index {i} outside 0..31")
        bits |= 1 << i
    return bytes([REPORT_BUTTONS]) + bits.to_bytes(4, "little")


def clamp_axis(value: int) -> int:
    """Apple's ``bci_clamp_axis``: a real value never equals the -128 sentinel."""
    return max(-127, min(127, value))


def encode_pointer(x: int, y: int | None = None, z: int | None = None) -> bytes:
    axes = [clamp_axis(x)]
    axes.append(AXIS_ABSENT if y is None else clamp_axis(y))
    axes.append(AXIS_ABSENT if z is None else clamp_axis(z))
    return bytes([REPORT_POINTER]) + bytes(a & 0xFF for a in axes)


def encode_item_selection(index: int) -> bytes:
    if not 0 <= index <= 255:
        raise ValueError("index 0..255")
    return bytes([REPORT_ITEM_SELECTION, index])


def encode_scan_info(
    selected_item: int,
    number_of_items: int,
    seed: int,
    item_control_type: int,
    latency_s: float,
    *,
    focus_is_keyboard_key: bool,
) -> bytes:
    """Host-to-device report 4. Mirrors Apple's privacy rule: when focus is on a keyboard
    key, only the latency is sent and every other field is zero."""
    if not 0 <= latency_s < 256 or math.isnan(latency_s):
        raise ValueError("latency 0..<256 s")
    whole = int(latency_s)
    frac = min(255, round((latency_s - whole) * 255))
    if focus_is_keyboard_key:
        selected_item = number_of_items = seed = item_control_type = 0
    fields = (selected_item, number_of_items, seed, item_control_type)
    if any(not 0 <= v <= 255 for v in fields):
        raise ValueError("fields 0..255")
    return bytes([REPORT_SCAN_INFO, *fields, whole, frac])


# -- a tiny descriptor walker (short items only; Apple's descriptor has no long items) --


@dataclass(frozen=True)
class DescriptorSummary:
    top_usage_page: int
    top_usage: int
    report_bits: dict[tuple[str, int], int]  # (direction, report id) -> data bits

    def report_bytes(self, direction: str, rid: int) -> int:
        """Bytes including the report-ID byte."""
        return 1 + math.ceil(self.report_bits[(direction, rid)] / 8)


def summarize_descriptor(desc: bytes) -> DescriptorSummary:
    """Find the top-level collection's usage page/usage and each report's size."""
    i = 0
    usage_page = 0
    last_usage = 0
    report_size = report_count = report_id = 0
    top: tuple[int, int] | None = None
    bits: dict[tuple[str, int], int] = {}
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:
            raise ReportError("long_item")
        size = (0, 1, 2, 4)[prefix & 0x03]
        if i + 1 + size > len(desc):
            raise ReportError("truncated_descriptor")
        value = int.from_bytes(desc[i + 1 : i + 1 + size], "little")
        kind, tag = (prefix >> 2) & 0x03, prefix >> 4
        i += 1 + size
        if kind == 1:  # global
            if tag == 0x0:
                usage_page = value
            elif tag == 0x7:
                report_size = value
            elif tag == 0x8:
                report_id = value
            elif tag == 0x9:
                report_count = value
        elif kind == 2 and tag == 0x0:  # local Usage
            last_usage = value
        elif kind == 0:  # main
            if tag == 0xA and value == 0x01 and top is None:  # Collection(Application)
                top = (usage_page, last_usage)
            elif tag in (0x8, 0x9):  # Input / Output
                key = ("input" if tag == 0x8 else "output", report_id)
                bits[key] = bits.get(key, 0) + report_size * report_count
    if top is None:
        raise ReportError("no_application_collection")
    return DescriptorSummary(top[0], top[1], bits)


def is_bci_descriptor(desc: bytes) -> bool:
    """What a per-OS reader would check before opening a device: the top-level
    collection is usage page 0x60, usage 1. Never decided by vendor or product ID."""
    try:
        s = summarize_descriptor(desc)
    except ReportError:
        return False
    return (s.top_usage_page, s.top_usage) == (USAGE_PAGE_BCI, USAGE_BCI_APPLICATION)


# -- the switch decoder ---------------------------------------------------------------


@dataclass(frozen=True)
class SwitchEvent:
    """Same field names as ``yazses.biosignal.types.BioEvent``; ``kind`` is its value
    string, so a build converts one to the other without a lookup table."""

    kind: str
    t: float
    confidence: float = 1.0
    channel: str = ""
    detail: dict = field(default_factory=dict)


class SwitchDecoder:
    """Turn a stream of input reports into switch events. Pure, single-threaded.

    * Edges come from the absolute 32-bit state; a repeated state produces nothing.
    * The first button report is a baseline: a button already down when the stream
      starts is not a press (a device that connects mid-hold must not act).
    * Only press edges act. ``toggle_dictation`` flips a mode and emits ``squeeze_on``
      or ``squeeze_off``; any other mapped action emits ``switch_press`` with its
      command-grammar label in ``detail``. Unmapped buttons and unlabelled actions
      are counted and do nothing.
    * A press is refused, silently and counted, when the device's last signal-quality
      report for that button is below ``quality_floor``. No report yet means unknown,
      which does not refuse: the guard holds only on the device's own checkable number.
    * Pointer and item-selection reports are parsed and counted, never acted on.
    * Malformed reports are counted by reason; nothing raises out of ``feed``.
    """

    def __init__(
        self,
        button_actions: Mapping[int, str] | None = None,
        action_labels: Mapping[str, str] | None = None,
        *,
        quality_floor: int = QUALITY_FLOOR_DEFAULT,
    ) -> None:
        if not 0 <= quality_floor <= 255:
            raise ValueError("quality_floor 0..255")
        actions = dict(APPLE_DEFAULT_BUTTONS if button_actions is None else button_actions)
        for idx in actions:
            if not 0 <= idx < N_BUTTONS:
                raise ValueError(f"button index {idx} outside 0..31")
        self._actions = actions
        self._labels = dict(DEFAULT_ACTION_LABELS if action_labels is None else action_labels)
        self._floor = quality_floor
        self._quality: dict[int, int] = {}
        self._prev_bits: int | None = None
        self._dictating = False
        self.counts: dict[str, int] = {}

    @property
    def dictating(self) -> bool:
        return self._dictating

    def _count(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def feed(self, data: bytes, t: float) -> list[SwitchEvent]:
        try:
            report = parse_input_report(bytes(data))
        except ReportError as exc:
            self._count(f"rejected:{exc.reason}")
            return []
        if isinstance(report, SignalQuality):
            self._quality[report.button] = report.strength
            self._count("signal_quality")
            return []
        if isinstance(report, Pointer):
            self._count("pointer_ignored")
            return []
        if isinstance(report, ItemSelection):
            self._count("item_selection_ignored")
            return []
        return self._buttons(report.bits, t)

    def _buttons(self, bits: int, t: float) -> list[SwitchEvent]:
        prev, self._prev_bits = self._prev_bits, bits
        if prev is None:
            self._count("baseline")
            return []
        pressed = bits & ~prev
        events: list[SwitchEvent] = []
        for idx in range(N_BUTTONS):
            if pressed >> idx & 1:
                event = self._press(idx, t)
                if event is not None:
                    events.append(event)
        return events

    def _press(self, idx: int, t: float) -> SwitchEvent | None:
        action = self._actions.get(idx)
        if action is None:
            self._count("unmapped_button")
            return None
        quality = self._quality.get(idx)
        if quality is not None and quality < self._floor:
            self._count("refused_low_quality")
            return None
        confidence = 1.0 if quality is None else quality / 255.0
        detail: dict = {"button": idx, "action": action, "quality": quality}
        channel = f"bci-hid:button{idx}"
        if action == TOGGLE_DICTATION:
            self._dictating = not self._dictating
            kind = KIND_MODE_ON if self._dictating else KIND_MODE_OFF
            return SwitchEvent(kind, t, confidence, channel, detail)
        label = self._labels.get(action, "").strip()
        if not label:
            self._count("unlabelled_action")
            return None
        detail["label"] = label
        return SwitchEvent(KIND_SWITCH_PRESS, t, confidence, channel, detail)

    def release_all(self, t: float) -> list[SwitchEvent]:
        """The global pause (ADR-v2-148): close an open dictation mode and forget the
        button baseline, so a button held across the pause cannot act on resume."""
        self._prev_bits = None
        if not self._dictating:
            return []
        self._dictating = False
        return [SwitchEvent(KIND_MODE_OFF, t, 1.0, "bci-hid", {"reason": "release_all"})]


# -- the per-OS seam, as a Protocol only ----------------------------------------------


class HidReportSource(Protocol):
    """What a per-OS reader (hidraw, IOHIDManager, Windows HID) would provide. None is
    implemented here; ``ReplaySource`` stands in with synthetic bytes."""

    def report_descriptor(self) -> bytes: ...
    def read_report(self) -> bytes | None: ...
    def close(self) -> None: ...


class ReplaySource:
    """A finite, in-memory source of synthetic reports."""

    def __init__(self, reports: Sequence[bytes], descriptor: bytes = APPLE_EXAMPLE_DESCRIPTOR):
        self._descriptor = bytes(descriptor)
        self._it: Iterator[bytes] = iter(list(reports))
        self.closed = False

    def report_descriptor(self) -> bytes:
        return self._descriptor

    def read_report(self) -> bytes | None:
        return next(self._it, None)

    def close(self) -> None:
        self.closed = True


def run(source: HidReportSource, decoder: SwitchDecoder, dt: float = 0.01) -> list[SwitchEvent]:
    """Drain a source through a decoder. Refuses a device that is not usage page 0x60."""
    try:
        if not is_bci_descriptor(source.report_descriptor()):
            raise ReportError("not_a_bci_device")
        events: list[SwitchEvent] = []
        t = 0.0
        while (data := source.read_report()) is not None:
            events += decoder.feed(data, t)
            t += dt
        return events
    finally:
        source.close()


def main(argv: Sequence[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    try:
        reports = [bytes.fromhex(a) for a in argv]
    except ValueError as exc:
        print(f"not hex: {exc}", file=sys.stderr)
        return 2
    decoder = SwitchDecoder()
    for ev in run(ReplaySource(reports), decoder):
        print(f"{ev.t:6.2f}  {ev.kind:<12} {ev.channel:<18} {ev.detail}")
    print(f"counts: {decoder.counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
