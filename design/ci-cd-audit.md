# CI/CD audit

**Started:** 2026-08-24 · budget 3 passes.

* **Pass 1 — the workflow layer.** The 23 files in `.github/workflows/`.
* **Pass 2 — release provenance.** Attestations, checksums, and what a published
  artifact can be checked against.
* **Pass 3 — remaining.** The three build scripts in `scripts/`, the six package
  channels, SBOM and signing.

---

## Pass 1 — the workflow layer

### The question this audit asks

Not "is the YAML tidy" but: **what does each surface actually prove, by a command, today?**
Everything else is assertion. A pipeline is enterprise-grade when its claims are checkable,
not when it has more steps.

The sharpest form of that question turns out to be one the YAML cannot answer about itself:
*has this workflow ever run at all?* A file can be perfectly written, committed, reviewed,
and never once fire.

### Method

Two derivations, both re-runnable:

```bash
# 1. how often each workflow has actually run, and how it ended
gh api repos/MSKazemi/yazses/actions/workflows --jq '.workflows[] | "\(.name)\t\(.path)"'
# then per workflow: .../actions/workflows/<file>/runs?per_page=1 -> total_count

# 2. the trigger surface of every workflow, parsed rather than read
uv run python -c "import yaml; ..."   # see tests/test_release_workflow_triggers.py
```

Note for anyone re-running #2: in YAML 1.1 the key `on:` parses as the **boolean `True`**,
not the string `"on"`. A script that reads `doc["on"]` finds nothing and reports every
workflow as untriggered — a check that cannot parse its input reports compliance.

### Findings

#### F1 — `ppa.yml` has never run, and could not have. *(live defect, now marked)*

```
Launchpad PPA    active    runs=0    last=never
```

Zero runs in the repository's lifetime. The trigger is `tags: ["v0.*"]`, with the comment
*"Python v0.x only — v1.x handled by rust-release.yml"*. `rust-release.yml` was **deleted**
in `61025cc` when the Rust line was archived. So the trigger was scoped to a version line
that ended, its named successor no longer exists, and the Launchpad PPA has had **no
publisher at all** since v1.0.0.

Nothing failed. That is why it survived: a workflow that never fires produces no red mark,
no notification, and no log. It is invisible in exactly the way a broken one is not.

Impact is bounded — nothing in `README.md` or `docs/` advertises a PPA, so no user was
promised something that does not exist, and Launchpad credentials were never set up either
(`design/packaging/ppa-setup.md` is an unexecuted setup guide). Widening the glob would
convert silence into a *failing* job, which is why this pass marks it disabled with a
reason rather than enabling it. **Whether the PPA should exist at all is a decision, not a
fix.**

#### F2 — `release.yml` and `snap.yml` carried the same shape, one major ahead of the blade. *(fixed)*

```yaml
tags:
  - "v0.*"
  - "v1.*"  # Part 1 owns the 1.x line (Rust release workflow archived)
  - "v2.*"  # v2 Python line (cognitive layer)
```

An enumeration somebody has to remember to extend. On the day `v3.0.0` is tagged, PyPI and
the Snap Store would not publish — and **the tag would look successful, because no job would
run to fail**. That is strictly worse than v2.30.0's failure, which at least went red.

Both are now `tags: ["v*"]`. Jobs verified unchanged: `release.yml` still declares
`test → publish-pypi → build-deb → release-linux`, `snap.yml` still declares `snap`.

#### F3 — `flatpak.yml` cannot fire on the way this repository is actually developed. *(open)*

Triggers are `pull_request` (paths `packaging/flatpak/**`) and `workflow_dispatch` — there
is **no `push` trigger**. Maintainer work here lands directly on `main`, so a change to the
Flatpak manifest committed to `main` is never built.

This is not hypothetical. `5a9e3d4` on 2026-08-23 fixed the manifest that would have
installed **2.18.2** while the store listing advertised **2.29.0** — eleven releases apart —
and it touched `packaging/flatpak/python3-yazses.json`. The Flatpak workflow's last run was
**2026-08-13**, ten days earlier. The fix for the packaging defect was itself never
build-tested.

Left open deliberately: adding `push` here means running a full Flatpak SDK build on every
`main` commit that touches those paths, which is slow and may need `org.kde.Sdk` caching to
be worth it. That is a design choice, not a typo.

### Observations, not yet defects

| workflow | signal | reading |
|---|---|---|
| `benchmark.yml` | 1 run, `workflow_dispatch` only | a manual tool by design; expensive to run per-commit. Fine, but it proves nothing continuously. |
| `link-check.yml` | 1 run, `schedule` only | scheduled 2026-08-17; too young to judge. |
| `apt-repo.yml` | 17 success / 15 skipped / 8 failure | genuinely exercised. Healthy. |
| `android-test.yml` | 7 runs, last 2026-08-15 | path-filtered; consistent with no Android changes since. |

### What is now proven by a command

