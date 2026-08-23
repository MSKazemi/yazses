# CI/CD audit — pass 1 of 3: the workflow layer

**Date:** 2026-08-24 · **Scope of this pass:** the 23 files in `.github/workflows/`.
Passes 2 and 3 cover the three build scripts in `scripts/`, the six package channels,
and release provenance / SBOM / signing.

## The question this audit asks

Not "is the YAML tidy" but: **what does each surface actually prove, by a command, today?**
Everything else is assertion. A pipeline is enterprise-grade when its claims are checkable,
not when it has more steps.

The sharpest form of that question turns out to be one the YAML cannot answer about itself:
*has this workflow ever run at all?* A file can be perfectly written, committed, reviewed,
and never once fire.

## Method

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

## Findings

### F1 — `ppa.yml` has never run, and could not have. *(live defect, now marked)*

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

### F2 — `release.yml` and `snap.yml` carried the same shape, one major ahead of the blade. *(fixed)*

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

### F3 — `flatpak.yml` cannot fire on the way this repository is actually developed. *(open)*

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

## What is now proven by a command

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

## Still only asserted, after this pass

* That any release workflow **does the right thing when it runs** — this pass proves only
  that it runs. Job-level correctness is pass 2/3 territory.
* That the six package channels install and launch. `T20` already records four frozen on
  credentials.
* Provenance, SBOM and signing: `checksums.yml` and the `.intoto.jsonl` attestations exist
  and ran on v2.30.0, but nothing in the repository *verifies* an attestation.
