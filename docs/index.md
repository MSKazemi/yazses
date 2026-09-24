---
title: YazSes — offline voice dictation for Linux, macOS & Windows
description: Hold a key, speak, release — your words are transcribed on-device with faster-whisper and typed into any focused app. No cloud, no API key, no subscription.
hide:
  - navigation
---

<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "SoftwareApplication",
      "@id": "https://mskazemi.com/yazses/#software",
      "name": "YazSes",
      "applicationCategory": "UtilitiesApplication",
      "applicationSubCategory": "Voice dictation / speech-to-text",
      "operatingSystem": "Linux, macOS, Windows",
      "inLanguage": "en",
      "keywords": "offline voice dictation, Linux voice typing, offline speech-to-text, Wayland dictation, local transcription, voice commands",
      "description": "Offline, on-device hold-to-talk voice dictation for Linux, macOS and Windows. Hold a key, speak, release — speech is transcribed locally with faster-whisper and typed into any focused app, plus voice commands and macros. No cloud, no API key, no subscription.",
      "url": "https://mskazemi.com/yazses/",
      "downloadUrl": "https://pypi.org/project/yazses/",
      "codeRepository": "https://github.com/MSKazemi/yazses",
      "sameAs": [
        "https://github.com/MSKazemi/yazses",
        "https://pypi.org/project/yazses/",
        "https://snapcraft.io/yazses",
        "https://arxiv.org/abs/2607.28878",
        "https://www.youtube.com/watch?v=nn8WUKsCvZ4",
        "https://www.wikidata.org/wiki/Q140935593"
      ],
      "citation": "https://arxiv.org/abs/2607.28878",
      "license": "https://www.apache.org/licenses/LICENSE-2.0",
      "isAccessibleForFree": true,
      "offers": { "@type": "Offer", "price": "0", "priceCurrency": "USD" },
      "featureList": [
        "Fully offline on-device speech-to-text (faster-whisper)",
        "Hold-to-talk dictation into any focused application",
        "Voice commands and user-defined macros",
        "Dysfluency-friendly mode for stuttered or dysarthric speech",
        "EMG/USB muscle-sensor trigger for hands-free accessibility use"
      ],
      "softwareVersion": "2.38.0",
      "mainEntityOfPage": { "@id": "https://mskazemi.com/yazses/index.html#webpage" },
      "author": { "@id": "https://orcid.org/0000-0002-1166-6559" },
      "publisher": { "@id": "https://orcid.org/0000-0002-1166-6559" }
    },
    {
      "@type": "WebSite",
      "@id": "https://mskazemi.com/yazses/#website",
      "url": "https://mskazemi.com/yazses/",
      "name": "YazSes",
      "description": "Official documentation for YazSes offline voice dictation.",
      "inLanguage": "en",
      "about": { "@id": "https://mskazemi.com/yazses/#software" },
      "publisher": { "@id": "https://orcid.org/0000-0002-1166-6559" }
    },
    {
      "@type": "WebPage",
      "@id": "https://mskazemi.com/yazses/index.html#webpage",
      "url": "https://mskazemi.com/yazses/index.html",
      "name": "YazSes — offline voice dictation for Linux, macOS & Windows",
      "description": "Hold a key, speak, release — your words are transcribed on-device and typed into any focused app.",
      "inLanguage": "en",
      "isPartOf": { "@id": "https://mskazemi.com/yazses/#website" },
      "about": { "@id": "https://mskazemi.com/yazses/#software" },
      "mainEntity": { "@id": "https://mskazemi.com/yazses/#software" }
    },
    {
      "@type": "Person",
      "@id": "https://orcid.org/0000-0002-1166-6559",
      "name": "Mohsen Seyedkazemi Ardebili",
      "url": "https://mskazemi.com/",
      "identifier": {
        "@type": "PropertyValue",
        "propertyID": "ORCID",
        "value": "0000-0002-1166-6559"
      },
      "sameAs": [
        "https://orcid.org/0000-0002-1166-6559",
        "https://scholar.google.com/citations?user=xP64pZsAAAAJ",
        "https://www.linkedin.com/in/mskazemi/",
        "https://github.com/MSKazemi"
      ]
    },
    {
      "@type": "SoftwareSourceCode",
      "name": "YazSes",
      "codeRepository": "https://github.com/MSKazemi/yazses",
      "programmingLanguage": "Python",
      "runtimePlatform": "Python 3.11+",
      "license": "https://www.apache.org/licenses/LICENSE-2.0"
    },
    {
      "@type": "VideoObject",
      "name": "YazSes — offline voice dictation for Linux, macOS & Windows (hold a key, speak, release)",
      "description": "40-second tour of YazSes: the hold-to-talk core loop, the command line (status, doctor, features), and the system tray. Speech is transcribed on-device with faster-whisper and typed into the focused app.",
      "thumbnailUrl": "https://i.ytimg.com/vi/nn8WUKsCvZ4/maxresdefault.jpg",
      "uploadDate": "2026-08-07T15:37:12-07:00",
      "duration": "PT40S",
      "contentUrl": "https://www.youtube.com/watch?v=nn8WUKsCvZ4",
      "embedUrl": "https://www.youtube.com/embed/nn8WUKsCvZ4",
      "publisher": { "@id": "https://orcid.org/0000-0002-1166-6559" },
      "about": { "@id": "https://mskazemi.com/yazses/#software" }
    },
    {
      "@type": "ScholarlyArticle",
      "name": "YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System",
      "headline": "YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System",
      "@id": "https://arxiv.org/abs/2607.28878",
      "url": "https://arxiv.org/abs/2607.28878",
      "identifier": "arXiv:2607.28878",
      "datePublished": "2026-07-30",
      "publisher": { "@type": "Organization", "name": "arXiv" },
      "author": { "@id": "https://orcid.org/0000-0002-1166-6559" },
      "about": { "@id": "https://mskazemi.com/yazses/#software" }
    }
  ]
}
</script>

