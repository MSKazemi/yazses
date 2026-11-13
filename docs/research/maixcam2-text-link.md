---
title: "MaixCAM2 text link (experimental, research only)"
description: A research note on sending text recognised on a Sipeed MaixCAM2 board to a desktop over a wired serial link. Not part of YazSes, not supported, nothing is typed. What is verified and what is not.
---

# MaixCAM2 text link: experimental, research only

!!! warning "Experimental, research only, not part of YazSes"

    **YazSes does not include this, does not ship it, and does not support it.**
    There is no setting, no command and no install option for it. Nothing on this
    page has been tried on a real board: the project does not own one. It is a
    research note and a set of reference files, nothing more.

*Written 2026-11-13. Part of the [research series](index.md).*

## What it would do

A [Sipeed MaixCAM2](https://wiki.sipeed.com/maixpy/doc/en/mllm/asr_whisper.html) is a small
board that can run a speech-recognition model on the board itself. The idea being
studied is whether such a board could send the **text it recognised**, or a simple
trigger, to a computer running YazSes over a wired serial connection. The speech
recognition would happen on the board; the computer would receive plain text.

The files that exist are a written description of the message format, a reference
reader that prints accepted text, a simulated board, an untested board-side sender,
and tests. The reader prints only **text** messages; it counts and drops trigger and
ping messages and never acts on them. Everything except the board-side sender runs on
any computer with no board attached, using made-up test data.

## The example never types anything

This is a deliberate safety stance, not a missing feature. The reference reader:

- only **reads** and **prints**; it does not type into any window,
- does not use the YazSes typing code,
- opens no network connection,
- refuses a message that is too long (including after normalisation), damaged, not valid
  UTF-8, that contains control, text-direction or invisible characters, or that has no
  visible content,
- counts gaps and exact repeats in the message numbering and drops nothing: it cannot tell
  a resent message from a repeated sentence, so protection against replayed messages is out
  of scope. Look-alike letters from mixed scripts are not handled either; anything that
  types such text needs its own check.

If this idea were ever added to YazSes itself, text from a board would have to go
through the same safety checks as dictated text, stay off by default, and be
reviewable before it is typed. None of that exists today.

## What is verified and what is not

| Statement | Status |
|---|---|
| The MaixCAM2 documentation lists Whisper `base`, for Chinese and English, needing 1 GB of memory | Verified, from the [vendor page](https://wiki.sipeed.com/maixpy/doc/en/mllm/asr_whisper.html), 2026-11-13 |
| The vendor says a serial link is feasible, and that the board's USB port is **not** a serial connection | Vendor statement by email, November 2026. Not tested |
| The model must be downloaded first | Verified, from the same page |
| The board's first setup needs internet access (to activate the device, install the runtime and connect development tools) | Verified, from the [MaixCAM2 README](https://github.com/sipeed/MaixPy/blob/main/docs/doc/en/README_MaixCAM2.md), 2026-11-13. So "offline" could at most mean offline **after** a one-time online setup |
| Whether recognition itself works with the board's network turned off, and whether anything is fetched later | **Not measured, not known.** The vendor says Whisper runs locally but did not separate setup, activation and download from recognition |
| The board's USB cable shows up on the computer as a USB **network** adapter, not a serial port | Verified, same README |
| Speed, accuracy, wiring behaviour, how well it works in practice | **Not measured.** No board has been used |
| Whether anyone wants this | Open question; see [research issue #878](https://github.com/MSKazemi/yazses/issues/878) |

Please do not describe this as "offline", "working" or "supported" anywhere until
the unknown rows above have been measured on a named board.

## What you would need to wire it

The board's USB port does **not** give your computer a serial port: it appears as a
USB *network* adapter. The vendor says a **USB-to-UART adapter** has to be connected
to the board's UART pins. The USB-network link is not used in this research, because
it would add a network listener on the computer. The board's console UART (UART0) is not meant to be used for this.
Check the voltage level of the pins against your adapter before connecting anything,
and follow the board's own manual. This project has not verified any pin map.

## Where to read more

- The reference files: [`examples/maixcam2-text-link/`](https://github.com/MSKazemi/yazses/tree/main/examples/maixcam2-text-link)
  and the message format in
  [`design/specs/textlink-wire-protocol.md`](https://github.com/MSKazemi/yazses/blob/main/design/specs/textlink-wire-protocol.md)
  (a draft, not yet verified on a board).
- The decision record, with the threat analysis, the unknowns and the conditions
  under which this idea would be dropped:
  [ADR-v2-156](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-156-maixcam2-text-link.md)
  (status: Proposed).
- Why a proposal like this stops at research for now:
  [how a research idea earns implementation](../roadmap.md#how-a-research-idea-earns-implementation).

If you own a MaixCAM2 and would like to run the measurements, comment on
[research issue #878](https://github.com/MSKazemi/yazses/issues/878). Please use synthetic or non-personal speech for anything you share.
