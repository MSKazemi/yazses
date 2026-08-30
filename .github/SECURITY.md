# Security Policy

YazSes is an offline, on-device voice-dictation tool. By design, audio and
transcribed text stay on the local machine and nothing is sent to any network
service by default. The opt-in learning corpus is stored encrypted
(AES-256-GCM, machine-bound key). Security and privacy are core to the project,
so vulnerability reports are taken seriously.

## Supported versions

Security fixes are applied to the latest released version on the `main` branch.
Please upgrade to the newest release before reporting an issue.

| Version | Supported |
|---------|-----------|
| Latest release | ✅ |
| Older releases | ❌ (please upgrade) |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, report privately through either channel:

- **GitHub Security Advisories** — open a private report at
  <https://github.com/MSKazemi/yazses/security/advisories/new> (preferred).
- **Email** — mohsen.seyedkazemi@gmail.com with the subject line
  `YazSes security report`.

Please include:

- a description of the issue and its potential impact,
- steps to reproduce (proof-of-concept if available),
- affected version(s) and platform (Linux / macOS / Windows), and
- any suggested remediation.

## What to expect

- Acknowledgement of your report within **7 days**.
- An initial assessment and severity triage shortly after.
- Coordinated disclosure: a fix and a public advisory once a patch is available.
  Reporters are credited unless they prefer to remain anonymous.

## Scope

In scope: the YazSes daemon, CLI, IPC layer, injection backends, remote agent,
and the encrypted learning corpus. The Android app will be in scope once it
exists; until then, reports against its *design* (the ADRs in `docs/mobile/adr/`)
are welcome as public issues — there is nothing to exploit yet.

Out of scope: vulnerabilities in third-party dependencies (report those
upstream), and issues that require an already-compromised local account with
the same privileges as the user running YazSes.

## Known advisories in dependencies

"Out of scope" is not the same as "unanswered". An advisory against a dependency
still shows up in anyone's supply-chain scan of this repository, and leaving it
with no published reasoning is how a real finding later gets waved through by
someone who has learned the alerts are noise. So each open advisory that this
project does not simply upgrade away is assessed here — whether because no
upstream patch exists, or because something here holds the dependency below the
fix — and **each assessment is pinned by a test** in
`tests/test_dependency_advisories.py` — the reasoning below cannot quietly stop
being true without the suite failing.

### `diskcache` ≤ 5.6.3 — unsafe pickle deserialization

**Not exploitable in YazSes as shipped.** No patched release exists upstream, so
this alert stays open until one does.

`diskcache` is not a dependency of YazSes. It arrives only underneath
`llama-cpp-python`, and two things have to be true for the advisory to bite —
neither is:

1. **A default install never downloads it.** `llama-cpp-python` appears only in
   the `slm`, `notes` and `all` extras, never in `project.dependencies`. Unless
   you opted into a local LLM feature, the package is not on your machine.
2. **Nothing here ever deserializes a cache.** The vulnerability is in unpickling
   a `diskcache` file. `llama_cpp` reads one only when a caller installs a cache
   object via `Llama.set_cache(...)`. YazSes never calls it, never constructs
   `LlamaDiskCache`, and never imports `diskcache` — so no cache file is ever
   written or read.

Exploiting it would additionally require an attacker who can already write to
your cache directory, which is the local-account precondition listed as out of
scope above.

If you enable a local LLM feature *and* configure llama-cpp's disk cache
yourself, that assessment no longer covers you — that is a supported thing to
want, so please open an issue rather than assuming.

### `lightning` ≤ 2.6.5 (CVE-2026-58659) — code execution from a checkpoint

**Reachable in principle, and bounded by three things this repository controls.**
No patched release exists: 2.6.5 is the newest on PyPI and the fix is an
unreleased upstream commit, so this one cannot be closed by a version bump.

This entry is deliberately worded less comfortably than the `diskcache` one above,
because the honest answer is different. `diskcache` is unreachable — nothing here
ever constructs the object that would unpickle. This code path *is* executed, by
the pyannote diarization backend, and what stands between it and an exploit is a
precondition rather than an absence.

The vulnerability is in `lightning/pytorch/core/saving.py::_load_state`. A
checkpoint's hyperparameters may carry an `_instantiator` string; lightning
imports that dotted path and calls it. It is plain text in the hparams, so
`weights_only=True` does not stop it. `pyannote.audio` reaches it —
`Pipeline.from_pretrained` → `Model.from_pretrained` → `load_from_checkpoint`.

What bounds it:

