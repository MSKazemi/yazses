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

## Legend

| | Meaning |
|---|---|
| ✅ | Published and installable today |
| ⏳ | Built by CI but not yet published — lands at the next tagged release |
| ⚗️ | Wired up and unit-tested, but never run on real hardware |
| ❌ | Not available, with the reason given |

## Linux

Python 3.11+ required.

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
| **Intel** (`x86_64`) | ✅ | ❌ | ❌ arm64-only bundle ([#264](https://github.com/MSKazemi/yazses/issues/264)) |

**On an Intel Mac, use `pipx install yazses`.** The `.dmg` is built on an Apple
Silicon runner and the bundled Mach-O has no `x86_64` slice, so the app bundle will
not launch there. A universal2 build is **not** reachable — several of the runtime
wheels ship single-architecture binaries — so the fix would be a separate Intel
build, not a fat one.

The `.dmg` is unsigned: right-click → **Open** on first launch. Grant
**Accessibility** and **Microphone** when prompted. See
[Install on macOS](macos-install.md).

## Windows

Windows 10 (21H2) or newer.

| CPU | `pipx` (PyPI) | `.exe` installer |
|---|---|---|
| **x64** | ✅ | ✅ (unsigned) |
| **arm64** | ⚠️ untested | ❌ no arm64 installer is built |

The `.exe` is built on an x64 runner only. On Windows arm64 the pure-Python wheel
installs, and x64 emulation covers the dependency wheels, but **nobody has run it
there** — it is listed as untested rather than supported, because claiming a
platform we have not exercised is how the arm64 snap gap happened.

The installer is unsigned, so SmartScreen will warn: **More info → Run anyway**.
Code signing is tracked on the
[code-signing policy page](https://mskazemi.com/yazses/code-signing.html). See
[Install on Windows](windows-install.md).

## BSD — experimental

| System | `pipx` (PyPI) | Hold-to-talk | Autostart |
|---|---|---|---|
| **FreeBSD** | ✅ | ⚗️ experimental | ❌ no systemd — use rc.d or your session's autostart |
| **OpenBSD**, **NetBSD**, **DragonFly** | ✅ | ⚗️ experimental | ❌ same |

YazSes builds a real backend on all four. It is a thin composition over the Linux
one, because on a BSD desktop those components are genuinely the same code path
rather than merely a similar one: paths come from `platformdirs` (which already
returns the XDG locations BSDs use), FreeBSD ships `evdev` (`/dev/input/event*`)
when the kernel has `EVDEV_SUPPORT` — the default since FreeBSD 12 — `xdotool`,
`wtype`, `ydotool`, `xclip` and `wl-clipboard` are all in ports/pkgsrc, and a Unix
domain socket is a Unix domain socket.

**⚗️ "Experimental" means exactly this:** every component is exercised by the test
suite against a simulated BSD `sys.platform`, and **nobody has run YazSes on real
BSD hardware.** It is wired up so that it *can* work and so a BSD user gets a
working `yazses doctor` and a truthful report — not because it is known to work end
to end. `doctor` prints a `[WARN]` saying so rather than a reassuring `[OK]`.
A CI job now runs the suite in a real FreeBSD VM; it is advisory until it has been
green for a while. If you try it,
[tell us what happened](https://github.com/MSKazemi/yazses/issues) — that is the
only thing standing between this row and a plain ✅.

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
