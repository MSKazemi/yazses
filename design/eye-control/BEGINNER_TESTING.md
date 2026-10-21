# Beginner / no-code eye-control testing

You can help this programme **without writing code**.

A useful contribution can be one short test on one computer. You do not need to understand gaze
algorithms, MediaPipe, Python, ADRs or research statistics.

## Words used in this guide

- **Issue** — a task page on GitHub. You need a free GitHub account to comment on one or to open a
  new one.
- **Label** — a coloured tag shown on the issue page, for example `help wanted`.
- **READY / PLANNED** — the first lines of an issue say which one it is. READY means you can start now.
  PLANNED means the software it tests does not exist yet, so there is nothing to run.
- **Slot** — one reserved place for one test on one kind of computer. "Slot A" and "slot B" are two
  slots for the same kind of computer.
- **Pack** — a small named test (T0 to T7, listed below). One issue names exactly one pack.
- **Claim an issue** — write a short comment on it saying you are taking it.

## Is the test available yet?

This guide lists both **future PLANNED slots** and **currently READY slots**.

Before claiming an issue:
- open it (each number below is a link);
- if it has the `help wanted` label and a **READY** banner at the top, you may start;
- if it begins with **PLANNED — not yet available**, do not claim it or invent manual steps;
- `good first issue` is added only when the task is both READY and beginner-safe.

