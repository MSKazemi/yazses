---
title: YazSes vs Handy, OpenWhispr, Talon, Dragon & Wispr Flow — offline dictation compared
description: "An honest comparison of offline voice dictation tools for Linux, macOS and Windows: YazSes vs Handy, OpenWhispr, FluidVoice, VoiceInk, Dragon NaturallySpeaking, Talon Voice, nerd-dictation, Vocalinux, TalkType, VOXD, Speech Note, Wispr Flow, Google and Apple dictation — which runs offline, which does voice commands, which supports Wayland, and which is free."
---

# YazSes vs. other dictation tools

**Short answer:** YazSes is the tool to pick when you want **hold-to-talk voice
dictation that runs fully offline on Linux (and macOS/Windows), is free and
open-source, and also does voice commands** — without sending your voice to any
cloud service. If you need cloud-grade AI reformatting, professional
medical/legal accuracy, or deep voice-coding scripting, one of the alternatives
below may fit you better. This page is deliberately honest about where each tool
wins.

## At a glance

| Tool | Runs offline | Voice commands | Linux | macOS / Windows | Cost | Open source |
|---|---|---|---|---|---|---|
| **YazSes** | **Yes** (on-device faster-whisper) | **Yes** (regex grammar) | **Yes** (X11 & Wayland) | **Yes** | **Free** | **Yes (Apache-2.0)** |
| **Handy** | Yes (whisper.cpp) | No | Yes | Yes | Free | Yes (MIT) |
| **OpenWhispr** | Yes (Whisper/Parakeet; cloud optional) | Spoken instructions | Yes | Yes | Free | Yes (MIT) |
| **FluidVoice** | Yes (Parakeet) | Yes (Command Mode) | Announced | macOS (Windows community port) | Free | Yes (GPLv3) |
| Dragon (Nuance) | Yes | Yes | No | Windows | Paid (commercial) | No |
| Talon Voice | Yes | Yes (advanced scripting) | Yes | Yes | Freemium | No (free tier + paid beta) |
| nerd-dictation | Yes (VOSK) | Via Python config | Yes | No | Free | Yes (GPL-3.0) |
| Vocalinux | Yes (whisper.cpp / Whisper / VOSK) | Yes | Yes (X11 & Wayland) | No | Free | Yes (AGPL-3.0) |
| Wispr Flow | No (cloud) | Limited | No | Yes | Subscription | No |
| Willow Voice | No (cloud) | Limited | No | Yes (+ iOS) | Subscription | No |
| Voice In | No (browser engine) | No | Via browser | Via browser | Freemium | No |
| Google Voice Typing | No (cloud) | No | Via browser | Yes | Free | No |
| Windows Voice Typing | No (cloud) | Limited | No | Windows only | Free | No |
| Apple Dictation | Partial | Limited | No | macOS only | Free | No |
| Whisper + DIY scripts | Yes | No (you build it) | Yes | Yes | Free | Yes |

> **Looking for meeting notes rather than dictation?** YazSes also records whole
> meetings and transcribes existing recordings offline. That is a different
> competitor set (Otter.ai, Fireflies, Granola, Meetily) and has its own page:
> **[Offline meeting notes](meeting-notes-offline.md)**.

## What makes YazSes different

- **Fully offline & private by default.** Audio is transcribed on-device with CPU
  faster-whisper (int8). No GPU, no network, no account — nothing you say leaves
  the machine.
- **Dictation *and* voice commands.** Speak to type, or use a fast regex command
  grammar that maps
  *"undo that"*, *"save file"*, *"go to line 42"* to real key sequences.
- **Hold-to-talk.** Natural push-to-talk that types into whatever app has focus —
  editor, browser, terminal, chat.
- **Linux-first, cross-platform.** Works on X11 and Wayland, plus macOS and Windows.
- **Built for accessibility.** VAD calibration, a dysfluency-friendly mode for
  stuttered/dysarthric speech, and an optional EMG muscle-sensor trigger for
  hands-free use.
- **Self-improving on your terms.** An opt-in, encrypted, on-device learning corpus
  lets `yazses tune` propose accuracy fixes from your own corrections.
