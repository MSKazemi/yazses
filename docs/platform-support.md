---
title: Platform support — operating systems, CPU architectures and install channels
description: Which operating systems and CPU architectures YazSes runs on, which install channel to use for each, and how to verify every claim on this page yourself. Linux, macOS, Windows, BSD.
---

# Platform support

Which operating systems and CPU architectures YazSes runs on, and which install
channel to use for each. **Audited live on 2026-08-13** against PyPI, the Snap Store
API, the GitHub Releases assets and the Homebrew tap — not against the manifests in
this repository, which can and do drift from what is actually published.

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
| **x86_64** (`amd64`) | ✅ | ✅ | ✅ | ✅ `stable` | ✅ |
| **aarch64** (`arm64`) | ✅ | ✅ | ⏳ | ⏳ (`--edge` today) | ⏳ |
| `armhf`, `i386`, `ppc64el`, `s390x`, `riscv64` | ❌ | ❌ | ❌ | ❌ | ❌ |

**On arm64 today**, use the universal script or `pipx`. Both work now — PyPI ships
`aarch64` wheels for the whole runtime stack. The snap, the APT repo and the `.deb`
gain arm64 at the next tagged release ([#267](https://github.com/MSKazemi/yazses/issues/267));
until then `sudo snap install yazses --edge` is the only snap channel with an arm64
build, and it is a release behind.

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
| **Intel** (`x86_64`) | ✅ | ❌ cask tracks arm64 | ⏳ built, unproven ([#264](https://github.com/MSKazemi/yazses/issues/264)) |

**On an Intel Mac, use `pipx install yazses`.** A universal2 build is **not**
reachable — several of the runtime wheels ship single-architecture binaries — so the
fix is a *separate* Intel build rather than a fat one, and that build now exists: CI
produces `YazSes-<version>-macos-x86_64.dmg` alongside the Apple Silicon one.

It is marked ⏳ rather than ✅ for a specific reason. The `macos-15-intel` runner has
never completed a build in this repository, so the leg is advisory — a brand-new
cross-architecture job must not be able to fail a release the Apple Silicon build
completed fine. It becomes ✅ once it has produced a working `.dmg`, not before, and
the Homebrew cask will not offer it until then either: a cask whose hash is a guess is
worse than no cask.

**The `.dmg` filenames now name their architecture.** They did not, and
`YazSes-2.20.0.dmg` reads as though it were for everybody — which is a large part of
why an Apple-silicon-only bundle went unnoticed.

!!! warning "Intel Mac support has an end date, and it is not ours"

    An Intel `.dmg` is being added on GitHub's `macos-15-intel` runner
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
| **arm64** | ⚠️ untested | ⏳ native build added, unproven |

**On Windows arm64 today, use `pipx install yazses`,** or the x64 `.exe` — Inno Setup
marks it `x64compatible`, which includes ARM, so it installs and runs under Windows'
x86 emulation.

A **native** arm64 installer is now built by CI on a `windows-11-arm` runner and will
be attached to releases alongside the x64 one. It is marked ⏳ rather than ✅ for a
specific reason: neither that runner nor PyInstaller-on-ARM has ever run in this
repository, so the job is deliberately advisory — a brand-new cross-architecture
build must not be able to fail a release the x64 build completed fine. It becomes ✅
once it has produced a working installer, not before. Nobody has run YazSes on a
Windows ARM machine either, which is why the `pipx` column stays ⚠️ untested;
claiming a platform we have not exercised is exactly how the arm64 snap gap
happened.

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

What is actually verified, as of 2026-08-15: a CI job boots a FreeBSD guest and
runs `tests/test_platform_bsd_and_fallback.py` natively — 48 tests, green — where
`sys.platform` genuinely *is* `freebsdN` rather than monkeypatched. That covers
platform detection, the composed backend, path resolution, and the
OS-independent commands (`reflow`, `table`, `shellpipe`, `transcribe`) that must
work on a platform with no backend at all.

That job spent weeks failing before a single test ran, on the dependency install
described above, and being `continue-on-error` it reported success every time — so
the gap was invisible in a green workflow. It now installs `--no-deps` and only
what those tests need, which is why the evidence above exists.

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
```

A `curl -o /dev/null -w '%{http_code}'` check **lies** about Flathub,
`search.nixos.org` and AlternativeTo — they are single-page apps that answer HTTP 200
for pages that do not exist. Use each service's API instead.