Hardware slots [#428](https://github.com/MSKazemi/yazses/issues/428) to
[#440](https://github.com/MSKazemi/yazses/issues/440) are intentionally visible before they are ready so the project can show the
future validation matrix. They become real contributor tasks only after their evaluator/runtime
blockers merge.

Every READY slot is also listed in the project's [task finder](https://mskazemi.com/yazses/contribute/find.html):
choose "specific hardware or an OS" and the "measurement" kind. A slot that is not listed there is not READY yet.

If no hardware slot is READY, choose another current contributor task rather than forcing the test.
[Open issues labelled `good first issue`](https://github.com/MSKazemi/yazses/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
is a good place to look.

## Pick one task

### I have Windows 11

Choose one unclaimed issue:
- [#428](https://github.com/MSKazemi/yazses/issues/428) — Windows A
- [#429](https://github.com/MSKazemi/yazses/issues/429) — Windows B, intended as an independent second computer/person

### I have a Mac with Apple Silicon

- [#430](https://github.com/MSKazemi/yazses/issues/430) — macOS A
- [#431](https://github.com/MSKazemi/yazses/issues/431) — macOS B

### I use GNOME Wayland

- [#432](https://github.com/MSKazemi/yazses/issues/432) — GNOME A
- [#433](https://github.com/MSKazemi/yazses/issues/433) — GNOME B

### I use KDE Wayland

- [#434](https://github.com/MSKazemi/yazses/issues/434) — KDE A
- [#438](https://github.com/MSKazemi/yazses/issues/438) — KDE B

### I use Linux X11

- [#435](https://github.com/MSKazemi/yazses/issues/435) — X11 A
- [#439](https://github.com/MSKazemi/yazses/issues/439) — X11 B

### I have two monitors or non-100% scaling

- [#436](https://github.com/MSKazemi/yazses/issues/436) — topology A
- [#440](https://github.com/MSKazemi/yazses/issues/440) — topology B

### I can repeat the same test three times on different sessions

- [#437](https://github.com/MSKazemi/yazses/issues/437) — test/retest stability. This one takes three
  separate sittings, each about 15–20 minutes, recorded separately.

### I do not have special hardware but want to help

- [#427](https://github.com/MSKazemi/yazses/issues/427) — read the tester/data-sharing wording and
  report anything confusing.

### How do I tell what I have?

- **Apple Silicon Mac:** Apple menu > About This Mac. The "Chip" line says "Apple M1", "M2" or similar.
  An "Intel" line means this task is not for your Mac.
- **Windows scaling:** Settings > System > Display. The "Scale" box shows the percentage.
- **Linux session (Wayland or X11):** open a terminal and type `echo $XDG_SESSION_TYPE`. It normally
  prints `wayland` or `x11`. If it prints nothing, ask in the issue before choosing.
- **Linux desktop (GNOME or KDE):** type `echo $XDG_CURRENT_DESKTOP`. It normally prints `GNOME` or `KDE`.

If you cannot tell which row fits you, say so in a comment on the issue instead of guessing.

## What does "A/B" mean?

It does **not** mean one person should do both.

A = first independent report.  
B = preferably another person on another physical computer.

That helps us tell the difference between:
- "worked on one developer's laptop";
- "works repeatedly across the platform."

## How long?

A normal no-code slot should be about **15–20 minutes** once its required runtime/evaluator is
available.

If the issue is blocked because the feature is not implemented yet, do not invent manual steps.
Wait until its blocker is merged.

## What you run

Use the project-generated/local test, not private desktop content.

The issue will name one small pack from [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md#test-packs), such
as:

- T0 camera start/stop;
- T1 four-target gaze (does the computer pick the box you looked at?);
- T2 large-target Head-Pointer (moving the mouse pointer with your head);
- T3 face switch (a deliberate facial expression acting like a button);
- T4 pause/recovery;
- T5 multi-monitor;
- T6 semantic grounding (turning a rough look into an exact on-screen item);
- T7 hands-free workflow.

One issue should normally mean one pack on one environment. In the matrix, read **only the section for
your pack** and skip the rest; the other sections are for the maintainers.

The issue gives you what to run. **Run only what the issue names.** If it gives no command, or asks for
something you do not understand, stop and ask in the issue. Do not guess, and do not run anything that
opens your camera or moves your pointer until the issue says it is READY.

## Where to report

When the slot is READY, report your result with the **"No-code eye-control test"** form:
Issues > New issue > "No-code eye-control test". The form asks for the slot's issue number (for example
`#428`), and the slot must be READY. A report posted through the form is community engineering QA, not
research.

## What you share

Required engineering information:
- YazSes version/commit (in a terminal, type `yazses --version`; it prints something like
  `yazses 2.42.0`);
- operating system/version/session;
- broad computer model;
- camera model/category;
- monitor resolution/scaling/topology;
- PASS / PARTIAL / FAIL / BLOCKED (see below);
- generated counts/metrics;
- a short description of what failed and whether recovery worked.

The four results mean:
- **PASS** — the scripted steps worked;
- **PARTIAL** — some steps worked;
- **FAIL** — a problem you can make happen again;
- **BLOCKED** — you could not start because of a missing dependency, permission or piece of hardware.

Optional when relevant:
- approximate viewing distance;
- lighting category;
- glasses yes/no/prefer-not-to-say.

Copy only the numbers the form asks for. Do **not** paste a whole log file or command output: it can
contain your user name, your computer's name and file paths.

## Never share in a public issue

Do not post:
- face photo/video;
- webcam frames;
- raw eye/face images;
- private dictated text/audio;
- private screenshots;
- diagnosis or medical records;
- email/phone/address;
- hostname;
- device serial number;
- passwords/tokens.

GitHub issues are public and may be mirrored. The safest sensitive datum is the one we never ask you
to upload.

## What if my result fails?

**Post it** (in the form above).

A FAIL, PARTIAL or BLOCKED report is a successful contribution if the instructions were followed.

We need to know:
- camera permission failed;
- pointer portal was denied;
- feature broke at 150% scaling;
- gaze chose the wrong target;
- face switch fired while speaking;
- recovery did not work.

Do not retry until a failure disappears and then report only the successful run.

## Am I joining a research study?

No.

The normal public test issues are **community engineering QA**.

If you select "I am willing to be contacted about research", that only means a research team may
contact you later. It does not convert your GitHub test into research consent.

A publication-quality human study has its own:
- protocol;
- ethics/review determination;
- participant information;
- consent;
- random participant IDs;
- data-retention/release rules.

See [DATA_SHARING.md](DATA_SHARING.md).

## Do I become a paper author?

Testing, research participation and paper authorship are separate things.

Contributors should receive project credit/acknowledgement appropriate to their contribution, but a
hardware test does not automatically create paper authorship and research participation does not
automatically create authorship.

## Simple completion checklist

A no-code issue can be closed when:

- [ ] correct YazSes version was used;
- [ ] the named small test pack was followed;
- [ ] OS/computer/camera/display were described;
- [ ] PASS/PARTIAL/FAIL/BLOCKED was reported;
- [ ] generated metrics were included;
- [ ] no sensitive/raw face/private content was posted.

That's enough. You do not need to fix the problem you discover.
