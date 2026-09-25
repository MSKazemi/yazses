---
title: Platform support — operating systems, CPU architectures and install channels
description: Which operating systems and CPU architectures YazSes runs on, which install channel to use for each, and how to verify every claim on this page yourself. Linux, macOS, Windows, BSD.
---

# Platform support

Which operating systems and CPU architectures YazSes runs on, and which install
channel to use for each. **Audited live on 2026-08-16, and the desktop bundle and
snap rows re-audited on 2026-09-25** against PyPI, the Snap Store API, the GitHub
Releases assets, the published APT index and the `.deb` control fields — not against
the manifests in this repository, which can and do drift from what is actually
published.

Both audits moved rows in **both** directions, and the second one moved them back.
In August every Linux arm64 channel turned out to work already, while the two
cross-architecture desktop bundles turned out not to exist — their build legs are
advisory, so they had been failing while their workflows reported success. Those two
legs went green the same week and have attached a file to **every release since
v2.22.0**; this page went on saying they had not, for twenty-three releases, because
the test guarding it read the build leg's advisory flag instead of the release.
Understating support costs people a slower install; overstating it sends them after a
file that is not there. Both are wrong answers, and only one of them looks careful.

!!! tip "The short answer"

    `pipx install yazses` works on **every** row below that is supported at all. The
    published wheel is `py3-none-any` — pure Python, no architecture baked in — so
    PyPI is the universal path, and the native packages (`.deb`, `.dmg`, `.exe`,
    snap) are conveniences layered on top of it.

!!! question "Looking for *which features* work where?"

    This page answers **"will it install and run on my machine?"** — operating
    system, CPU architecture, install channel. For **which capabilities work in
    which session** (hold-to-talk, injection, tray, gaze, window control on X11 vs
    Wayland), see the [capability matrix](capability-matrix.md).

## Legend

| | Meaning |
|---|---|
| ✅ | Published and installable today |
| ⏳ | Built by CI but not yet published — lands at the next tagged release |
| ⚗️ | Wired up and unit-tested, but never run on real hardware |
| ❌ | Not available, with the reason given |

