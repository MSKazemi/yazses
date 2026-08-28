# Contributors 💛

YazSes is built by its community. **Everyone who lands a merged PR is added here** — code, docs,
translations, a mic entry, a showcase, anything. Thank you for making it better.

**Code is not the only contribution that counts.** A design review that changes a decision before
it is built is worth more than most patches, and it leaves no diff to point at — so those are
credited too, in their own section below.

## Maintainer
- [@MSKazemi](https://github.com/MSKazemi) — creator & maintainer

## Design review & research

Reviewers whose analysis changed the design. No merged PR required — the contribution is the
argument, and the record of it is the decision it altered.

- [@YossiMH](https://github.com/YossiMH) — found that the cross-platform contract pinned
  implementation parity but not *meaning*, and that a golden contract generated from the code
  under test cannot detect a rule that erases a distinction ([#98](https://github.com/MSKazemi/yazses/issues/98)).
  Adopted as **ADR-MOB-008 §8** and shipped as `contract/semantic/`, which found five
  meaning-destroying bugs on its first run ([#146](https://github.com/MSKazemi/yazses/issues/146))
  while all 191 parity vectors were green. Also raised the agency-preserving uncertainty
  invariant for graded EMG activation ([#103](https://github.com/MSKazemi/yazses/issues/103)).

## Testing & field reports

Running an unproven build on your own machine and writing down exactly what happened.
This project had **three supported platforms and hardware for one of them**, so for a
long time the macOS and Windows builds were correct only in the sense that nobody had
disproved them. These reports are what turned that into evidence — and two of them
found defects that no amount of reading the code here would have surfaced.

- [@happytester-funbugs](https://github.com/happytester-funbugs) (Tanya Martin-McClellan) —
  the first person to take the macOS build all the way through, on an M2 running
  Tahoe: both `.dmg` routes and Homebrew, Gatekeeper, the permission panes, and
  `doctor` output at every step ([#182](https://github.com/MSKazemi/yazses/issues/182),
  [#241](https://github.com/MSKazemi/yazses/issues/241),
  [#6](https://github.com/MSKazemi/yazses/issues/6)). The report that mattered most was
  the one that looked like three separate bugs — Accessibility granted and enabled, the
  dictation key dead everywhere, and YazSes absent from the Microphone pane with no way
  to add it. It is one cause: a `CGEventTap` needs **Input Monitoring** as well as
  Accessibility on macOS 10.15+, and YazSes never asked for it, so nothing ever recorded
  and macOS never showed the microphone prompt that puts an app in that list. Reported
  carefully enough — with the state of each toggle, not just "it doesn't work" — that
  the cause was findable without a Mac.
- [@AtmanActive](https://github.com/AtmanActive) — the first bug report from a real user
  outside the project ([#310](https://github.com/MSKazemi/yazses/issues/310)): a crash on
  first run that turned out to be a firewall blocking the model download, i.e. the
  offline-first tool failing at the one moment it is not yet offline.
- [@slegarraga](https://github.com/slegarraga) (Sebastian Legarraga) — ran the Homebrew
  cask route end to end on an Apple M4, the route this project had marked "never
  executed", and found that Homebrew's new tap-trust gate makes the **documented
  one-liner fail for every new user** without `brew trust`
  ([#182](https://github.com/MSKazemi/yazses/issues/182)); also fixed the tap's
  deprecated `depends_on macos:` warning upstream. Notably declined to claim `doctor`
  output that could not be captured from a sandbox — a report that says where it stops
  is worth more than one that guesses.
- [@hoti-code](https://github.com/hoti-code) — ran the Homebrew cask on an M5 and reported
  every symptom precisely: no Accessibility, Input Monitoring or Microphone prompt, no
  menu-bar icon, a dead hotkey, and `doctor` unable to name its own version
  ([#318](https://github.com/MSKazemi/yazses/pull/318)). They read as the two macOS fixes
  having failed. They were not — the tap had been serving **2.18.2 since 2026-08-13**, so
  the build predated both. The report is what surfaced a distribution channel frozen for
  seventeen releases that no dashboard was reporting, because the drift watch compares
  against the previous release and a permanently-stale channel is its own baseline. A
  faithful list of symptoms was worth more here than a diagnosis would have been.

## Contributors
- [@4nmus](https://github.com/4nmus) — Russian README translation, the project's first in
  Cyrillic script
- [@AshSgDe29071999](https://github.com/AshSgDe29071999)
- [@HeaTTap](https://github.com/HeaTTap)
- [@jackie-cqz](https://github.com/jackie-cqz)
- [@jayavandhiniMK](https://github.com/jayavandhiniMK) (Jayavandhini M K) — Windows 11
  showcase entry ([#317](https://github.com/MSKazemi/yazses/pull/317))
- [@lntutor](https://github.com/lntutor)
- [@Maqbool61](https://github.com/Maqbool61)
- [@mercael91](https://github.com/mercael91) — went after the FreeBSD CI job nobody had looked
  at, which is how we learned the BSD backend had never once been executed
  ([#306](https://github.com/MSKazemi/yazses/issues/306)); and brought the Logseq app
  profile, the one that made the probe harness reach AppImage apps
  ([#309](https://github.com/MSKazemi/yazses/pull/309))
- [@Mr-Neutr0n](https://github.com/Mr-Neutr0n) — the VS Code app profile
  ([#43](https://github.com/MSKazemi/yazses/issues/43)), the project's first Electron editor
  and the one most people asked for
- [@Parinitha-26](https://github.com/Parinitha-26)
- [@Prithvi4904](https://github.com/Prithvi4904) — first README translation (Hindi), and the
  language switcher that makes every later translation reachable
- [@slegarraga](https://github.com/slegarraga) — see **Testing & field reports** above
- [@waterlemonnn](https://github.com/MSKazemi/yazses/commits?author=waterlemonnn)

<!-- New contributors: added on merge, alphabetical. Want to be here? See CONTRIBUTING.md and grab a
     good first issue: https://github.com/MSKazemi/yazses/labels/good%20first%20issue
     (CONTRIBUTING.md lives in .github/ — GitHub surfaces it from there.) -->

---

*Want to join this list? It's easier than you think — pick a
[good first issue](https://github.com/MSKazemi/yazses/labels/good%20first%20issue), open a PR, and
we'll help you through it. We review fast.*

*No code? Read an [open ADR](https://github.com/MSKazemi/yazses/tree/main/docs/mobile/adr) and tell
us what is wrong with it. That path is on this page too, and it has already changed the
architecture once.*