`tests/test_release_workflow_triggers.py` derives every tag-triggered workflow from the
YAML and asserts each still fires **for this major and the next**. The `offset=1` case is
the point: it fails *before* a major bump rather than after, when the cost is one edit
instead of a silent non-release.

A workflow that genuinely should not fire declares `RELEASE-TRIGGER-DISABLED: <reason>` in
its own text — the exemption sits beside the trigger it explains, so it cannot drift from
it the way a list inside the test would. A separate test requires that reason to be more
than a word, because a marker with nothing after it is a silencer.

Verified to bite, not merely to pass:

| mutation | expected | result |
|---|---|---|
| strip the marker from `ppa.yml` | both cases red | 2 failed |
| restore `release.yml` to `v2.*` | only the next-major case red | 1 failed |
| *(pre-fix state, as found)* | `ppa` today, all three for v3 | 2 failed |

### Still only asserted, after pass 1

* That any release workflow **does the right thing when it runs** — this pass proves only
  that it runs. Job-level correctness is pass 2/3 territory.
* That the six package channels install and launch. `T20` already records four frozen on
  credentials.
* Provenance, SBOM and signing: `checksums.yml` and the `.intoto.jsonl` attestations exist
  and ran on v2.30.0, but nothing in the repository *verifies* an attestation.

---

## Pass 2 — release provenance

**Date:** 2026-08-24 · **Scope:** attestations, published checksums, and what a released
artifact can actually be checked against.

### The gap pass 1 named

> Provenance, SBOM and signing: `checksums.yml` and the `.intoto.jsonl` attestations exist
> and ran on v2.30.0, but nothing in the repository *verifies* an attestation.

Measured: `gh attestation verify` occurs **once** in the whole repository, at
`.github/workflows/release.yml:181` — **inside a comment**. `codesign --verify` runs only
under `if: steps.sign.outputs.sign == 'true'`, and no signing certificate exists yet. So no
published artifact had ever been checked against its own provenance.

`tests/test_release_provenance_assets.py` is not that check, and does not claim to be: it
proves the *workflow* attaches a bundle. The distance between "the workflow has an attest
step" and "the artifact people download can be verified" is exactly where v2.19.0 failed —
the `.dmg` attest step globbed the workspace root instead of `dist/`, produced nothing, and
skipped the upload. That was caught only because the asset went missing too. Had it
attested nothing while still uploading, the release would have looked signed, scored well
on Scorecard, and failed for anyone who tried to verify it.

### F4 — provenance was never verified, and is now. *(closed)*

The check is by **digest**, never by download. Every release publishes `SHA256SUMS.txt`, and
GitHub serves attestations at `/repos/{owner}/{repo}/attestations/sha256:{digest}` — so a
full check costs a few API calls instead of ~370 MB of installers. That is what makes it
cheap enough to run on every release rather than once, by hand, after something goes wrong.

`scripts/verify-provenance.py`, run live during this pass:

```
$ python scripts/verify-provenance.py --tag v2.29.0
attested suffixes (derived from .github/workflows): ['.deb', '.dmg', '.exe']
  OK   YazSes-2.29.0-macos-arm64.dmg     1 attestation(s)
  OK   YazSes-2.29.0-macos-x86_64.dmg    1 attestation(s)
  OK   YazSes-2.29.0-windows-arm64.exe   1 attestation(s)
  OK   YazSes-2.29.0-windows-x64.exe     1 attestation(s)
  OK   yazses_2.29.0_amd64.deb           1 attestation(s)
  OK   yazses_2.29.0_arm64.deb           1 attestation(s)

all 6 attestable artifact(s) verified by digest
```

**The result is good news, and it is now evidence rather than belief:** every artifact of
the last complete release carries a real in-toto attestation, across all three channels. The
half-published v2.30.0 verifies too, for the two artifacts it did publish.

Which suffixes require an attestation is **derived from the workflows that do the
attesting** (`subject-path:` of each `actions/attest-build-provenance` step), not listed in
the script. A hand-written list is the defect it would be guarding against: add a channel,
forget the list, and the check reports success over an artifact nobody attested.

Wired into `release-complete.yml`, before the channel report — that step is *expected* to
fail until every channel publishes, so a check placed after it would never run.

### The failure mode this class of checker actually has

Not a wrong answer: a **vacuous** one. If the derived suffix set comes back empty, every
release passes, because nothing was required and so nothing was missing. The script fails
loudly on an empty derivation, and `tests/test_verify_provenance.py` exists mostly to make
that impossible — including a test that the empty case is *reachable*, so the guard is not
dead code.

Writing those tests found a real bug in the checker itself: `main()` called
`attested_suffixes()` and took the default argument, which Python binds at **definition**
time. The function could therefore never be pointed at another tree, the empty-derivation
guard was untestable, and the "offline" test made a live network call. Fixed by reading the
module global at call time — after which the suite went from 3.53 s to 0.24 s, which is the
measurable sign it had stopped touching the network.

### Observations from this pass