Which of ✅ and ⏳ a **desktop bundle** cell carries is not a judgement call.
[`tests/test_platform_support_claims.py`](https://github.com/MSKazemi/yazses/blob/main/tests/test_platform_support_claims.py)
compares each one against `packaging/released-assets.json` — the list of files the
last release attached to its tag, written by the same script that computes every
packaging checksum — and fails in both directions: a ✅ with no file behind it, and
a ⏳ on a file that shipped.

## Linux

Python 3.11+ required. **CI runs the full suite on 3.11, 3.12, 3.13 and 3.14** —
3.11 and 3.12 on all three operating systems, 3.13 and 3.14 on Linux, since what
those catch is interpreter behaviour rather than OS behaviour. Nothing above 3.11
is merely assumed to work: `pyproject.toml` may not claim an interpreter the matrix
does not run, nor omit one it does, and
[`tests/test_platform_support_claims.py`](https://github.com/MSKazemi/yazses/blob/main/tests/test_platform_support_claims.py)
fails the build in either direction.

| CPU | `pipx` / `uv tool` (PyPI) | Universal script | APT repo | Snap | `.deb` asset |
|---|---|---|---|---|---|
| **x86_64** (`amd64`) | ✅ | ✅ | ✅ | ✅ `stable` (X11 + Wayland) | ✅ |
| **aarch64** (`arm64`) | ✅ | ✅ | ✅ | ✅ `stable` (X11 + Wayland) | ✅ |
| `armhf`, `i386`, `ppc64el`, `s390x`, `riscv64` | ❌ | ❌ | ❌ | ❌ | ❌ |

**Every Linux channel works on arm64 today.** This page said otherwise until it was
measured, and the measurement is worth stating because it changes what you should
install:

- **The test suite now runs on aarch64, and until recently never had.** Every row
  above shipped on the strength of the code being pure Python; nothing had executed
  a single test on the architecture. It has now been run on an aarch64 Linux box —
  **12029 passed, 42 skipped, exit 0, identical to the x86_64 result**, with no
  arm64-specific failure of any kind. A leg on GitHub's free `ubuntu-24.04-arm`
  runner keeps it that way rather than leaving it a one-off. One genuine
  architectural difference surfaced and is harmless: CTranslate2 offers
  `{int8, float32, int8_float32}` on aarch64 against four types on x86_64 (`int16`
  is absent), and the settings window derives its list from CTranslate2 at runtime,
  so it already adapts.

- **The snap dictates on Wayland, not on X11 alone.** This page and the Snap Store
  listing both said X11-only until v2.37.0, when `inject/portal.py` was added: it
  types through `org.freedesktop.portal.RemoteDesktop`, the one route that survives
  strict confinement, and `inject/registry.py` treats a strictly confined snap as
  consent for it because a snap cannot install the `ydotoold` udev rule that the
  alternative needs. Approve the desktop's one-time permission prompt at first
  dictation. See [Install on Linux](install-linux.md#3e-what-the-snap-can-and-cannot-do).

- **The snap is on `stable` for arm64**, not edge-only. The Snap Store API answers
  `stable arm64` directly — the command is in [Verifying this page](#verifying-this-page-yourself).
  What *is* true is that the whole snap, both architectures, sits two releases
  behind the tag — at the time of writing `stable` is 2.29.0 against a 2.31.0
  release. That is a publishing gap, not an architecture gap, and it affects x86_64
  users equally.
- **The `.deb` and the APT repo are architecture-independent by construction.** The
  package declares `Architecture: all` and carries no compiled code: it installs a
  systemd user unit, a man page, and a `postinst` that runs `pipx install yazses`,
  which then fetches the architecture-appropriate wheels from PyPI. The two release
  assets `yazses_<version>_amd64.deb` and `yazses_<version>_arm64.deb` are the same
  package — same size, same file listing, both `Architecture: all`. The architecture
  in the filename is the *build host's*, from `dpkg --print-architecture`, and says
  nothing about what the package runs on.

  Consequence worth knowing: **pick either asset, they are interchangeable**, and
  the APT repo has served arm64 all along. This page previously told arm64 users to
  wait for a future release, which sent them to a slower install path for something
  they already had.

`pipx` and the universal script work on arm64 as well — PyPI ships `aarch64` wheels
for the whole runtime stack.

**Why the other five architectures cannot work:** the runtime stack is wheel-only.
`ctranslate2` (via faster-whisper), `onnxruntime` (via onnx-asr) and PySide6 publish
manylinux wheels for `x86_64` and `aarch64` **and nothing else**, so a build for any
other architecture fails at `pip install` every time. This is a dependency ceiling,
not a decision we can reverse in this repository.

!!! note "`pipx` on arm64 needs a compiler"

    `evdev` — the hold-to-talk key reader — publishes **no wheels at all**, so it is
    compiled from source on every Linux install. Install `build-essential
    python3-dev` (Debian/Ubuntu), `gcc python3-devel` (Fedora) or `base-devel`
    (Arch) first. The universal script checks for this before it starts; the snap
    bundles a prebuilt `evdev` and needs none of it.

Both X11 and Wayland are supported. See [Install on Linux](install-linux.md).

## macOS

macOS 11 (Big Sur) or newer.

| CPU | `pipx` (PyPI) | Homebrew | `.dmg` app bundle |
|---|---|---|---|
| **Apple Silicon** (`arm64`) | ✅ | ✅ `brew install --cask mskazemi/yazses/yazses` | ✅ (unsigned) |
| **Intel** (`x86_64`) | ✅ | ❌ cask tracks arm64 | ✅ (unsigned) |

**On an Intel Mac, download `YazSes-<version>-macos-x86_64.dmg`** from the
[latest release](https://github.com/MSKazemi/yazses/releases/latest). A universal2
build is **not** reachable — several of the runtime wheels ship single-architecture
binaries — so the fix was a *separate* Intel build rather than a fat one, and it has
been attached to every release since v2.22.0 (2026-08-16).

**Homebrew is the one Intel route that does not work yet**, which is why that cell
stays ❌: the cask carries a single `sha256` and `scripts/refresh-package-manifests.py`
hashes the arm64 `.dmg` for it. Adding Intel means `on_arm`/`on_intel` blocks with two
checksums, and a cask whose hash is a guess is worse than no cask — Homebrew refuses
the download, so the first thing a new user sees is a failure that looks like the
project is broken.

The `pipx` path is unaffected by any of that and is the one that outlasts the
hardware: resolving the runtime for `x86_64-apple-darwin` succeeds today, selecting
Intel wheels for the whole stack.

**It builds — as of 2026-08-16, and not before.** Until then this page said the build
"exists", and it did not: every attempt had failed at dependency resolution and the
workflow had reported success anyway, because the leg is `continue-on-error`. What it
failed on was not the architecture but the lock file — `uv.lock` pins an onnxruntime
that upstream publishes for Apple Silicon only, and `uv sync` installs exactly what
the lock says. The Intel leg now resolves unlocked, which backtracks to the last
release carrying an Intel wheel, and it produced a working
`YazSes-2.21.0-macos-x86_64.dmg` on the first run afterwards — as a **CI artefact**,
from the v2.21.0 tree. The v2.21.0 *release* carries no Intel `.dmg`; v2.22.0 is the
first that does, and every release since has.

It was marked ⏳ ("built by CI, not yet attached to a release") on the day that was
true, and stayed ⏳ long after it stopped being — through v2.22.0, which carried the
first `YazSes-2.22.0-macos-x86_64.dmg`, and the twenty-two releases after it. The
guard that was supposed to keep this row honest read the build leg's `experimental:`
flag and required the row to say ⏳ for as long as the leg stayed advisory, which is
a question about CI policy and not about whether anyone can download the file. It
now reads `packaging/released-assets.json` — the asset list of the last release,
regenerated by the same script that computes every packaging checksum — so the row
follows the release and nothing else.

The leg itself is still `continue-on-error` in `build-macos.yml`, and that is the
right call for a cross-architecture build that must not be able to fail a release
the Apple Silicon one completed fine. It does mean a future release could ship
without an Intel `.dmg` and say nothing about it; the refresh step would then record
its absence and this row would have to change back.

[#264](https://github.com/MSKazemi/yazses/issues/264) is still open, and asks the
question a step above this one: whether Intel is worth carrying at all. Read it with
its premise in mind — it argued that closing the Intel gap "costs money rather than
effort", and
[ADR-017](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-017-intel-mac-support-has-a-deadline.md)
records that premise as false: standard GitHub-hosted runners are free for public
repositories, so the leg costs runner minutes and not money. What is left of #264 is
how long the image lasts, which the warning below answers.

One consequence of building unlocked is worth stating rather than hiding: the Intel
bundle is not built from the pinned dependency set, so it is not reproducible against
`uv.lock` the way the Apple Silicon one is. The alternative was no Intel bundle at
all.

**The `.dmg` filenames now name their architecture.** They did not, and
`YazSes-2.20.0.dmg` reads as though it were for everybody — which is a large part of
why an Apple-silicon-only bundle went unnoticed.

!!! warning "Intel Mac support has an end date, and it is not ours"

    The Intel `.dmg` is built on GitHub's `macos-15-intel` runner
    ([ADR-017](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-017-intel-mac-support-has-a-deadline.md)).
    It costs nothing, and it does not last: `macos-15-intel` is the **last** x86_64
    image GitHub Actions will offer, it is available until **August 2027**, and
    x86_64 macOS support ends entirely in **Fall 2027**. The `macos-13` image that
    used to serve Intel builds was retired on 4 December 2025.

    So the desktop bundle for Intel has a roughly two-year horizon that no decision
    here can extend. **`pipx install yazses` is the Intel path that outlives it** —
    `ctranslate2` publishes `macosx_11_0_x86_64` wheels, so the Python install works
    on Intel today and keeps working as long as those wheels are published.

The `.dmg` is unsigned: right-click → **Open** on first launch. Grant
**Accessibility** and **Microphone** when prompted. See
[Install on macOS](macos-install.md).

## Windows

Windows 10 (21H2) or newer.

| CPU | `pipx` (PyPI) | `.exe` installer |
|---|---|---|
| **x64** | ✅ | ✅ (unsigned) |
| **arm64** | ⚠️ untested | ✅ (unsigned) |

**On Windows arm64, download `YazSes-<version>-windows-arm64.exe`** from the
[latest release](https://github.com/MSKazemi/yazses/releases/latest). The x64 `.exe`
also works — Inno Setup marks it `x64compatible`, which includes ARM, so it installs
and runs under Windows' x86 emulation — and `pipx install yazses` works as it does
everywhere. The native installer is the one that does not pay the emulation cost.

**The native arm64 installer ships, and has since v2.22.0.** On every tag before
2026-08-16 the leg failed before compiling anything:

```
error: No download found for request: cpython-3.12-windows-aarch64-none
```

The leg asked `uv` for a Python and `uv` had none for that architecture — it was
pinned to a version predating Windows ARM64 interpreter builds. With that pin lifted
the leg produced a 160 MB `YazSes-2.21.0-windows-arm64.exe` on its first run — a **CI
artefact**, from the v2.21.0 tree. The v2.21.0 *release* carries no arm64 `.exe`;
v2.22.0 is the first that does.

This is worth saying plainly because the failure was invisible. The leg is
`continue-on-error` — correct, so a new cross-architecture build cannot fail a
release the x64 build completed fine — and the consequence is that the workflow
reports **success** while shipping nothing for that architecture. Two releases went
out that way, and the leg is still advisory, so a future one could too.

The invisibility cuts the other way as well, and that is the mistake this row
actually shipped. The check written to catch it compared the page against the build
workflow's `experimental:` flags, so it read "advisory leg" as "nothing published"
and held this cell at ⏳ through twenty-three releases that each carried a
`YazSes-<version>-windows-arm64.exe`. A page that tells a Windows-on-ARM user their
installer does not exist yet is not the cautious answer; it is the wrong one, and it
sends them to emulation for a native build that is already there. The check now
reads `packaging/released-assets.json`, the asset list of the last release, and
fails in both directions: a ✅ with no file behind it, and a ⏳ on a file that
shipped.

**The `pipx` column stays ⚠️ untested, and the `.exe` column does not.** Nothing
exercises a `pipx install` on ARM. The installer is a different matter: the
`windows-11-arm` leg installs it silently, runs `yazses-cli --version` and
`yazses doctor` out of the installed tree, then uninstalls and asserts the user
`PATH` was restored — and the step that attaches the file to the release runs only
after all of that, so an `.exe` on the release page is itself evidence the smoke test
passed on ARM. What still has not happened is anyone *dictating* on a Windows ARM
machine: a runner has no microphone and no hold-to-talk key.

The installer is unsigned, so SmartScreen will warn: **More info → Run anyway**.
Code signing is tracked on the
[code-signing policy page](https://mskazemi.com/yazses/code-signing.html). See
[Install on Windows](windows-install.md).

## BSD — experimental

| System | `pipx` (PyPI) | Hold-to-talk | Autostart |
|---|---|---|---|
| **FreeBSD** | ❌ `ctranslate2` has no BSD build — see below | ⚗️ experimental | ❌ no systemd — use rc.d or your session's autostart |
| **OpenBSD**, **NetBSD**, **DragonFly** | ❌ same | ⚗️ experimental | ❌ same |

!!! failure "`pip install yazses` does not currently work on BSD"

    This row said ✅ until it was measured. It is not: the install fails during
    dependency resolution, before any YazSes code is reached.

    `faster-whisper` requires `ctranslate2`, which publishes 35 wheels — macOS,
    manylinux and Windows — **and no source distribution**. There is no FreeBSD
    port either. So pip has nothing it can use and nothing it can build:

    ```
    ERROR: Could not find a version that satisfies the requirement
           ctranslate2<5,>=4.0 (from faster-whisper) (from versions: none)
    ```

    `faster-whisper` is a hard dependency rather than an extra, so this is not
    avoidable by choosing a different speech engine at install time — even though
    `py312-onnxruntime` *is* in ports, which is what the Parakeet engine would
    need. Making a BSD install possible means moving the Whisper stack behind an
    extra, which is a packaging change and is tracked in
    [#306](https://github.com/MSKazemi/yazses/issues/306).

    Everything that does not need the decoder still runs — see
    [Any other OS](#any-other-os) below, which applies here in full.

YazSes builds a real backend on all four. It is a thin composition over the Linux
one, because on a BSD desktop those components are genuinely the same code path
rather than merely a similar one: paths come from `platformdirs` (which already
returns the XDG locations BSDs use), FreeBSD ships `evdev` (`/dev/input/event*`)
when the kernel has `EVDEV_SUPPORT` — the default since FreeBSD 12 — `xdotool`,
`wtype`, `ydotool`, `xclip` and `wl-clipboard` are all in ports/pkgsrc, and a Unix
domain socket is a Unix domain socket.

**⚗️ "Experimental" means exactly this:** the platform layer is now exercised on a
real FreeBSD VM in CI, and **the transcription stack still is not, because it
cannot be installed there at all.** `doctor` prints a `[WARN]` saying so rather
than a reassuring `[OK]`.

What is actually verified: a CI job boots a FreeBSD guest and runs the test suite
natively, where `sys.platform` genuinely *is* `freebsdN` rather than
monkeypatched. That covers platform detection, the composed backend, path
resolution, and the OS-independent commands (`reflow`, `table`, `shellpipe`,
`transcribe`) that must work on a platform with no backend at all.

That job spent weeks failing before a single test ran, on the dependency install
described above, and being `continue-on-error` it reported success every time — so
the gap was invisible in a green workflow. It now installs `--no-deps` and only
what the suite needs, which is why the evidence above exists.

Until 2026-08-29 the job ran **one file** — 48 tests out of the roughly 14,800
this project has — on the stated grounds that the rest need the decoder. That
reason turned out to be mostly wrong: the decoder is reached by a small set of
files, so the job was reporting on 0.3% of the suite while reading as FreeBSD
coverage.

It now runs `tests/` whole:

| | tests executed | red | measured where |
|---|---|---|---|
| the old one-file command | 48 | — | the VM |
| first whole-suite run | 14,212 | **96** + 4 errors | the VM |
| after the decoder markers and the missing programs | 14,260 | **20** + 4 errors | the VM |
| after the `safe.directory` fix | **14,304** | **0** | the VM |

Every row is a run that happened, and every number was read out of that run's own
pytest summary line rather than carried forward from the row above — the counts move
between rows because a test that starts skipping stops being executed, so "executed"
is not a constant the red column is subtracted from. The `0` row is
[run 33320909064](https://github.com/MSKazemi/yazses/actions/runs/33320909064) —
`14304 passed, 462 skipped in 249.16s`, job conclusion `success`. The `96` row is
[run 33313023270](https://github.com/MSKazemi/yazses/actions/runs/33313023270)
(`96 failed, 14212 passed, 413 skipped, 4 errors`) and the `20` row is
[run 33319683585](https://github.com/MSKazemi/yazses/actions/runs/33319683585)
(`20 failed, 14260 passed, 467 skipped, 4 errors`).

The last twenty were one cause wearing twenty faces. Every `git` invocation in the
guest exited 128, because the workspace is created on the Linux host as uid 1001 and
rsynced into a guest running as root, and git refuses a repository it does not
believe you own:

```
fatal: detected dubious ownership in repository at '/home/runner/work/yazses/yazses'
```

The host runner's checkout step adds itself as a `safe.directory` — for the *host's*
git. The guest has its own git, its own global config, and inherits neither. The job
now adds the workspace inside the guest and prints git's own complaint once before
the suite, so the next version of this never has to be inferred.

`scripts/simulate-missing-deps.py` remains useful for the *next* change rather than
this one: it makes exactly the modules FreeBSD cannot supply unimportable and runs
the suite on a Linux machine, which is how the decoder markers were checked before
being pushed. It cannot fake `sys.platform == "freebsdN"`, so it is a close estimate
and not a substitute for the job. The job stays `continue-on-error` until it has
been green for a while — one green run is not yet a record.

Those 96 were three causes and **not one defect between them**, which is the part
worth knowing if you are reading this job's history:

* **23** were `git` and `bash` simply not being in the VM image. Repo-hygiene
  guards shell out to one or the other, and a guard that cannot run its own probe
  reported itself as an assertion failure *about the repository* — a missing
  program dressed up as a finding.
* **20** were `ffmpeg`. `recimport/audio_io.load_audio` decodes through
  faster-whisper's bundled PyAV and falls back to a system `ffmpeg`; with neither
  installed the fallback had no fallback. This is the only leg in CI where that
  documented fallback can be exercised at all, so it is now installed and the
  path finally has coverage somewhere.
* **50** were the decoder stack, which genuinely cannot be installed here. Those
  tests carry a marker from `tests/decoder_stack.py` and skip on this platform
  alone. Deliberately per-test rather than the module-scope
  `pytest.importorskip` used elsewhere: `test_stt_download.py` has 24 tests and 5
  need the decoder, `test_shipped_backends.py` has 36 and needs it for 2 — a
  whole-module skip would drop 19 and 34 *passing* FreeBSD tests to silence 5 and
  2, trading the coverage this job exists for against a green tick.

A new test that reaches the decoder and forgets the marker still fails loudly
here, which is the property a hand-maintained exclusion list in the workflow
could never have.

Widening it immediately paid for itself: it surfaced a **shipped** defect nobody
had hit, because nobody had run that code on a BSD. `inject/ydotool.py` imported
`evdev` — Linux-only, and deliberately not installed here — inside the function
that turns a key combo into ydotool tokens, so every spoken command, every
backspace correction and the clipboard paste raised `ModuleNotFoundError` on
FreeBSD. The keycodes it needed are a frozen kernel ABI, so they are now a
committed table (`src/yazses/inject/keycodes.py`) that `tests/test_ydotool_keycodes.py`
re-derives against `evdev` wherever `evdev` exists.

**What is still unverified is the part you actually came for.** Nobody has
dictated a word with YazSes on BSD hardware, and CI cannot try: `ctranslate2` has
no BSD build, so the speech pipeline is not installable in that VM either. The row
stays ⚗️ for that reason, not for the platform layer. If you try it on real
hardware, [tell us what happened](https://github.com/MSKazemi/yazses/issues) —
that is the thing standing between this row and a plain ✅.

!!! info "You get the X11 hotkey backend, not evdev"

    `evdev` is a C extension compiled against `<linux/input.h>` and does not build
    on BSD, so `pip install yazses` deliberately does **not** pull it there —
    claiming it would make the install fail outright instead of merely degrade.
    The hotkey therefore comes from `python-xlib`, which is pure Python and works
    anywhere X11 does; the BSD backend tries it **first**, the reverse of Linux.

    Practical consequence: **hold-to-talk needs an X11 session on BSD.** Under
    Wayland, or on a console, there is currently no key-reading path. Text
    injection is unaffected — `xdotool`, `wtype`, `ydotool`, `xclip` and
    `wl-clipboard` are all in ports and `inject/auto.py` probes for whichever
    exists.

The one real difference from Linux is **autostart**: BSDs have no per-user systemd,
so `yazses autostart enable` refuses with instructions instead of writing a
`.service` file into a directory nothing on the system reads. `yazses start` works
normally.

## Any other OS

| System | Status |
|---|---|
| Solaris/illumos, AIX, Haiku, Cygwin, … | ⚠️ partial — see below |
| Android, iOS | ❌ not supported — see the [mobile notes](mobile/index.md) |
| Web / browser | ❌ not supported; [try it without installing](try-without-installing.md) runs it in Docker instead |

**A system with no backend is not a system where nothing works.** YazSes needs an
OS-specific backend for three things only — reading the hold-to-talk key, injecting
text into the focused window, and running as a service. Everything that does not
depend on those is pure CPU work and runs anywhere Python 3.11+ does:

```bash
yazses transcribe recording.m4a    # offline transcription of any audio/video file
yazses reflow / table / shellpipe / gitvoice / braille / case
yazses about / --version / --help
```

Commands that *do* need a backend exit with a readable message naming the supported
set and the list above — not a traceback. That is the whole difference between "this
tool does not run on my machine" and "the hold-to-talk half does not".

Adding a platform is a contained job: implement the Protocol interfaces in
`src/yazses/platform/<os>/` and register the `sys.platform` value in
`platform/factory.py`. The BSD backend in `src/yazses/platform/bsd/` is about 60
lines and is the worked example. The daemon and CLI need no other change — see
[the architecture guide](architecture.md).

## Verifying this page yourself

Every row above is checkable without trusting this document:

```bash
# PyPI — is the wheel really architecture-independent?
curl -s https://pypi.org/pypi/yazses/json | python3 -c \
  'import json,sys; [print(u["filename"]) for u in json.load(sys.stdin)["urls"]]'

# Snap Store — which architectures are on which channel, right now?
curl -sH 'Snap-Device-Series: 16' \
  'https://api.snapcraft.io/v2/snaps/info/yazses?fields=revision,version' \
  | python3 -c 'import json,sys; [print(m["channel"]["risk"], m["channel"]["architecture"], m["version"]) for m in json.load(sys.stdin)["channel-map"]]'

# GitHub Releases — what binaries does the latest tag actually ship?
gh release view --json assets --jq '.assets[].name'

# …and what this repository committed as the answer, which the ✅/⏳ marks
# above are tested against. The two disagreeing is a bug in the release flow.
python3 -c 'import json;print(*json.load(open("packaging/released-assets.json"))["assets"],sep="\n")'
```

A `curl -o /dev/null -w '%{http_code}'` check **lies** about Flathub,
`search.nixos.org` and AlternativeTo — they are single-page apps that answer HTTP 200
for pages that do not exist. Use each service's API instead.
