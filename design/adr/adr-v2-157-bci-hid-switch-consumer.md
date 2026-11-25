# ADR-v2-157 — A consumer for Apple's BCI HID switch protocol: research record, device-free parser, no product feature

**Status:** Proposed — research record only (2026-11-20). No implementation is authorised. Anything beyond the device-free example needs a recorded go and a named ADR-030 freeze exception
**Scope:** Whether YazSes should read brain-computer interfaces that implement Apple's BCI HID descriptor (usage page `0x60`, intent decoded on the device) as a switch on macOS, Linux and Windows. **Not** a new YazSes capability, not a claim that any device works, not an authorisation to change `src/`
**Related:** [ADR-030](adr-030-agent-era-direction.md) (breadth freeze; its 2026-11-01 amendment names "new device families"), [ADR-v2-152](adr-v2-152-biosignal-artifact-switches.md) (biosignal switches: the detector emits events, never actions), [ADR-v2-153](adr-v2-153-biosignal-false-positive-governor.md) (the false-positive governor), [ADR-021](adr-021-invest-in-error-cost.md) (a guard is judged on how rarely it fires), [ADR-v2-148](adr-v2-148-hands-free-composition.md) (one global pause), [ADR-019](adr-019-egress-inventory-and-escalation.md) (egress inventory), [ADR-v2-156](adr-v2-156-maixcam2-text-link.md) (the precedent for a research record with an out-of-tree example)
**Companion artefacts:** the device-free reference parser `examples/bci-hid-switch/` and its tests `tests/test_example_bci_hid_switch.py`. Source plan: [`design/research/2026-11-19-landscape-start-plans.md`](../research/2026-11-19-landscape-start-plans.md), item M3

Evidence labels used throughout: **[V]** verified, with the source named · **[U]** unverified · **[O]** engineering judgement.

---

## Context and problem

Apple published a HID descriptor for BCI hardware. The device decodes neural activity
itself and presents the result to the host as ordinary HID reports: button presses, a
pointer, an item selection and a signal-quality value. The host maps them to Switch Control.
This has the same shape as YazSes's biosignal pipeline (decoded signal → discrete switch
event → action), but standardised, with the decoding done on the device.

Apple's support covers iOS, iPadOS and visionOS. A device built to this descriptor is a HID
device, so in principle any desktop can read it. YazSes could make such a device a switch on
macOS, Linux and Windows. Nobody has shown that this works, and no device is available.

