---
title: Persian injection matrix — does typed Persian arrive code point for code point
description: How to check that YazSes delivers Persian, ZWNJ, mixed Persian-English, digits, paths, multiline text and emoji unchanged into a real application on Linux, macOS and Windows, and how to record the result as release evidence.
---

# Persian injection matrix

This is the procedure and the results table for
[#517](https://github.com/MSKazemi/yazses/issues/517) (FA-08 in the
[Persian language support plan](https://github.com/MSKazemi/yazses/blob/main/design/specs/persian-language-support-plan.md)).
It asks one narrow question: **when a backend types a Persian string, does the receiving
application get exactly those code points?** It does not test speech recognition, and it does
not test whether YazSes produced the right words. The strings are fixed before anything is typed.

!!! warning "Status: the harness exists, the matrix has not been run"

    The harness, the fixtures, the result format and the comparator are built and unit-tested
    (`tests/test_injectmatrix.py`). **Windows has been run** (2026-10-22, Windows 11 22H2, both
    backends): all 19 fixtures arrived code point for code point, in the Tk receiver only, with
    the visual check still pending. The result files are in
    `scripts/injectmatrix/results/2.43.2/`. Every Linux and macOS cell is still **UNVERIFIED**.
    That is the part a contributor can do, and it can be split by OS.

## Two different bugs, two different fields

A Persian string can fail in two unrelated ways, and they are filed separately:

| Kind | What it means | How it is judged | Where it goes |
|---|---|---|---|
| **Unicode corruption** | The application received different code points: a ZWNJ dropped, Arabic `ي` in place of Persian `ی`, an emoji split into two halves, a newline turned into CRLF | Automatically. The pass condition is code-point equality, nothing weaker | `codepoint_verdict` in the result; one issue per backend and defect |
| **Visual layout** | The code points are right, but the text is drawn wrongly: words in left-to-right order, a parenthesis not mirrored, Latin text in the wrong place | By a person looking at the window | `visual_check` in the result; a separate bidi-layout issue |

Text can look perfect and be corrupt (`ی` and `ي` are drawn the same way in most fonts), and it
can be byte-exact and look wrong. That is why neither check stands in for the other.

## What is typed

The fixture set is `scripts/injectmatrix/fixtures.json` — 19 strings, version 1. Each one is
either copied from a case in `contract/vectors/` (and a test fails if the two drift apart) or
written for this harness and marked `synthetic`. **No fixture is anything a person dictated**,
so a result file never contains private speech. List them with:

```sh
python scripts/injectmatrix/injectmatrix.py fixtures
```

They cover every class the issue names: plain Persian, mixed Persian and English, ZWNJ (inside
words, doubled, and at both ends of the burst), URLs, email addresses and POSIX and Windows paths,
Persian, Arabic-Indic and ASCII digits, Persian punctuation and guillemets, multiline text, and
emoji including a ZWJ sequence, a variation selector and a skin-tone modifier. There is also an
ASCII control string (`en-control`): if that one fails, the harness or the window focus is wrong,
not the Unicode handling.

## Running it

You need YazSes installed and a Python 3.11 or newer with Tk. The harness uses the standard
library only. On Debian and Ubuntu, Tk is the `python3-tk` package; the python.org installers for
macOS and Windows include it.

The run uses two terminals and one window. The **receiver** is a plain Tk text box that records
what arrives as code points. The **driver** types every fixture through `yazses inject`, which uses
the backend configured in `[injection] backend`, the same one dictation uses.

**1. Pick the backend.** On Linux, `yazses inject-backend` lists what is available here and
`yazses inject-backend clipboard` (or `xdotool`, `ydotool`, `wtype`, `unicode`) pins one. On
Windows set `[injection] backend = "clipboard"` in `config.toml` for the clipboard row and
`"auto"` for the native one. Put it back to `auto` when you are done.

**2. Start the receiver** in the first terminal:

```sh
python scripts/injectmatrix/injectmatrix.py receive --out captures.jsonl
```

Before it shows anything, the receiver inserts every fixture into its own text box directly and
reads it back. A Tk older than 9.0 can fail that for emoji, with no typing involved; those cases
are then reported as `RECEIVER_LIMIT` rather than blamed on the backend. The status line names any
fixture that failed this self-test.

**3. Start the driver** in the second terminal, then click into the receiver's text box within the
first eight seconds:

```sh
python scripts/injectmatrix/injectmatrix.py drive --out timeline.jsonl
```

If YazSes is not on `PATH` as `yazses`, pass the command, for example
`--yazses "uv run yazses"`. The driver waits seven seconds between fixtures so the receiver can
tell them apart, and it records which backend `yazses inject` reported. Do not type in the
receiver while it runs. When the driver finishes, **wait until the receiver has stopped changing
before you close it.** Tk 8.6 lays a growing block of Persian out slowly: on the Windows run the
929-character `fa-long-paragraph` took about 16 seconds to appear after it was typed, and closing
the window sooner records it as `NOTHING`, which reads as a backend failure but isn't one.

**4. Assemble the result:**

```sh
python scripts/injectmatrix/injectmatrix.py assemble \
    --timeline timeline.jsonl --captures captures.jsonl \
    --out linux-x11-xdotool.json --backend-version "$(xdotool --version)"
```

The OS, the OS version, the Linux session type, the YazSes version and the backend are filled in
for you; `--backend-version`, `--target-app` and the other flags override or add to them. The
result is checked as it is written, and the command exits non-zero if it is incomplete: a result
that does not name the OS, the backend and the YazSes version is rejected.

**5. Do the visual check.** For each case, look at how the receiver drew the text and record it:

```sh
python scripts/injectmatrix/injectmatrix.py visual linux-x11-xdotool.json \
    --case fa-punctuation-quotes --status pass
python scripts/injectmatrix/injectmatrix.py visual linux-x11-xdotool.json \
    --case fa-multiline --status fail --notes "second line drawn left to right"
```

**6. Check and render:**

```sh
python scripts/injectmatrix/injectmatrix.py validate linux-x11-xdotool.json
python scripts/injectmatrix/injectmatrix.py render *.json
```

`validate` recomputes every verdict from the stored code points and compares the expected side
with the shipped fixture, so a result cannot say `EXACT` for text that did not match. It accepts
`RECEIVER_LIMIT` only for a fixture the receiver's self-test marked as one it cannot hold, so a
backend failure cannot be relabelled as the receiver's. `render` prints a row for the table below,
then the code-point failures and the visual failures as two separate lists, ready to file as two
kinds of issue. A `RECEIVER_LIMIT` case is neither: its cell says "not tested" and names the
fixture, and it is listed last, under receiver limits, as nothing to file against the backend.

### Another target application

The Tk box is one application. A backend can work there and fail in a browser, an editor or a
terminal. For any other target, type a fixture into it (with `yazses inject -d 5 "<text>"`, or
`yazses inject -d 5 "$(python scripts/injectmatrix/injectmatrix.py text fa-zwnj)"` in a POSIX
shell), save what arrived as a UTF-8 file, and compare that file:

```sh
python scripts/injectmatrix/injectmatrix.py compare --fixture fa-zwnj \
    --received received.txt --out linux-wayland-ydotool-gedit.json \
    --backend ydotool --yazses-version "$(yazses --version)" --target-app gedit
```

Many editors add a newline when they save. `--strip-final-newline` removes exactly one and records
that it did, rather than hiding it.

On Linux X11, `scripts/appprobe/probe-gui.sh` already drives real applications in a container and
now keeps the untouched clipboard contents in `<label>.received.txt`; set `PROBE_TEXT` from the
`text` command and compare that file. That route types with `xdotool` directly rather than through
`yazses inject`, and a container is not hardware, so record it as **CI only** in the terms of the
[evidence standard](validation.md).

## Per-platform notes

| Platform | Rows to fill | Notes |
|---|---|---|
| Linux X11 | `xdotool`, `unicode`, `clipboard` | The Tk receiver is a native X11 client here. |
| Linux Wayland | `ydotool`, `wtype`, `portal`, `clipboard` as available | Tk runs under XWayland, so the Tk receiver tests the XWayland path. Repeat at least the ZWNJ and emoji fixtures in a native Wayland application with `compare`. `wtype` is a no-op on GNOME and KDE (see `yazses inject-backend`). |
| macOS | native (CGEvent) | The terminal that runs the driver needs Accessibility permission. **The clipboard row is blocked**: when this page was written (2026-10-21) the source has a clipboard injector for Linux and Windows but none for macOS, so there is no macOS clipboard fallback to test. |
| Windows | native (`SendInput`), `clipboard` | Results depend on the receiving application: an ANSI window turns characters it cannot represent into `?` (see *Windows: one app gets `????`* in [troubleshooting](../troubleshooting.md)), so test more than one application. `yazses inject -d 5 --diagnose "test"` reports whether the window you type into is an ANSI window. |

## Storing results as release evidence

Commit result files as
`scripts/injectmatrix/results/<yazses-version>/<os>-<session>-<backend>[-<app>].json`, for
example `results/2.43.2/linux-x11-xdotool.json`. Each file names the fixture-set version and a hash
of its texts, the OS and version, the session, the backend and its version, the YazSes version and
the receiving application, so the run can be repeated exactly. The format is
`scripts/injectmatrix/result.schema.json`. A result is evidence for the YazSes version it names
only; a later release does not inherit it.

## Results

Replace a row with the output of `render` when you have a result, and link the issue for every
failure. Cells use the words of the [evidence standard](validation.md).

| OS | Session | Backend | YazSes | Target | persian | mixed | zwnj | url-path | digits | punctuation | multiline | emoji | Visual |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Linux | x11 | xdotool | — | — | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| Linux | x11 | unicode | — | — | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| Linux | x11 | clipboard | — | — | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| Linux | wayland | ydotool | — | — | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| Linux | wayland | wtype | — | — | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| Linux | wayland | clipboard | — | — | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| macOS | none | native | — | — | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED |
| macOS | none | clipboard | — | — | Blocked | Blocked | Blocked | Blocked | Blocked | Blocked | Blocked | Blocked | Blocked |
| Windows 11 10.0.22621 | none | WindowsInjector | yazses 2.43.2+main.e224b67e (source checkout) | Tk text box (injectmatrix receiver) | EXACT | EXACT | EXACT | EXACT | EXACT | EXACT | EXACT | EXACT | pending |
| Windows 11 10.0.22621 | none | WindowsClipboardInjector | yazses 2.43.2+main.e224b67e (source checkout) | Tk text box (injectmatrix receiver) | EXACT | EXACT | EXACT | EXACT | EXACT | EXACT | EXACT | EXACT | pending |