1. **No shipped artifact contains it.** `pyannote.audio` is in the
   `diarization-pyannote` and `all` extras only. Verified against the lockfile
   rather than the declaration, because a `uv.lock` is a *universal* resolution
   and this project has already been wrong about exactly that (see the
   `setuptools` entry below): a default `uv export --no-dev` emits no
   `lightning`, no `pyannote`, and no `torch`, and neither does `--extra
   diarization`. The Docker image installs `yazses[diarization]`, the `.deb`
   installs `yazses[desktop]`, and the snap bundles `sherpa-onnx` and
   deliberately bundles nothing from the torch family. You get this dependency
   only by asking for it by name.
2. **It is not the default backend.** Diarization defaults to `sherpa` — ONNX
   Runtime, no torch, no lightning. `backend = "pyannote"` is a choice.
3. **The checkpoint is not attacker-selectable.** `PIPELINE_ID` and
   `SEGMENTATION_ID` in `yazses/recimport/pyannote_backend.py` are hardcoded
   module constants. There is no config key that redirects them, and nothing in
   YazSes loads a user-supplied `.ckpt` from anywhere. So the malicious
   checkpoint has to arrive *as* `pyannote/speaker-diarization-3.1` or
   `pyannote/segmentation-3.0` — which means compromising those gated
   repositories on Hugging Face, not handing you a file.

Fact 3 is the load-bearing one and the one most likely to be broken by a future
change, so it is the one the tests pin: adding a `[meeting] pyannote_model`
config key would be an ordinary-looking feature that silently converts a
supply-chain precondition into "point it at a repo". The suite fails if the ids
stop being literals, if the loader is called with anything else, or if
`pyannote.audio` becomes a base dependency.

**Residual risk, stated plainly.** If those upstream repositories are compromised,
you execute their code. That is true here *independently of this CVE* — pyannote
reads its pipeline class name out of the downloaded `config.yaml` and imports it —
so the honest summary is that trusting the model is part of using pyannote, and
this advisory does not change the trust boundary so much as make it explicit.
Passing `revision=` to pin the model to a known commit is the obvious next
hardening and is **not implemented**: pyannote propagates a parent revision only
to `$model/`-style child references, and `pyannote/segmentation-3.0` is a
separately gated repository, so how far a pin actually reaches could not be
verified without accepting the gated licence. It is written down here rather than
guessed at.

If you do not use pyannote diarization — which is the default — none of this is
installed on your machine.

### `setuptools` < 83.0.0 — `MANIFEST.in` exclusion bypass when building an sdist

**Resolved — the lock now takes 84.0.0.** This entry is kept rather than deleted
because the way it was *wrongly* assessed is the useful part.

The vulnerability is in setuptools' **sdist builder** — on a case-insensitive,
Unicode-normalising filesystem (macOS APFS/HFS+) an NFC/NFD collision can defeat a
`MANIFEST.in` exclusion, so a file you told the packager to leave out is included in
the source distribution anyway. Two facts still stand and are still guarded by tests:
YazSes is built with **hatchling**, not setuptools (`[build-system]`), and there is
**no `MANIFEST.in`** in this repository for the bypass to act on.

What did not stand was the third claim. The alert had been left open because the
`voiceprint-resemblyzer` extra pinned `setuptools<81` — `resemblyzer` needs
`webrtcvad`, whose first line is `import pkg_resources`, which setuptools removed
(80.10.2 has it; 83.0.0 and 84.0.0 do not). Three files said, in three different
wordings, that the pin was confined to that opt-in extra. It was not:

* `uv.lock` is a **universal** resolution — one version per package for the entire
  workspace. It has no way to hold a package back "only inside an extra".
* `uv export --no-dev`, asking for no extras at all, emitted `setuptools==80.10.2`,
  because core `ctranslate2` requires setuptools and there was a single entry to
  satisfy every consumer.
* `scripts/build-macos.sh` and `scripts/build-windows.ps1` build the shipped `.dmg`
  and `.exe` from that lock, so the held-back version reached release artifacts.

The pin has therefore been removed from `pyproject.toml`, and the `ignore` rule that
was suppressing the security PR has been removed from `.github/dependabot.yml`. The
remedy for that one extra now lives where the choice is made: install it and, in that
environment, `pip install "setuptools<81"`. `voiceprint/factory.py` already
distinguishes "installed but cannot import" from "absent" and reports the real
`ModuleNotFoundError`, so the failure is self-describing rather than silent, and
`.github/workflows/heavy-extras.yml` applies the same remedy weekly — which is what
proves the instruction works.

The guard that should have caught this read `project.dependencies` and
`optional-dependencies`. Both are *declarations*; the property being claimed was
about the *resolution*. It now asserts the version `uv.lock` actually resolves.
