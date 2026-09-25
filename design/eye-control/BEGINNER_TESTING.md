# Beginner / no-code eye-control testing

You can help this programme **without writing code**.

A useful contribution can be one short test on one computer. You do not need to understand gaze
algorithms, MediaPipe, Python, ADRs or research statistics.

## Is the test available yet?

The guide lists both **future PLANNED slots** and **currently READY slots**.

Before claiming an issue:
- open it;
- if it has the `help wanted` label and a **READY** banner, you may start;
- if it begins with **PLANNED — not yet available**, do not claim it or invent manual steps;
- `good first issue` is added only when the task is both READY and beginner-safe.

Hardware slots #428–#440 are intentionally visible before they are ready so the project can show the
future validation matrix. They become real contributor tasks only after their evaluator/runtime
blockers merge.

If no hardware slot is READY, choose another current contributor task rather than forcing the test.

## Pick one task

### I have Windows 11

Choose one unclaimed issue:
- #428 — Windows A
- #429 — Windows B, intended as an independent second computer/person

### I have a Mac with Apple Silicon

- #430 — macOS A
- #431 — macOS B

### I use GNOME Wayland

- #432 — GNOME A
- #433 — GNOME B

### I use KDE Wayland

- #434 — KDE A
- #438 — KDE B

### I use Linux X11

- #435 — X11 A
- #439 — X11 B

### I have two monitors or non-100% scaling

- #436 — topology A
- #440 — topology B

### I can repeat the same test three times on different sessions

- #437 — test/retest stability

### I do not have special hardware but want to help

- #427 — read the tester/data-sharing wording and report anything confusing.

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

The issue will name one small pack from [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md), such as:

- T0 camera start/stop;
- T1 four-target gaze;
- T2 large-target Head-Pointer;
- T3 face switch;
- T4 pause/recovery;
- T5 multi-monitor;
- T6 semantic grounding;
- T7 hands-free workflow.

One issue should normally mean one pack on one environment.

## What you share

Required engineering information:
- YazSes version/commit;
- operating system/version/session;
- broad computer model;
- camera model/category;
- monitor resolution/scaling/topology;
- PASS / PARTIAL / FAIL / BLOCKED;
- generated counts/metrics;
- a short description of what failed and whether recovery worked.

Optional when relevant:
- approximate viewing distance;
- lighting category;
- glasses yes/no/prefer-not-to-say.

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

**Post it.**

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