<div class="yz-hero" markdown>

# YazSes

Offline, on-device voice dictation for **Linux, macOS & Windows**.
Hold a key, speak, release — your words are transcribed locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) and typed into any
focused app. **No cloud. No API key. No subscription. Nothing leaves your machine.**
{ .yz-hero__tagline }

[Get started :material-rocket-launch:](#install){ .md-button .md-button--primary }
[Platform support :material-monitor-multiple:](platform-support.md){ .md-button }
[Star on GitHub :material-star:](https://github.com/MSKazemi/yazses){ .md-button }

<div class="yz-chips">
  <span>hold</span><span>→ speak</span><span>→ release</span><span>→ text appears</span>
</div>

</div>

![YazSes — hold a key, speak, release; the text is typed into the focused app](screenshots/yazses-reel.gif)

*40-second tour: the core loop, the command line, and the system tray. Terminal output is real; the command-line typing is re-enacted for legibility.*
[:material-youtube: Watch it with narration and chapters on YouTube](https://www.youtube.com/watch?v=nn8WUKsCvZ4)

![yazses doctor — all green, fully offline by default](screenshots/yazses-doctor.png)

## Start with your goal

<div class="grid cards" markdown>

- :material-linux: **[Install on Linux](install-linux.md)** — recommended universal installer, plus APT, Snap and pipx alternatives
- :material-apple: **[Install on macOS](macos-install.md)** — Homebrew on Apple Silicon, native `.dmg` builds, or pipx
- :material-microsoft-windows: **[Install on Windows](windows-install.md)** — winget, native `.exe`, Scoop, or pipx
- :material-file-music: **[Transcribe a recording](tutorials/transcribe-recordings.md)** — audio/video to text or subtitles; speaker labels are optional
- :material-lifebuoy: **[Fix something that is not working](troubleshooting.md)** — start with `yazses doctor`, then jump to the symptom
- :material-tune: **[Customize YazSes](configuration.md)** — hotkey, models, vocabulary, features and `config.toml`

</div>

## Why YazSes

<div class="grid cards" markdown>

-   :material-shield-lock:{ .lg .middle } **Fully offline by default & private**

    ---

    Speech is transcribed on-device with CPU faster-whisper (int8). No GPU,
    no network, no account. No audio, no text — nothing leaves the machine
    by default.

    [:octicons-arrow-right-24: Privacy statement](privacy-statement.md)

-   :material-keyboard:{ .lg .middle } **Types into any app**

    ---

    Hold the hotkey, speak, release — the text lands in whatever window has
    focus: editor, browser, terminal, chat. Works on X11 and Wayland.

    [:octicons-arrow-right-24: Install on Linux](install-linux.md)

-   :material-server-network:{ .lg .middle } **Works over SSH and Remote-SSH**

    ---

    Because text is injected at the OS level, not inside an app, it lands in
    VS Code / Cursor Remote-SSH panes, integrated terminals, `tmux` and
    container shells — where in-app dictation usually can't reach.

    [:octicons-arrow-right-24: Dictation over SSH](how-to/remote-dictation.md)

-   :material-console:{ .lg .middle } **Voice commands & macros**

    ---

    A regex grammar maps *"undo that"*,
    *"save file"*, *"go to line 42"* to real key sequences.

    [:octicons-arrow-right-24: Command index](command-index.md)

-   :material-file-music:{ .lg .middle } **Transcribe recordings**

    ---

    `yazses transcribe meeting.m4a` turns any audio/video file into text —
    offline, with `--diarize` speaker labels and subtitle export.

    [:octicons-arrow-right-24: Transcription guide](tutorials/transcribe-recordings.md)

-   :material-human-cane:{ .lg .middle } **Built for accessibility**

    ---

    VAD calibration, mic-level tuning, dysfluency-friendly mode, and an
    EMG muscle-sensor trigger for fully hands-free use.

    [:octicons-arrow-right-24: Features](features.md)

-   :material-tune:{ .lg .middle } **Self-improving, on your terms**

    ---

    An opt-in, encrypted, on-device learning corpus lets `yazses tune`
    propose accuracy fixes from your own corrections.

    [:octicons-arrow-right-24: Performance tuning](how-to/performance-tuning.md)

</div>

## Install

=== ":material-linux: Linux (recommended)"

    ```sh
    bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)
    ```

    The universal installer provisions audio, hotkey and text-injection
    prerequisites, then runs `yazses doctor`. See the
    [Linux install guide](install-linux.md) for APT, Snap and pipx alternatives.

=== ":material-apple: macOS"

    On Apple Silicon, Homebrew is the recommended route:

    ```sh
    brew tap MSKazemi/yazses
    brew trust MSKazemi/yazses
    brew install --cask yazses
    ```

    Apple Silicon and Intel also have native `.dmg` builds. See the
    [macOS install guide](macos-install.md) for downloads, Gatekeeper and
    Accessibility/Microphone permissions.

=== ":material-microsoft-windows: Windows"

    ```powershell
    winget install MSKazemi.YazSes
    ```

    winget resolves x64 vs ARM64 automatically. See the
    [Windows install guide](windows-install.md) for the native installer, Scoop,
    SmartScreen and microphone permissions.

=== ":material-language-python: Python package"

    ```sh
    pipx install yazses
    ```

    This installs the Python package on supported platforms. On Linux, run
    `yazses setup` afterward to provision system dependencies. On macOS and
    Windows, prefer the platform-specific route above when you want the packaged
    desktop experience.

!!! note "The snap on Wayland"
    The strictly confined snap dictates on X11, and on **GNOME/KDE Wayland**
    through the `xdg-desktop-portal` RemoteDesktop API. It cannot configure or
    use the host `ydotoold` service, so the portal is the route it takes; the
    first dictation asks once for permission and the answer is remembered. The
    unconfined installs above remain the most-tested Wayland path.

    On X11, connect both required interfaces after installing:

    ```sh
    sudo snap install yazses
    sudo snap connect yazses:audio-record
    sudo snap connect yazses:raw-input
    yazses doctor
    ```

    `yazses setup` is not required for the snap. Confinement prevents it from
    installing host packages, changing groups, or configuring host services, so
    it can only print the manual permission checklist; the snap already bundles
    its X11 dependencies.

**Installed with `pipx` on Linux?** Provision the host in one command. Skip this
if you used the universal installer or APT path — both already do it:

```sh
yazses setup        # installs audio + injection deps, joins the input group, sets up ydotoold
# then log out and back in (the input-group change needs a fresh login)
```

Then:

```sh
yazses quickstart # machine-tailored next steps; read-only
yazses doctor     # check mic, injection backend and permissions
yazses enroll     # calibrate your microphone (~30 s)
yazses start      # start the dictation daemon
```

Hold the hotkey (Right Alt on Linux, Right Option on macOS, Right Ctrl on Windows), speak, release — the text appears in the focused app within about a second.

## What it does

- **Offline dictation** — type into any focused app with on-device faster-whisper (CPU, int8). No GPU needed.
- **Transcribe recordings** — `yazses transcribe meeting.m4a` turns any audio/video file into text, fully offline. Add `--diarize` to tag who said what and `--format srt` for subtitles. See the [transcription guide](tutorials/transcribe-recordings.md).
- **Voice commands** — a regex grammar maps phrases to editor/terminal key sequences: *"undo that"*, *"save file"*, *"go to line 42"*, *"run the tests"*, *"rename this to user_id"*.
- **Macros & personal vocabulary** — define multi-step commands and teach YazSes your mis-heard words.
- **Dysfluency-Friendly Mode** — opt-in collapse of stutters/repeats for stuttered or dysarthric speech.
- **Self-improving** — opt-in, encrypted on-device learning corpus; `yazses tune` proposes accuracy fixes from your own corrections.
- **Accessibility** — VAD calibration, mic-level tuning, and EMG (muscle-sensor) trigger support.

## What people use it for

<div class="grid cards" markdown>

- :material-linux: **[Voice typing on Linux](use-cases/voice-dictation-linux.md)** — dictation that works on X11 *and* Wayland
- :material-wave: **[Voice dictation on Wayland](use-cases/voice-dictation-wayland.md)** — GNOME, KDE Plasma, sway and Hyprland, terminals included
- :material-shield-lock: **[Confidential & offline work](use-cases/private-offline-dictation.md)** — clinical, legal, air-gapped
- :material-code-braces: **[Coding by voice](use-cases/voice-coding.md)** — spoken symbols, identifiers, LaTeX, git
- :material-microphone-message: **[Control by voice](use-cases/voice-commands.md)** — commands, macros, hands-free actions
- :material-human-cane: **[Accessibility & RSI](use-cases/accessibility-rsi-hands-free.md)** — hands-free and dysfluency-friendly
- :material-file-music: **[Transcribe recordings](use-cases/transcribe-audio-offline.md)** — offline, with speaker labels
- :material-code-braces: **[Dictating code](use-cases/dictating-code.md)** — identifiers, jargon and punctuation
- :material-speedometer: **[Choosing a model](models.md)** — measured accuracy vs latency
- :material-monitor-multiple: **[Platform support](platform-support.md)** — will it run on my OS and CPU
- :material-table-check: **[Capability matrix](capability-matrix.md)** — which features work where, and why not
- :material-tune: **[The Settings window](settings-gui.md)** — every capability as a checkbox, no config file
- :material-translate: **[More than one language](use-cases/multilingual-dictation.md)** — non-English and code-switching

</div>

[Browse all use cases :octicons-arrow-right-24:](use-cases/index.md){ .md-button }

## When *not* to use it

YazSes is **not an LLM agent** — it dictates text and runs editor/terminal commands; it does not browse, reason over your files, or hold a conversation. It uses CPU faster-whisper (a cloud service may still win on raw accuracy for a noisy mic), ships English-tuned `*.en` models by default, and is desktop-only.

## How it works

```
Hold hotkey → record audio → VAD gate → faster-whisper (CPU)
            → clean + disfluency filter → command grammar (Tier 1 regex)
            → dictate? type it · command? send keys
```

Two at-a-glance signals show you what YazSes is doing: a top-bar **"Y" tray icon** whose colour is a live state indicator (🔵 idle · 🟢 dictating · 🟡 no text target → clipboard · 🟣 command mode · 🔴 problem) and an optional **sonar overlay** that pulses near your cursor while it's listening. See [Tray icon & overlay](tray-and-overlay.md) for what each colour means.

Want the CLI itself, not a description of it? **[Watch it play right here](watch-the-cli.md)** —
a real [asciinema](https://asciinema.org) recording of `-h` → `about` → `quickstart` →
`features` → `status`, with selectable, copy-pasteable text. Or in your own terminal:
`asciinema play docs/demo/yazses-cli.cast`.

## Documentation

<div class="grid cards" markdown>

- :material-book-open-variant: **[Install on Linux](install-linux.md)** · [macOS](macos-install.md) · [Windows](windows-install.md)
- :material-console-line: **[CLI reference](cli-reference.md)** — every command and flag
- :material-cog: **[Configuration](configuration.md)** — every `config.toml` section
- :material-star-four-points: **[Features](features.md)** & **[v2 preview](v2-features.md)**
- :material-scale-balance: **[Comparison & alternatives](comparison.md)** — vs Talon, Dragon, Wispr Flow
- :material-frequently-asked-questions: **[FAQ](faq.md)** — common questions answered
- :material-sitemap: **[Architecture](architecture.md)** & **[diagrams](diagrams/index.md)**
- :material-lifebuoy: **[Troubleshooting](troubleshooting.md)** & **[roadmap](roadmap.md)**
- :material-flask-outline: **[Research](research/index.md)** — the cited science behind eye, voice & muscle input
- :material-school-outline: **[Student & research projects](research/get-involved.md)** — thesis-sized problems, open issues

</div>

!!! tip "Curious *why* it works this way?"

    The [research section](research/index.md) is a public, fully-cited notebook
    on post-keyboard input: how accurate webcam eye tracking really is, how
    offline speech recognition overtook the cloud, and why a $50 muscle sensor
    beats a $1,000 EEG headset. Every design decision in YazSes traces back to
    a measurement there — and the open questions are open to anyone.

## FAQ

**Does it work without internet?** Yes — transcription runs locally; nothing is sent anywhere by default.

**What GPU do I need?** None. It runs on CPU; 4 GB RAM minimum, 8 GB comfortable.

**Does it work on Wayland?** Yes. Unconfined installs use `wtype`/`ydotool`;
the strictly confined Snap uses the `xdg-desktop-portal` RemoteDesktop API on
GNOME/KDE Wayland. The universal installer remains the most-tested Linux path.

**Is it a replacement for Talon?** YazSes focuses on offline dictation plus a practical command grammar. Talon has far more advanced scripting. They can coexist.

More answers in the **[full FAQ](faq.md)**, and a side-by-side in **[Comparison & alternatives](comparison.md)**.

---

Apache-2.0 licensed. If YazSes is useful to you, a ⭐ on [GitHub](https://github.com/MSKazemi/yazses) helps others find it.

**Want to help?** See [Contributing](contributing.md) — several tasks need no code at all, like
translating the README, sharing a config you already use, or adding the microphone that worked
for you.