| Fact | Label | Source |
|---|---|---|
| Apple's reference defines a HID descriptor so that BCI hardware "can be recognized by a host computing device … without requiring specialized drivers", for Switch Control and AssistiveTouch | **[V]** | Apple Developer, *Brain-computer interface HID reference for connecting to Apple platforms*, <https://developer.apple.com/documentation/accessibility/brain-computer-interface-hid-reference-for-connecting-to-apple-platforms>, read 2026-11-20 (page content read through the documentation site's data endpoint) |
| The page's availability metadata: iOS 26.0, iPadOS 26.0, Mac Catalyst 26.0, visionOS 26.0. macOS is not listed | **[V]** | same page |
| Whether a Mac (through Mac Catalyst or otherwise) consumes these reports for its own Switch Control | **[U]** | the page does not say. Mac Catalyst appearing in the metadata is not evidence that macOS acts on the device |
| Apple announced: "iOS, iPadOS, and visionOS will add a new protocol to support Switch Control for Brain Computer Interfaces (BCIs)" | **[V]** | Apple Newsroom, *Apple unveils powerful accessibility features coming later this year*, 13 May 2025, <https://www.apple.com/newsroom/2025/05/apple-unveils-powerful-accessibility-features-coming-later-this-year/> |
| Synchron reported the first native integration with iPhone, iPad and Apple Vision Pro | **[U]** here: a company claim, not re-read for this record | [BioSpace press release](https://www.biospace.com/press-releases/synchron-to-achieve-first-native-brain-computer-interface-integration-with-iphone-ipad-and-apple-vision-pro), cited in the [landscape note](../research/2026-11-19-offline-voice-tech-landscape.md) |
| No BCI HID device is owned or on loan, and no user has asked for this | **[V]** that none is recorded | repository and tracker, 2026-11-20 |
| YazSes already turns switch events into actions: `EventKind.SQUEEZE_ON` / `SQUEEZE_OFF` drive `on_mode_start` / `on_mode_end`; other events become `ActivationIntent` labels that go through the ordinary command grammar | **[V]** | `src/yazses/biosignal/types.py`, `biosignal/pipeline.py` (`events_to_intents`), `activation/intent.py` |
| The governor's ledger counts every `EventKind` except `SQUEEZE_OFF` as an activation, so a new kind is governed with no code change | **[V]** | `biosignal/fprate.py`, `ACTIVATING_KINDS = frozenset(EventKind) - {EventKind.SQUEEZE_OFF}` |

## The report layout (from Apple's reference)

Every item in this section is **[V]** from the Apple page above unless it is labelled
otherwise. Lengths include the report-ID byte. The device-free example derives every length
from Apple's own example descriptor (119 bytes, copied byte for byte), so these figures are
checked, not just copied.

### Top level

- Usage page `0x60` ("Brain Control Interface"), usage `0x01` ("BCI Application"),
  Collection (Application). Inside it: usage `0x02` = Signal Quality, `0x03` = number of
  items (on the output report), `0x04` = Item Selection. Buttons use the standard Button page
  (`0x09`), and the pointer uses Generic Desktop (`0x01`, usage Pointer, axes X/Y/Z
  `0x30`–`0x32`). Both are nested inside the `0x60` application collection.
- Whether `0x60` is assigned in the USB-IF HID Usage Tables, or is Apple's own choice:
  **[U]**. This record did not read the usage tables.

### Input reports (device → host)

| Report ID | Bytes | Layout | Meaning |
|---|---|---|---|
| 1 — signal quality (usage `0x02`) | 3 | `signalQuality[0]` = button number ID; `signalQuality[1]` = neural activity strength. The device scales a percentage to 0–255 with `(uint8_t)(percent * 255.0 / 100.0)` | Drives a visual indicator. iOS shows it as an animated overlay while the Switch Control cursor has focus on an element |
| 2 — buttons (Button page, usages 1–32) | 5 | `buttons[4]`, 32 single bits. Bit `i` lives in byte `i / 8` with mask `1 << (i % 8)`. `1` = down. **Absolute state**: every report carries all 32 buttons | Presses mapped by the host to Switch Control actions |
| 3 — pointer (Generic Desktop) | 4 | `position[3]`, signed 8-bit x, y, z, logical range −127..127. `−128` (`0x80`) is a reserved **axis absent** sentinel. x must be valid. Valid axes x → 1D gliding cursor; x+y → 2D pointer (head-tracking equivalent); x+y+z → 3D spatial picker (visionOS). The host ignores any other shape. Relative deltas by default; absolute positions if the descriptor's Input item is `0x81 0x02` instead of `0x81 0x06` (1D and 2D only; 3D is always relative). Apple says the host does not clamp, so a stray −128 reads as an absent axis | Pointer movement |
| 4 — item selection (usage `0x04`) | 2 | `itemIndex`, 0–255 | Asks the host to act on a particular item of the current scan |

### Output report (host → device)

| Report ID | Bytes | Layout |
|---|---|---|
| 4 — scan information | 7 | `selectedItem`, `numberOfItems`, `seed` (identifies the scan cycle), `itemControlType` (0 discrete, 1 continuous such as a slider), `uiScanningLatencyInt`, `uiScanningLatencyFrac` (latency = int + frac/255 seconds) |

- **Privacy rule [V]:** "The host computing device doesn't send information about the
  focused item if it's a keyboard key … to protect user privacy." The descriptor comment adds:
  "When on keyboard (for privacy), only send UI scanning latency. Other fields are zero-set."
  The host tells the device *where in the scan* it is, never *which key* has focus.
- Input report 4 and output report 4 share a report ID. They are distinguished by
  direction **[V]**.
- Apple's example declares the output item `0x91 0x03` (Output, **Constant**, Variable).
  Whether every host stack delivers output data declared Constant is **[U]**.

### Buttons and actions

- Apple's descriptor comment: "By default, button 0 = select, button 1 = next, button 2 =
  previous, button 3 = menu" **[V]**.
- Apple lists 22 actions for iOS **[V]**: Select, MoveToNextItem, MoveToPreviousItem,
  ToggleAssistiveTechnologyMenu, Activate, StartSequentialNavigation,
  StopSequentialNavigation, TriggerAutomation, ToggleAppSwitcher, Home,
  ToggleNotificationsView, Assistant, VolumeDown, VolumeUp, **ToggleDictation**,
  ToggleAccessibilityFeature, ToggleQuickSettingsView, **Escape**, ScrollUp, ScrollDown,
  ScrollLeft, ScrollRight.
- The page does **not** say that a position in that list is a button index, or which button
  sends ToggleDictation **[V]** that it is silent. Beyond buttons 0–3, the assignment of
  buttons to actions is therefore **[U]**, and presumably host-side configuration **[O]**. A
  YazSes consumer must let the user assign buttons rather than assume an index.

## Hypothesis (falsifiable)

> **H1.** A BCI HID device that follows Apple's descriptor, connected to a desktop running a
> user-space reader with no kernel driver, can be identified by its usage page alone. Its
> button and signal-quality reports reach the reader byte for byte as laid out above. The
> operating system does not also act on those buttons or that pointer on its own. All three
> hold on at least one of Linux, macOS and Windows.

H1 is false, and the build stops on that OS, if any of these is observed on a named device
and OS version:

- **F1.** User space cannot open the device without a kernel driver, root, or a permission
  that YazSes must not ask for.
- **F2.** The OS input stack claims the nested Button or Generic Desktop collection and moves
  the system cursor or emits key events. The device would then act twice, once through the
  OS and once through YazSes.
- **F3.** The bytes read do not match Apple's layout. For example, report IDs are stripped,
  or the OS reassembles the reports differently.

## Why now, and why not now

**Why now.** The report layout can be recorded and a parser written and tested from
synthetic bytes, with no device and no change to `src/` **[O]**. ADR-030 §3 allows a
*Proposed* ADR during the freeze and stops there **[V]**. The device-free example follows
ADR-v2-156, which the maintainer accepted for its own example on 2026-11-13 **[V]**.

**Why not now.**

- **The freeze names this exactly.** The 2026-11-01 amendment keeps the freeze for "further
  biosignal capabilities and new device families" **[V]** (`adr-030-agent-era-direction.md`).
- **No device and no demand.** No BCI HID device is available to the project, and no
  non-contributor has asked for one **[V]**. ADR-021: investment follows evidence.
- **The OS behaviour that decides feasibility is unmeasured** (F1–F3).

## Decision

1. **Record the research question and stop at the roadmap gate.** No `src/` change, config
   key, CLI command, IPC method, registry capability or extra in `pyproject.toml`.
2. **Ship only the device-free example** under `examples/bci-hid-switch/`. It contains a
   stdlib-only parser for the five reports, encoders for synthetic bytes, a descriptor walker,
   a `SwitchDecoder` that applies the mapping below, the reader seam as a `Protocol`, and an
   in-memory replay source. Tests are in `tests/test_example_bci_hid_switch.py`. It opens no
   device, types nothing and opens no socket. Removing it is one commit.
3. **The build waits** for a recorded maintainer go and a named freeze exception. It must then
   follow [Build plan](#build-plan-when-the-freeze-allows) and
   [Requirements](#requirements-on-any-future-product-wiring).

## Mapping to existing YazSes actions

The consumer is a new **source** of the existing biosignal event types, not a new action
path **[O]**. A BCI HID device has already decoded intent. YazSes adds no detector. It adds a
report decoder, which sits where `StreamDetector` sits and emits `BioEvent`s.

| Apple action | Event emitted | What YazSes does with it (existing path) |
|---|---|---|
| ToggleDictation (button chosen by the user; Apple gives no default) | `EventKind.SQUEEZE_ON` on one press, `SQUEEZE_OFF` on the next | `on_mode_start` / `on_mode_end`, the same dictation mode an EMG squeeze holds. A *click* toggles because Apple's sample firmware sends press and release back to back **[V]**. A hold mapping would record nothing |
| Next / MoveToNextItem (button 1 by default) | `switch_press`, label `press tab` | `ActivationIntent("press tab")` → command grammar → `press_tab` **[V]** that the grammar parses it |
| Escape | `switch_press`, label `press escape` | → `press_escape` **[V]** |
| Select (button 0) | none by default | Select would be Enter. Enter in a terminal runs a command, so it is never a default (the ADR-v2-156 T9 rule). A user may map it; the grammar's consequence gate still applies |
| Previous (button 2) | none | The grammar has no shift-tab command **[V]**. It stays inert until such a command exists through its own PR |
| Menu (button 3), the other 17 actions, buttons 4–31 | none | Unmapped means inert, the same as `events_to_intents` today |

- **Event kinds.** `SQUEEZE_ON` and `SQUEEZE_OFF` are reused unchanged. Discrete presses
  need one new member, `EventKind.SWITCH_PRESS = "switch_press"`. That is the only change to
  the shared contract. Because `ACTIVATING_KINDS` is "every kind except `SQUEEZE_OFF`", the
  ADR-v2-153 governor counts it, desensitises and suspends with **no change to the governor**
  **[V]** by reading `fprate.py`. Mapping presses onto `BLINK` or `DOUBLE_BLINK` instead was
  rejected: it would mix the ledger's per-kind counts for two different input families.
- **Confidence.** The press carries `confidence = strength / 255` from the button's latest
  signal-quality report, or 1.0 when none has been seen. The governor's desensitise state
  raises the pipeline's confidence floor, so it also applies to a BCI source unchanged. Whether
  Apple's "neural activity strength" behaves like a confidence is **[U]**. It is a design
  assumption, and the field test must check it.
- **Edges, not levels.** Reports carry absolute state, so only a 0 → 1 transition acts. A
  repeated report is idle. The **first** button report after the stream opens (or after a
  pause) is a baseline, so a device that connects while a button is held cannot act.
- **Global pause (ADR-v2-148).** On pause, an open dictation mode is closed with
  `SQUEEZE_OFF` and the baseline is forgotten. A button held across the pause does not fire
  when it ends.
- **Pointer and item selection** are parsed and counted, never acted on, in the first build.
  YazSes has no Switch Control scanner that could give an item index a meaning, and a pointer
  source is a separate decision **[O]**.
- **Scan feedback (output report 4).** The first build sends none, because YazSes does not
  scan. If a scanner is added later, it must mirror Apple's rule: on a keyboard key, send the
  latency only and set the other fields to zero. The example's encoder enforces this rule, and
  a test checks it.

## Signal quality: refuse to act below a threshold

- **The rule.** If the device's latest signal-quality report for the pressed button is below
  `quality_floor`, the press is **refused**. It is dropped silently and counted; it never
  prompts. The design default is 64/255 (about 25 %). That number is a design choice, not a
  measurement, and only data can change it.
- **Why this fits ADR-021.** The guard holds only on a *specific, checkable* number the
  device itself reports, never on a heuristic. A refusal costs the user one more press. It
  does not interrupt them with a dialog, so it does not train them to dismiss it.
- **No report means unknown, not bad.** A device that never sends report 1 is not refused.
  Refusing it would disable every device that omits an optional report, and the governor still
  counts its presses. Apple does not say how often devices send the report, or whether they
  send it at all when not scanning **[U]**.
- **No staleness timeout** in the first build. Without a device, nobody knows the report's
  cadence, so any timeout would be invented **[O]**.

## Per-OS reading, behind a Protocol

AGENTS.md rule 6 applies: no `sys.platform` branch. The seam is one Protocol, already sketched
in the example as `HidReportSource`:

```python
class HidReportSource(Protocol):
    def report_descriptor(self) -> bytes: ...
    def read_report(self) -> bytes | None: ...   # report-ID byte first
    def close(self) -> None: ...
```

The reader identifies a device by the top-level collection of its descriptor: usage page
`0x60`, usage `0x01`. It never uses vendor or product IDs, and it never scans or probes other
devices. The user names the device, as with the EMG serial port.

| OS | Mechanism | What is known |
|---|---|---|
| Linux | `/dev/hidrawN`. `HIDIOCGRDESC` returns the report descriptor. With numbered reports, `read()` returns the report number as the first byte and the data after it, and `write()` takes the report number first | **[V]** Linux kernel documentation, *HIDRAW — Raw Access to USB and Bluetooth Human Interface Devices*, <https://docs.kernel.org/hid/hidraw.html>. Node permissions are set by udev; a non-root user normally needs a udev rule **[U]**, and the page does not cover permissions. Whether `hid-input` also maps the nested Button page and Generic Desktop pointer into an evdev device, so that the system cursor moves (F2), is **[U]** |
| macOS | IOKit `IOHIDManager`, matching on primary usage page `0x60`; input-report callback | **[O]** that this is the API. Whether macOS asks for the Input Monitoring permission for a non-keyboard HID device, and whether it acts on the nested pointer, is **[U]**. Apple's page targets iOS, iPadOS and visionOS hosts, not macOS |
| Windows | HID class driver; a user-mode application finds the collection with `SetupDi*`, opens it with `CreateFile`, reads input reports with `ReadFile`, writes output reports with `WriteFile`, and interprets them with `HidP_*` | **[V]** Microsoft Learn, *Opening HID collections*, <https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/opening-hid-collections>. Because the top-level collection is page `0x60`, not a mouse or keyboard, it should be openable rather than held exclusively by the system **[U]** until measured |

The readers are thin. All parsing stays in the pure module (AGENTS.md rule 5), so the three
readers differ only in how they obtain bytes.

## Threat model (summary)

| # | Threat | Mitigation |
|---|---|---|
| T1 | A hostile or faulty device sends a flood of presses | Edge-only action; the governor (ADR-v2-153) desensitises, then suspends, with a one-action release; the global pause stops it. A future reader must bound its queue and drop the newest reports **[O]** |
| T2 | A device lies about signal quality | The floor only ever *refuses*. A lying device can disable its own quality guard, but it cannot reach any action beyond what the mapping allows |
| T3 | A press reaches an irreversible action | Labels only, through the command grammar and its consequence gate. Enter and send are never defaults. There is no free text: the protocol carries none, and the consumer accepts none |
| T4 | Malformed reports | Strict lengths and IDs; unknown IDs and pointer shapes are counted and dropped; nothing raises out of the decoder (fuzzed in the example's tests) |
| T5 | Focus leak through feedback | No scan feedback in the first build; any later scanner follows Apple's keyboard rule |

## Build plan (when the freeze allows)

1. `src/yazses/biosignal/bci_hid.py`: the pure parser and decoder, moved from the example and
   emitting real `BioEvent`s. Add `EventKind.SWITCH_PRESS`, and give `events_to_intents` a way
   to read the per-event label from `detail`. That change is a separate, reviewed contract edit.
2. `src/yazses/platform/<os>/bci_hid_reader.py` for `linux`, `macos` and `windows`,
   implementing `HidReportSource`, registered in `platform/factory.py`. Use OS APIs through the
   standard library or existing dependencies where possible. If a HID library is needed, make
   it an optional extra, lazily imported, with a `>=` floor at the latest stable release
   (AGENTS.md rules 3–4).
3. A `[biosignal.bci_hid]` (or `[bci_hid]`) config section with `enabled = False`. It holds the
   device path or identifier, the button → action map (empty by default except Apple's
   defaults for buttons 0–3), and `quality_floor`. Run `scripts/gen-docs.py`.
4. Wire the source through the existing biosignal runner, so that the governor, the ledger and
   the global pause apply. A default daemon must still load none of its code
   (`tests/test_biosignal_default_stays_out.py`).
5. An egress row: the reader modules go under `LOCAL_BOUND` in `tests/test_egress_inventory.py`
   with a reason ("reads a HID device the user named; no socket"), plus a test that their
   source imports no network root.
6. Docs: `docs/features.md` (generated), the configuration reference, `CHANGELOG.md`.

Size: M–L **[O]**.

### Requirements on any future product wiring

A reviewer should reject the build PR if any of these is missing:

- off by default;
- no network primitive;
- labels through the grammar only, never through the injector directly;
- never Enter by default;
- first report is a baseline;
- the quality floor refuses silently and is counted;
- the governor and the global pause apply unchanged;
- no `sys.platform` branching;
- tests built from synthetic bytes, including F2 detection where it can be simulated;
- no device or user data uploaded to any tool (AGENTS.md account-safety section).

## Egress statement

The example adds no code that sends, and no module under `src/yazses/`. ADR-019's inventory
and its count of paths that can transmit what the user said (two) are unchanged. A HID device
is not a network, and a future reader would be a `LOCAL_BOUND` row, as the BLE EMG backend is.

## AGENTS.md rule checklist

| # | Rule | Status |
|---|---|---|
| 1 | Nothing leaves the machine | Not engaged: nothing sends |
| 2 | Off by default | N/A to the example; required of the build |
| 3 | Heavy dependencies optional and lazy | None added |
| 4 | Latest stable with a `>=` floor | None added |
| 5 | Pure logic pure | The parser is stdlib-only and separate from any reader |
| 6 | Platform code behind Protocols | `HidReportSource`; per-OS readers deferred |
| 7 | Tests with the change | `tests/test_example_bci_hid_switch.py` |
| 8 | No AI authorship credit | Observed |
| 9 | A guard is judged on how rarely it fires | The quality floor holds on the device's own number only, and is silent |
| 10 | Cite the landing page | Apple, Microsoft and kernel documentation pages; no file links |
| 11 | Private tiers stay private | Nothing referenced |

## Unknown until a device exists

1. F1–F3 on each OS: user-space access, OS double-handling of the nested button and pointer
   collections, and whether the bytes arrive intact.
2. Which button a real device sends for ToggleDictation, and whether the device lets the user
   choose.
3. How often signal-quality reports arrive, and whether "neural activity strength" tracks the
   reliability of a press.
4. Whether any shipping device runs on a desktop at all, or pairs only with an Apple host.
5. Whether any person other than the maintainer wants this.

## Exit and kill criteria

**Mark this ADR Rejected, and remove the example, if any of these happens:**

- F1 or F2 holds on all three OSes;
- 180 days pass with no device available to anyone willing to measure, and no non-contributor
  request;
- the maintainer records a no-go.

**Re-open for the build only if all of these hold:**

- a person other than the maintainer reports a need;
- H1 has passed on at least one OS with a named device;
- the maintainer grants a named freeze exception in the style of the 2026-11-01 amendment.

## Decision requested

Choose one:

1. **Accept as a research record (recommended).** The example stays, and no implementation is
   authorised.
2. **Grant a named freeze exception** for the build. Not recommended: there is no device and
   no demand.
3. **Reject.** Remove the example and keep this file as Rejected.

**Verification status:** documentation and source reading only. Apple's reference page was
read in full on 2026-11-20, and the report layout above is taken from it. The newsroom post,
the kernel hidraw page and the Microsoft Learn page were read on the same day. No device, OS
HID stack or capture was involved.
