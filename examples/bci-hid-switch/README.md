# BCI HID switch parser (research example)

A device-free reference for one question: could a brain-computer interface that speaks
Apple's BCI HID protocol (usage page `0x60`, intent decoded on the device) act as a YazSes
switch on the desktops Apple's support leaves out (macOS, Linux and Windows)?

This folder is a **pure parser and decoder for synthetic report bytes**. It is a research
artifact, not a YazSes feature. Nothing under `src/yazses/` imports it. It adds no
dependency, config key or CLI command, never opens a device and never types.
[ADR-030](../../design/adr/adr-030-agent-era-direction.md) freezes new device families,
which is why it lives here. The decision record is
[ADR-v2-157](../../design/adr/adr-v2-157-bci-hid-switch-consumer.md).

## What is verified, and what is not

| Claim | Status |
|---|---|
| The report lengths match Apple's example descriptor | Verified by `tests/test_example_bci_hid_switch.py`, which walks Apple's descriptor (copied byte for byte, checked against a second hex copy) and derives every length from it |
| Buttons, signal quality, pointer (including the `-128` absent-axis sentinel and the 1D/2D/3D shapes), item selection and the host's scan-info report parse as Apple's reference describes them | Verified in software, on synthetic bytes |
| Malformed input never raises out of the decoder | Verified with property-based fuzzing (hypothesis) |
| The YazSes rules: first report is a baseline, only press edges act, ToggleDictation flips a mode, a low signal-quality report refuses the press, a pause closes the mode | Verified in software |
| Default labels are commands the existing grammar already parses (`press tab`, `press escape`) | Verified against `yazses.commands.grammar.classify` |
| Any real BCI device sends these bytes | **Not verified.** No device exists in this repository |
| Linux, macOS or Windows let a user-space program read a usage-page-0x60 device, and the OS does not also act on its buttons or pointer | **Not verified.** See ADR-v2-157, "Unknown until a device exists" |

## Files

| File | Role |
|---|---|
| `bcihid.py` | Constants, strict report parsers, encoders for synthetic bytes, a short-item descriptor walker, `SwitchDecoder`, the `HidReportSource` Protocol and an in-memory `ReplaySource`. Standard library only |

## Run it

```sh
# each argument is one report, report-ID byte first, in hex
python examples/bci-hid-switch/bcihid.py 0200000000 0202000000
uv run python -m pytest tests/test_example_bci_hid_switch.py -v
```

The first command prints one `switch_press` for button 1 ("next", labelled `press tab`).
The first button report is only the baseline.

## Event mapping (design choice of ADR-v2-157)

| Apple action | Event | YazSes label by default |
|---|---|---|
| `ToggleDictation` (no default button; the user assigns one) | `squeeze_on` / `squeeze_off`, alternately on each press | the existing dictation mode |
| `Next` / `MoveToNextItem` (button 1 by default) | `switch_press` | `press tab` |
| `Escape` | `switch_press` | `press escape` |
| `Select` (button 0), `Previous` (button 2), menu (button 3), everything else | none | unmapped: inert |

`squeeze_on` and `squeeze_off` are existing `EventKind` values. `switch_press` is the one
kind the ADR proposes adding at build time; it does not exist in the product.