* **`checksums.yml` behaved correctly on a partial release.** It logged `no asset matched
  *.deb` and `*.dmg`, checksummed the four Windows assets that did exist, and attached
  `SHA256SUMS.txt`. A job that skips absent inputs and still publishes what it has is the
  right shape.
* **The incomplete-release safety net fired.** `release-complete.yml` demoted v2.30.0 to
  pre-release, so `gh release list` still shows **v2.29.0 as Latest**. The half-published
  release is not being advertised to anyone.
* `SHA256SUMS.txt` also checksums the `.intoto.jsonl` bundles. Harmless, slightly odd.

### Still only asserted, after pass 2

* That the artifacts **install and launch**. Provenance says who built a file, not that it
  works.
* Code signing: macOS and Windows builds remain unsigned, gated on a certificate.
* The SBOM tracks `uv.lock`, which is the development closure. Whether it describes what a
  user actually installs from PyPI is a pass-3 question.

## Pass 3 — what the release *says* it ships

Scope for this pass: the build scripts, the package channels, the SBOM, and signing.
This closes the sweep's declared budget of three passes.

### F5 — the SBOM declared the maintainer's toolchain as a user's dependencies (fixed)

`sbom.cdx.json` listed **283 components** for a project with **16 declared runtime
dependencies**, every one of them scopeless. CycloneDX reads an absent `scope` as
`required`, so the published inventory asserted that `pip install yazses` brings in
`pytest`, `mypy`, `ruff`, `mkdocs` and `jiwer`.

This is not a cosmetic overstatement. The file exists for one purpose — someone whose
policy requires a dependency inventory before software may be installed — and that reader
feeds it to a scanner. Over-declaring produces advisories against packages no user ever
receives, with nothing in the document to separate them from the real ones. The generator's
own docstring already claimed it "describes what a user actually resolves to". It did not.

`scripts/gen-sbom.py::classify_scopes` now derives the scope from `uv.lock` itself:

| `scope` | Count | Derivation |
|---|---|---|
| `required` | 52 | Closure of `requires-dist` entries with no `extra ==` marker |
| `optional` | 179 | Closure of the extra-gated entries, minus required |
| `excluded` | 52 | Closure of the `requires-dev` groups, minus the previous two |

Derived rather than listed, so a new extra or dependency group is classified the day it is
added. Three bugs surfaced while writing it, all of the same family — **a package reachable
from nothing comes out scopeless, which means required**, i.e. every graph-walk gap fails
in the direction that over-declares:

1. The lock spells the request two ways: a package's dependency entry says `extra = [...]`,
   the root's `requires-dist`/`requires-dev` entries say `extras = [...]`. Reading only the
   singular stranded `mkdocs-material[imaging]`'s six-package image toolchain.
2. `pkg[extra]` installs `pkg` as well. Following the extra *instead of* the base list
   stranded `pymdown-extensions` and three siblings.
3. A name can be locked twice — `scipy` resolves once per Python version — so keying
   packages by name dropped one resolution's edges. Today both reach the same set, which is
   why only a synthetic-lock test catches it; the day they differ, it would have been
   silent.

`docs/privacy-statement.md` now publishes the three counts, and a test parses that table
and compares it to the file rather than trusting it. Six mutations of the generator and the
docs were each confirmed to fail the suite.

### F6 — the release notes told every future release it was a v0 build (fixed)

`release.yml`'s body block is written once and republished verbatim at every tag. It told
macOS and Windows users "*the v0 build is unsigned; signing is coming*" — still, on the
v2.30.0 release page. The signing half was true; the version half had been wrong for three
majors, on the page a reader lands on when the OS warns them about the binary.

Reworded to name no version and to point at the attestation, which is the thing a reader
can actually check today. `tests/test_release_notes_claims.py` derives every `body:` in the
workflow and fails any that pins itself to a version series — a claim with no version in it
cannot go stale — and fails first if no body was found at all, so the guard cannot pass
vacuously on a refactor that moves the notes elsewhere.

### Signing is wired, not absent

Worth correcting the pass-2 note that "macOS and Windows builds remain unsigned, gated on a
certificate". The *pipelines* are complete: `build-macos.yml` runs `codesign --deep
--options runtime --timestamp` with entitlements, verifies, and submits to `notarytool`;
`build-windows.yml` uploads the installer to SignPath and swaps in the signed result. Both
are gated on `steps.sign.outputs.sign == 'true'`, which is computed from whether every
secret is present, and both name the artifact `…-signed-…`/`…-unsigned-…` accordingly.

So the gap is credentials, not code — and the day the certificates exist, nothing needs to
be written. That is the right shape, and it is worth stating plainly because a dormant,
fully-wired path is easy to mistake for a missing one and rebuild.

### Budget spent

Three of three passes. What the sweep did **not** reach, so it is not mistaken for clear:

* The three build scripts were read only for their signing and icon paths, not audited.
* No channel was verified end-to-end by installing from it; `check-release-channels.py`
  asks each channel what version it serves, which is a different claim from "it works".
* Provenance and SBOM are now both checked in CI. Neither says the artifact runs.