- **One tool for three jobs.** The same install and the same downloaded model do
  live dictation, offline transcription of existing recordings
  (`yazses transcribe`), and whole-meeting capture with speaker labels
  (`yazses meeting`). Every other tool on this page does one of the three.

## The difference that is not a feature

Everything in the list above is copyable. Offline Whisper, a command grammar,
Wayland support, a tray icon — any of the open-source projects on this page could
ship all of it within a couple of releases, and some of them will. If you are
choosing a tool for this month, compare the features. If you are choosing a
project to *depend on*, or to contribute to, the more useful question is what it
is structurally able to become.

Every dictation tool listed here answers "how does the user start talking?" the
same way: **a hotkey, hardcoded**. That single assumption is load-bearing — it
decides who the tool can serve. If you cannot reliably press and hold a key, a
push-to-talk dictation tool is not accessible to you, no matter how good its
transcription is.

YazSes treats the activation channel as a **replaceable part**. A hotkey is one
implementation of a protocol, not a built-in assumption, and other implementations
already exist in the tree: a USB-serial EMG muscle sensor, a BLE variant, and
gaze-based window targeting on X11.

What that buys is a straight answer to a question the other tools cannot answer at
all — *"I can't press a key. Can I still use this?"*

It is also why the research on the [muscle and brain control
page](research/muscle-brain-control.md) is not decoration. The 2025–26
silent-speech literature is converging on a result that maps directly onto this
architecture: closed vocabularies of 10–30 words are decoded at
[96–97% accuracy](research/muscle-brain-control.md#the-measured-hierarchy-end-to-end),
while open-vocabulary silent speech still costs ~68% word error rate. So the
defensible split is **silent commands plus spoken prose** — which needs a system
where a command channel and a dictation channel can be owned by different
hardware. That is a shape, not a feature, and it is not something a hotkey-shaped
tool can add later without becoming a different program.

!!! warning "What is real today, and what is not"

    This page's honesty rule applies here too, so to be precise about the state of
    it: the **EMG serial and BLE backends exist and work** as a hold-to-talk
    trigger, and **gaze window-targeting works on X11**. The modality role router
    that assigns *commands* to one channel and *dictation* to another is written
    and unit-tested but **not yet wired into the daemon**, and the seam still only
    carries "start" and "stop" — a decoder that recognises a *word* cannot express
    it yet. Both are tracked in the open
    [Silent input milestone](https://github.com/MSKazemi/yazses/milestone/11).

    If you need silent commands working today, none of the tools on this page —
    including this one — will give you that. What differs is which of them is
    built so that it can.

## What the subscription actually costs over time

Dictation is a tool you use every working day for years, which makes a monthly fee an
unusual shape of cost: you keep paying for speech recognition that already worked the
first month. The comparison is worth making concretely.

Published list prices, **checked 2026-08-11** (Willow and Voice In **2026-08-15**;
verify before quoting — these change):

| Tool | Cheapest paid tier | Per year | Over 5 years |
|---|---|---|---|
| **YazSes** | — | **$0** | **$0** |
| Voice In Plus | $60/year | $60 | **$300** |
| Wispr Flow Pro | $12/mo billed annually ($15 monthly) | $144 | **$720** |
| Willow Individual | $12/mo billed annually | $144 | **$720** |
| Otter.ai Pro | $8.33/mo billed annually ($16.99 monthly) | $100 | **$500** |
| Otter.ai Business | $19.99/mo billed annually ($30 monthly) | $240 | **$1,200** |

For a team of five on Otter Business, the five-year figure is **$6,000**.

Three caveats, because a cost table that only argues one way is not an honest one:

- **Free is not the same as costless.** YazSes costs you setup time, about 1.25 GB of
  disk, and some CPU while it transcribes. If your time is worth more than the
  subscription, buy the subscription — that is a legitimate answer.
- **The paid tools do things YazSes does not**, and the sections below say where. Cloud
  models are larger than anything that fits comfortably on a laptop CPU.
- **The prices above are list prices** and both vendors run discounts.

!!! info "The part that is not about money"
    A subscription can be raised, re-tiered, or discontinued, and your access to your own
    workflow goes with it. A local, Apache-2.0 tool cannot be taken away from you — the
    version you have today keeps working on the machine you have today, forever, with no
    account to expire and no server to shut down. For some people that is worth more than
    the fee; for others it is irrelevant. It is a real difference either way.

## Speaking is faster than typing — with an honest asterisk

Ordinary speech runs at roughly **120–150 words per minute**, while most people type at
**35–60 wpm**. That is the reason dictation is attractive at all.

But raw throughput is the wrong number to plan around, and any tool that quotes it
without qualification is overselling. What matters is throughput **after corrections** —
and correcting a recognition error costs far more than the words it replaces, because you
have to notice it, move the caret, and fix it.

So the useful framing is not "dictate everything, three times faster". It is:

- Dictation wins clearly for **prose you would otherwise compose slowly** — long-form
  writing, email, notes, documentation, chat.
- It wins overwhelmingly when typing is **painful or impossible** — RSI, injury,
  limited hand mobility. Here it is not a speed comparison at all.
- It wins least for **dense code and identifiers**, where accuracy per token matters
  most and correction cost is highest.

The measured accuracy behind those judgements is on the [benchmarks page](benchmarks.md)
rather than asserted here. YazSes has not run a controlled throughput study against
typing; that experiment is
[an open research question](research/agenda.md), deliberately listed as unanswered
rather than guessed at.

## Will it still be here next year?

A fair question for any small open-source project, and the honest signals rather
than a promise:

- **Apache-2.0**, no CLA, no open-core tier withheld from the repo. If this project
  stalls, the whole thing is forkable by anyone, with no permission required.
- **2,300+ tests** across Linux, macOS and Windows on every push, so a fork or a new
  maintainer inherits something they can actually change safely.
- Published on **four independent channels** (PyPI, Snap, an APT repo, and
  `.dmg`/`.exe` release artifacts), so it does not disappear if one of them does.
- Ten people have contributed. That is a small number, said plainly — but the
  architecture, the ADRs and the design decisions are all in the open precisely so
  it does not depend on one person's continued attention.

The thing most likely to kill a project like this is not competition; it is a
single maintainer losing interest with everything undocumented. That is the failure
being designed against.

## When another tool is the better choice

### YazSes vs Dragon NaturallySpeaking

**Choose Dragon** if you need best-in-class accuracy for professional
medical/legal dictation on Windows and a commercial license is acceptable. Dragon
is a mature, paid, Windows-focused product with specialist vocabularies YazSes
does not ship.

**Choose YazSes** if you are on Linux or macOS (Dragon is Windows-only), if a
per-seat commercial licence is a blocker, or if you want the source to be
auditable. On accuracy for general prose the gap is much smaller than it used to
be; on specialist terminology it is not.

### YazSes vs Talon Voice

**Choose Talon** if your priority is deep, scriptable *voice coding*. Talon has a
powerful scripting ecosystem — Python configs, a large community grammar library,
eye tracking — and for people who drive their whole desktop by voice it remains
the most capable option.

**Choose YazSes** if you want dictation that works out of the box without
learning a scripting system, want it fully open-source (Apache-2.0), or want file
transcription and meeting capture from the same install. The two coexist happily;
they are aimed at different points on the effort/power curve.

### YazSes vs nerd-dictation

[nerd-dictation](https://github.com/ideasman42/nerd-dictation) is a single Python
file using the VOSK API, GPLv3, with famously small models and no background
process — dictation is started and stopped with explicit begin/end commands, and
you customise output by writing Python string operations.

**Choose nerd-dictation** if you want maximum minimalism and hackability, the
lowest possible resource footprint, or you like configuring behaviour in code.

**Choose YazSes** if you want a hold-to-talk key instead of begin/end commands,
Whisper-class accuracy rather than VOSK, macOS/Windows support (nerd-dictation is
Linux-only), or the packaged extras — voice commands, macros, personal
vocabulary, file transcription, meeting capture.

→ [The detailed comparison, with a step-by-step migration guide](compare/yazses-vs-nerd-dictation.md)

### YazSes vs Vocalinux

[Vocalinux](https://github.com/VocaHQ/vocalinux) is AGPL-3.0, supports
whisper.cpp / Whisper / VOSK, runs on X11 and Wayland, has voice commands for
text manipulation, and — notably — offers **Vulkan GPU acceleration** across AMD,
Intel and NVIDIA.

**Choose Vocalinux** if you have a capable GPU and want to use it, or you want to
pick between three recognition engines.

**Choose YazSes** if you need macOS or Windows too (Vocalinux is Linux-only), if
you want the same install to also transcribe recordings and capture meetings with
speaker labels, or if you need the accessibility-oriented pieces —
dysfluency-friendly mode, EMG triggering, VAD calibration — and the opt-in
on-device learning loop.

YazSes deliberately targets **CPU int8** rather than GPU, so it runs on modest
hardware; if you have the GPU, a whisper.cpp-based tool will transcribe faster.

### YazSes vs TalkType

[TalkType](https://github.com/ronb1964/TalkType) is the closest thing to YazSes on
Linux: it is offline, Whisper-based, Wayland-first, and uses the **same
hold-to-talk gesture** — press a key to talk, release to type. It ships as a
zero-config AppImage with optional GPU acceleration.

**Choose TalkType** if you want a single-file AppImage with nothing to configure,
and Linux is the only machine you dictate on.

**Choose YazSes** if you also work on macOS or Windows, if you want the same
install to transcribe existing recordings and capture meetings with speaker
labels, or if you need the accessibility and voice-command layers.

### YazSes vs Wispr Flow

**Choose Wispr Flow** if you want polished, cloud-based AI formatting and
rewriting and do not need offline operation or Linux support.

**Choose YazSes** if the audio must not leave the machine, if you are on Linux,
or if you do not want a subscription. This is the clearest trade-off on the page:
cloud polish versus local privacy.

### YazSes vs Willow Voice

**Choose Willow** if you want a polished commercial product on Mac, Windows or
iPhone, with cloud-grade accuracy on technical vocabulary and a support contract
behind it. It is a genuinely fast, well-made tool and it does things a laptop CPU
cannot.

**Choose YazSes** if you are on Linux, or if the audio genuinely must not leave
the machine.

One point is worth stating precisely, because it is easy to misread from
comparison tables (including Willow's own, which lists Willow's offline support
as an "optional mode"). Willow's **Private Mode is a retention control, not local
processing.** Willow's privacy policy says plainly that "Willow uses cloud
infrastructure to provide fast and accurate voice dictation, transcription,
note-taking, and related features", and describes Private Mode as processing
audio "transiently to return a transcription" without retaining it or training on
it. That is a real and meaningful privacy commitment — no retention, no training,
plus SOC 2 and HIPAA compliance — and for most users it is enough.

It is simply a different guarantee from the one this project makes. "We do not
keep your audio" requires you to trust an operator, a policy, and a network path.
"Your audio never left the machine" is a property of where the software runs, and
you can verify it with `tcpdump`. Neither is automatically the right answer:
if your threat model is a vendor mishandling data, Willow's compliance posture
may be worth more than a self-hosted tool with no auditor. If your threat model
includes the network itself, or you work under a rule that forbids third-party
processing at all, no retention policy substitutes for the audio not being sent.

Checked against Willow's published privacy policy on 2026-08-15; verify before
relying on it, since vendor policies change.

### YazSes vs browser-extension dictation (Voice In, Google Docs voice typing)

**Use a browser extension** if everything you dictate lives in a browser tab.
[Voice In](https://dictanote.co/voicein/) works across Chrome and Edge on
thousands of sites in 50+ languages, installs in seconds, and has a free tier —
for dictating into Gmail, Notion or a web CRM it is the lowest-friction option on
this page. Google Docs' built-in voice typing is similar, and narrower still.

**Choose YazSes** when the text has to go somewhere a tab cannot reach. The
limitation is structural, not a quality gap: a browser extension can only type
into pages the browser renders. It cannot dictate into your terminal, your
editor, an SSH session, a native desktop app, or an IDE. YazSes injects at the
OS level, so the target window is not special to it.

Two things not to assume about browser dictation: it is usually **not offline**
(the browser's speech engine typically streams audio to the platform vendor even
when the extension itself stores nothing), and it does not do voice commands.

### YazSes vs Google / Apple / Windows built-in dictation

**Use the built-in** if it is already good enough and you are comfortable with
cloud processing (Google), a walled ecosystem (Apple), or Windows-only
(Windows Speech Recognition). They cost nothing and need no setup.

**Choose YazSes** if you want the same dictation behaviour across all three
operating systems, need it to work with no network, or want voice commands that
the built-ins largely do not offer. Note that Linux has no comparable built-in at
all — that gap is the reason this project exists.

### YazSes vs Whisper + your own scripts

**Roll your own** if you enjoy building and maintaining the glue.

**Choose YazSes** if you would rather not: it *is* that glue, productized and
tested — hotkey capture across multiple keyboards, VAD calibration, pre-speech
padding, command grammar, text injection that works on X11 *and* Wayland *and* in
terminals, a no-text-target guard, mic-change auto-healing, and packaging for
APT/Snap/PyPI.

### YazSes vs the dictation built into your editor or AI coding tool

VS Code, Cursor and several AI coding assistants ship their own voice input, and
for typing a prompt into that tool's own box they are the path of least
resistance. The limitation is structural rather than a matter of quality:
**in-application dictation only reaches what the application owns.**

YazSes types at the **operating-system level** — `ydotool` on Wayland, `xdotool`
on X11 — into whichever window currently has focus. Nothing about the target
window is special to it, so it does not care whether the shell behind that window
is local, SSH'd, containerised or on the other side of the planet.

The practical consequence, and the reason developers working on remote machines
tend to notice it first:

| Typing target | In-app dictation | YazSes |
|---|---|---|
| That tool's own prompt box | ✅ | ✅ |
| **VS Code / Cursor Remote-SSH editor pane** | often not | ✅ |
| **Integrated terminal running a remote shell** | often not | ✅ |
| A separate terminal with `ssh` / `tmux` / `mosh` | ❌ | ✅ |
| A shell inside a Docker container or VM | ❌ | ✅ |
| Any other window you alt-tab to | ❌ | ✅ |

If most of your work happens over Remote-SSH — editing on a server, driving a
build box, working in a container — this is the single biggest day-to-day
difference, and it needs no configuration: install YazSes and dictate.

Details and the forwarding case (text typed on a *remote host's own display*):
[dictation over SSH](how-to/remote-dictation.md).

### YazSes vs Handy

[Handy](https://github.com/cjpais/Handy) is the closest thing to a direct
comparison: MIT-licensed, free, genuinely cross-platform (Linux, macOS, Windows),
on-device, and built around the same hold-a-key-and-speak loop. It is popular for
good reason.

**Choose Handy** if you want dictation and nothing else, with the smallest install
and the least to configure. It does one job and does not ask you to care about
anything else.

**Choose YazSes** if you also want the things that are not dictation: a documented
voice-command grammar, whole-meeting capture with speaker labels, offline
transcription of existing recordings, and a configuration surface deep enough to
tune the silence gate, the disfluency filter and per-application tone.

The four adjectives people reach for — open source, local, cross-platform, free —
describe both. They are not a differentiator, and this page would be dishonest if
it implied otherwise.

### YazSes vs OpenWhispr

[OpenWhispr](https://github.com/OpenWhispr/openwhispr) is MIT-licensed, runs on
macOS, Windows and Linux, and transcribes locally with Whisper, Parakeet or
Nemotron models. It also accepts spoken instructions such as "clean this up", and
can optionally use a cloud model with your own API key.

**Choose OpenWhispr** if you want a polished desktop app and regard an optional
cloud fallback as a feature rather than a dealbreaker.

**Choose YazSes** if "offline" needs to mean *there is no cloud path at all* —
YazSes ships no remote inference of any kind, and the one place a local LLM
endpoint can be configured refuses a non-loopback address unless you explicitly
opt out. Also if you want speaker-labelled meeting transcripts, or published
benchmark numbers with a method attached.

### YazSes vs FluidVoice

[FluidVoice](https://github.com/altic-dev/FluidVoice) is GPLv3, macOS-first, built
on Parakeet, and has both a Write Mode and a Command Mode that can drive the OS
itself — launching apps and running Shortcuts.

**Choose FluidVoice** if you are on macOS and want voice control of the *machine*,
which is broader than what YazSes's editor-oriented command grammar does.

**Choose YazSes** if you are on Linux (FluidVoice announces it but does not ship
it) or want the same experience across all three desktops.

### Others in this space

[Whispering](https://github.com/epicenter-so/epicenter),
[VoiceInk](https://github.com/Beingpax/VoiceInk) (macOS, paid) and
[VOXD](https://github.com/jakovius/voxd) are also active open-source offline
dictation projects, mostly built on whisper.cpp.

[Speech Note](https://github.com/mkiol/dsnote) is worth calling out separately
because it is a **different shape of tool**: a notepad application you dictate
*into*, which also does text-to-speech and offline translation. If you want a
document to write in rather than dictation injected into whatever window has
focus, it is the better fit — and it does more than YazSes on translation.

These are worth a look if the tools above do not fit; this page is a comparison,
not a claim that YazSes wins every case.

## Common questions

**Is there a good open-source, offline alternative to Dragon or Wispr Flow on
Linux?** Yes — YazSes is an open-source (Apache-2.0), fully offline dictation tool
that runs on Linux, macOS, and Windows and needs no cloud account.

**What's the best free voice dictation for Linux that also does commands?** YazSes
combines on-device transcription with a voice-command grammar, so the same
hold-to-talk key both types text and triggers editor/terminal actions.

**Does YazSes send my audio anywhere?** No. Transcription runs locally with
faster-whisper; by default nothing leaves your machine.

**Does voice dictation work over SSH, or in a VS Code Remote-SSH session?** Yes,
with no extra setup. YazSes injects keystrokes at the operating-system level into
the focused window, not inside a particular application, so Remote-SSH editor
panes, integrated terminals running a remote shell, `tmux` sessions and container
shells all receive dictated text normally. This is where it differs most from the
voice input built into editors and AI coding tools, which is bound to that
application's own input handling.

**Is there an offline, open-source alternative to Otter.ai for meeting notes?**
Yes. `yazses meeting start` / `yazses meeting stop` records a meeting hands-free
and produces a speaker-labelled transcript on-device, with optional minutes from a
local LLM — no account, no per-seat fee, and no bot joining the call. It records
the room through your microphone rather than capturing a video call's system
audio; see [Offline meeting notes](meeting-notes-offline.md).

**Can I transcribe an existing recording offline?** Yes —
`yazses transcribe interview.m4a` converts any audio or video file to txt, md,
srt, vtt, or json, with `--diarize` for who-said-what speaker tags.

**What is the best open-source dictation tool for Linux?** It depends on what you
weight. nerd-dictation is the most minimal, Vocalinux has GPU acceleration, Talon
is the most powerful for voice *control*, and YazSes is the one that is
cross-platform and covers dictation, file transcription and meeting capture from a
single install. All four are free and run offline; the sections above lay out the
trade-offs honestly.

**Does YazSes work on Wayland?** Yes. It probes the session at runtime and injects
text through `ydotool` or `wtype` on Wayland and `xdotool` on X11. This is the
part that most Linux dictation tools struggle with — see
[voice dictation on Linux](use-cases/voice-dictation-linux.md).

**Is there an alternative to Dragon NaturallySpeaking for Linux?** Dragon does not
run on Linux at all. The closest open-source options are YazSes, Talon Voice,
Vocalinux and nerd-dictation. For general prose dictation the accuracy gap to
Dragon is modest; for specialist medical or legal vocabularies it is not.

## Honest limitations

- Accuracy is Whisper-class — **4.07 % WER** on LibriSpeech test-clean with the
  default model, [measured and reproducible](benchmarks.md). It is not tuned for
  specialized medical/legal vocabularies the way Dragon is, and real dictation in
  a room will be worse than a clean read-speech benchmark.
- On Wayland, global-hotkey and injection setup needs `ydotool`/`ydotoold`.
- The first run downloads the STT model.
- It is a dictation + command tool, **not** an LLM agent or a full voice-scripting
  platform like Talon.

---

Ready to try it? See **[Install on Linux](install-linux.md)** — or
`pipx install yazses` on any OS with Python ≥ 3.11.
