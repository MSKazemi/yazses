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

**Not exploitable in YazSes as shipped.** A patched release *does* exist (83.0.0),
which makes this different from the advisory above: the alert stays open because
one optional extra deliberately pins below it, not because there is nothing to
upgrade to.

The vulnerability is in setuptools' **sdist builder** — on a case-insensitive,
Unicode-normalising filesystem (macOS APFS/HFS+) an NFC/NFD collision can defeat a
`MANIFEST.in` exclusion, so a file you told the packager to leave out is included
in the source distribution anyway. Three things would each have to be true for
that to reach this project, and none is:

1. **YazSes is not built with setuptools.** `[build-system]` declares
   `requires = ["hatchling"]` and `build-backend = "hatchling.build"`. The
   vulnerable code path is not the one that produces the YazSes sdist or wheel.
2. **There is no `MANIFEST.in` in this repository.** The advisory is a bypass *of
   exclusion rules written in that file*. With no such file there are no
   exclusions to bypass, and hatchling's file selection is configured in
   `pyproject.toml` by a different mechanism entirely.
3. **Installing setuptools does not run the vulnerable path.** It is a build-time
   code path. `setuptools` reaches an ordinary install only as a runtime
   dependency of `ctranslate2` and `torch`; nothing in YazSes builds an sdist.

The pin itself is `setuptools<81`, scoped to the `voiceprint-resemblyzer` extra,
and it exists for an unrelated and load-bearing reason: `resemblyzer` requires
`webrtcvad`, whose first line is `import pkg_resources`, and setuptools removed
`pkg_resources` in 81. Without the pin that extra installs and then cannot import
— which is how it once shipped. So taking the security patch in that extra would
trade a build-time issue this project cannot reach for a runtime break every user
of the extra *would* hit.

If you build source distributions of **your own** packages on macOS in an
environment where YazSes pinned setuptools for you, upgrade setuptools there —
that is a real exposure, it is simply not one YazSes creates or can fix for you.
