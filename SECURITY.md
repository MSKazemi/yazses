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
