# ADR-016 — The dependency budget: features pay for themselves

**Status:** Accepted (2026-08-08)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-011]] (offline by default), [[adr-v2-011-semg-modality-router]]
(the "no new base deps" clause this generalises), issue #141 (the CI gate), issue #135

---

## Context

YazSes ships **140 capabilities on 18 base dependencies**. That ratio is not an accident
and it is not a detail — it is the reason a user who wants plain dictation can install the
project without pulling mediapipe, speechbrain, sherpa-onnx, llama-cpp, PySide6-beyond-base,
or a single model weight.

The machinery already exists and works:

- `[project.optional-dependencies]` — 14 extras, one per heavy capability.
- `system/features.py::_FEATURE_DEPS` — maps a feature slug to the modules to probe and
  the packages to install.
- `system/deps.py` — `missing_modules` + `install_packages` (`uv pip` → `pip` fallback,
  targeting the running interpreter), so `yazses features enable <slug>` is turnkey.
- Lazy imports inside the code path that needs them, so an unenabled feature costs nothing
  at start-up.
- Models fetched on **first use**, never at install (`gaze/download.py`,
  `recimport/download.py`).

What does not exist is any enforcement. The property survives on reviewer attention.

## Decision

**A capability must pay for itself. A user who never enables it must not pay a byte.**

Concretely, every new capability:

1. Adds **no** base dependency. Its packages go in an extra and in `_FEATURE_DEPS`.
2. Is **OFF by default** in the feature registry.
3. Imports its heavy modules **lazily**, inside the function that needs them — never at
   module scope in anything the daemon imports.
4. Downloads any model or data file on **first use**, not at install time.
5. Degrades honestly when its dependency is absent — `system/backends.py::probe_backend`
   distinguishes "install this extra" from "this build cannot supply it", and neither may
   be reported as silence.

Base-dependency growth is permitted, but only as a deliberate, labelled, visible decision —
never as a side effect of an unrelated change.

### Channel exception: the snap cannot install anything, ever

On-demand install is the mechanism on pip/pipx/uv/apt. **It does not exist on snap**, and
this is not a bug to be fixed. `$SNAP` is a read-only squashfs, and Debian's
`EXTERNALLY-MANAGED` marker is staged beside the interpreter, so pip refuses under PEP 668
before it even reaches the read-only filesystem. Whatever a revision bundles is all that
revision will ever have.

So on snap the rule inverts: a heavy capability must be **bundled at build time or be
honestly unavailable**. Enabling a feature there must not write a config key that nothing
can honour — the failure mode that made this visible was exactly that, a capability reading
"on" while its packages could never be installed.

Bundling is itself budgeted, because `platforms:` builds x86_64 **and** aarch64 and a
dependency without wheels for both fails the arm64 build outright. Rejected on those
grounds so far: `praat-parselmouth` (no aarch64 wheel), `speechbrain` (drags in ~1 GB of
torch), `llama-cpp-python` (no PyPI wheels at all). Those features stay snap-impossible and
must say so, per the `system/backends.py` honesty rule — "this build cannot supply it" is a
different message from "install this extra", and the user must get the true one.

Audit what a snap really contains from the squashfs, never from `snapcraft.yaml` — the yaml
records intent, the filesystem records fact.

## Consequences

**Positive.** Install stays small and fast on every channel. Start-up time is bounded by
what the user actually turned on. The project can keep accepting ambitious features
(gaze, meeting diarization, local LLM notes) without the base install absorbing their cost.

**Negative, and accepted.** Enabling a heavy feature is slower at *enable* time, because
that is when the download happens. It also means a GUI cannot enable such a feature
synchronously without freezing — which is exactly the constraint recorded in issue #135,
where the settings window names the missing packages instead of installing them inline.

**The real risk is silent erosion.** A lazy import moved to module scope during an
unrelated refactor breaks this ADR while passing every test, because nothing asserts on
`sys.modules`. Reviewer vigilance is not a control for an invisible regression, so
**issue #141 moves enforcement into CI**: fail on eager optional imports, fail on unlabelled
base-dependency growth, and report cold-start import time on every run. Same philosophy as
the Android privacy gate (#85) — a rule a reviewer cannot see in a diff must be enforced by
a machine.

## Rejected

- **A single fat install ("just depend on everything").** Simpler to maintain, and it
  would make the base install hundreds of megabytes for capabilities most users never
  touch. It also breaks the offline-first pitch: a large install is a large download.
- **Vendoring optional dependencies.** Bloats the repo, defeats extras entirely, and puts
  us in the business of shipping other people's binaries — the same objection F-Droid
  raises for the Android port (ADR-MOB-006).
- **Documenting the rule and trusting review.** That is the status quo, and it is what
  this ADR exists to replace. The regression is invisible in a diff.
