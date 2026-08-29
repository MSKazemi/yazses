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
