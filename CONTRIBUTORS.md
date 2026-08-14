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

## Contributors
- [@4nmus](https://github.com/4nmus) — Russian README translation, the project's first in
  Cyrillic script
- [@AshSgDe29071999](https://github.com/AshSgDe29071999)
- [@HeaTTap](https://github.com/HeaTTap)
- [@jackie-cqz](https://github.com/jackie-cqz)
- [@lntutor](https://github.com/lntutor)
- [@Maqbool61](https://github.com/Maqbool61)
- [@Mr-Neutr0n](https://github.com/Mr-Neutr0n) — the VS Code app profile
  ([#43](https://github.com/MSKazemi/yazses/issues/43)), the project's first Electron editor
  and the one most people asked for
- [@Parinitha-26](https://github.com/Parinitha-26)
- [@Prithvi4904](https://github.com/Prithvi4904) — first README translation (Hindi), and the
  language switcher that makes every later translation reachable
- [@slegarraga](https://github.com/slegarraga)
- [@waterlemonnn](https://github.com/MSKazemi/yazses/commits?author=waterlemonnn)

<!-- New contributors: added on merge, alphabetical. Want to be here? See CONTRIBUTING.md and grab a
     good first issue: https://github.com/MSKazemi/yazses/labels/good%20first%20issue -->

---

*Want to join this list? It's easier than you think — pick a
[good first issue](https://github.com/MSKazemi/yazses/labels/good%20first%20issue), open a PR, and
we'll help you through it. We review fast.*

*No code? Read an [open ADR](https://github.com/MSKazemi/yazses/tree/main/docs/mobile/adr) and tell
us what is wrong with it. That path is on this page too, and it has already changed the
architecture once.*
