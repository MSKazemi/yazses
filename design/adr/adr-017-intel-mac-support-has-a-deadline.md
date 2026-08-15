# ADR-017 — Intel Mac support: build it while it is free, and put the end date in writing

**Status:** Accepted (2026-08-15)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** issue [#264](https://github.com/MSKazemi/yazses/issues/264) (the decision
this answers), [#216](https://github.com/MSKazemi/yazses/issues/216) (test on Intel),
[[adr-016-dependency-budget]], `docs/platform-support.md`

---

## Context

Issue #264 asks a binary question: **"do we pay for an Intel macOS runner, or declare Apple
silicon only?"** It is well evidenced on the technical side — the `.dmg` was decompressed on
Linux and every Mach-O header read (`{'arm64': 122}`, zero fat headers), so the artifact
really is arm64-only, and `universal2` really is unreachable because several runtime wheels
ship single-architecture binaries.

Both of its premises turned out to be wrong when checked against the world in August 2026.

### Premise 1: "it costs money rather than effort" — false

GitHub Actions is free for standard GitHub-hosted runners in **public repositories**, and
that is not a theoretical reading here: `test.yml` runs `macos-latest` on every push, and
`build-macos.yml` runs it on every tag. This repository has been consuming GitHub-hosted
macOS runner time continuously and #264 does not report a bill, because there is none.

An Intel leg costs **runner minutes, not money**. The decision was never a spend.

### Premise 2: "an Intel runner exists to be paid for" — no longer true either

The Intel image the issue implicitly assumes, `macos-13`, **began deprecation on 22 September
2025 and was fully retired on 4 December 2025**. Writing `runs-on: macos-13` today does not
buy an Intel build; it fails.

What exists instead is a migration label, **`macos-15-intel`**, and it has a published end of
life:

| Date | Event |
|---|---|
| 2025-12-04 | `macos-13` (the last "ordinary" Intel image) retired |
| now → **2027-08** | `macos-15-intel` available — the **last** x86_64 image on Actions |
| Fall 2027 | GitHub no longer supports x86_64 macOS on Actions at all |

## Decision

**Neither option in the issue. Build Intel now, on `macos-15-intel`, as an advisory matrix
leg — and document that Intel support ends in 2027 because GitHub ends it.**

1. **Add an Intel leg to `build-macos.yml`** using `macos-15-intel`, alongside the existing
   Apple-silicon build.
2. **Mark it advisory** (`continue-on-error`), exactly as `build-windows.yml` already treats
   its brand-new `windows-11-arm` leg. This repository's own rule is that *a brand-new
   cross-architecture build must not be able to fail a release the primary build completed
   fine*, and there is no reason for Intel to be the exception.
3. **Document it as ⏳, not ✅**, until it has produced a working installer. The arm64 snap
   gap is the standing lesson: a claim nothing has exercised reads exactly like a claim
   something has.
4. **Write the 2027 end date into `docs/platform-support.md`.** An Intel Mac owner deciding
   whether to adopt YazSes deserves to know the desktop bundle has a dated horizon, and that
   `pipx install yazses` — which works on Intel today, since `ctranslate2` publishes
   `macosx_11_0_x86_64` wheels — is the path that outlives it.

## Consequences

**Good.** The gap closes at zero cost, using a mechanism already proven in this repo. #216
("test YazSes on Intel") becomes answerable by a contributor with something to download.
The honest deadline is published rather than discovered by a user in 2027.

**Accepted cost.** One more advisory build per tag, and a second `.dmg` to name, checksum
and list in the release notes. The naming must distinguish the two artifacts — the current
`YazSes-<version>.dmg` is architecture-silent, which is itself part of how the arm64-only
bundle went unnoticed.

**The unavoidable one.** This buys roughly two years. In Fall 2027 the Intel `.dmg` stops
being buildable on Actions and the row becomes ❌ unless someone self-hosts an Intel Mac.
That is the "declare Apple silicon only" outcome from #264 — it is simply **scheduled by
GitHub rather than chosen by us**, and the right response is to take the two years rather
than concede them early.

**What this does not decide.** Signing and notarisation are untouched; both bundles stay
unsigned until the code-signing decision lands separately.

## Alternatives considered

- **Declare Apple silicon only, now.** Rejected: it discards two years of free coverage and
  strands every Intel Mac still in service, on the strength of a cost that does not exist.
- **Pay for a third-party Intel runner.** Rejected: there is nothing to buy that
  `macos-15-intel` does not already give for free until 2027.
- **`universal2`.** Rejected on the evidence already in #264 — PyInstaller can only emit a
  fat binary when *every* bundled wheel is fat, and several are not.
- **Cross-compile x86_64 from an arm64 runner.** Rejected: PyInstaller does not cross-build,
  and `target_arch` cannot conjure an x86_64 slice out of arm64-only wheels.
