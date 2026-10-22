---
title: What we're building now — YazSes development status
description: "The live development status of YazSes, offline voice dictation for Linux, macOS and Windows: the latest release, every change on main that is not released yet, recent releases, how the project is built and tested, and where to join in."
---

# What we're building now

YazSes is developed in the open, and this page shows where it stands. The sections marked
*generated* are produced from the repository each time the site is built: from
[`CHANGELOG.md`](https://github.com/MSKazemi/yazses/blob/main/CHANGELOG.md) and the
[release notes](releases/index.md). They are as current as the site, and they cannot say
anything the changelog does not.

For where the project is *going*, read the [roadmap](roadmap.md). This page covers what is
happening now.

## Latest release

*Generated.*

<!-- yazses-status:latest -->

[:material-download: Install or upgrade](get-started.md){ .md-button .md-button--primary }
[:material-tag: All releases on GitHub](https://github.com/MSKazemi/yazses/releases){ .md-button }

## On `main`, not yet released

*Generated.* Each item below is a change that has landed on `main` with its tests and will
ship in the next release. Each one is a heading in the changelog's `[Unreleased]` section,
where the full entry explains what changed and why.

<!-- yazses-status:unreleased-summary -->

<details markdown="1">
<summary>Every unreleased change, grouped by kind</summary>

<!-- yazses-status:unreleased -->

</details>

Want one of these before it is released? Install from `main` with
`pipx install git+https://github.com/MSKazemi/yazses` and report what you find. A test on
real hardware is the most useful contribution there is.

## Recent releases

*Generated.* Every release has a notes page that says what changed and how to upgrade.

<!-- yazses-status:recent-releases -->

Follow new releases without an account: [RSS](https://mskazemi.com/yazses/feed_rss_created.xml) ·
[JSON Feed](https://mskazemi.com/yazses/feed_json_created.json) · [GitHub releases](https://github.com/MSKazemi/yazses/releases).

## How YazSes is built

A small set of rules holds every change in place. Tests enforce them; a reviewer does not
have to remember them.

| Rule | What it means for you | Where it is held |
|---|---|---|
| **Nothing leaves the machine** | Audio, transcripts and the learning corpus stay on your computer. No telemetry, analytics or crash reporting. | A test fails the build when a module gains a network call that is not registered and classified ([ADR-019](design/adr/adr-019-egress-inventory-and-escalation.md)) |
| **New features ship off** | Upgrading never changes what your install does until you switch something on. | Every feature has a config section whose default is dormant ([features](features.md)) |
| **Heavy dependencies are optional** | The base install stays small. Torch, ONNX, Qt and similar libraries arrive only with the feature that needs them. | Optional extras, imported lazily, and a test that a disabled feature costs a default start nothing |
| **Pure logic, injected backends** | The decision-making code is unit-tested directly, without a microphone or a model. | The [architecture](architecture.md): pure modules beside swappable engines |
| **Every OS behind one interface** | Linux, macOS and Windows differences live in one place, which is also what makes an Android port possible. | Protocols in `platform/base.py` ([platform support](platform-support.md)) |
| **Tests come with the change** | A behaviour change arrives with the test that proves it. | The suite runs on Linux, macOS and Windows for every push and pull request |
| **Decisions are written down** | You can read *why* something works the way it does, including what was declined. | [Architecture decision records](design/adr/index.md) |

The code is Python 3.11+, managed with [`uv`](https://docs.astral.sh/uv/). Speech-to-text
is [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU by default;
[NVIDIA Parakeet TDT and Moonshine](models.md) are opt-in engines. The full stack is in the
[architecture overview](architecture.md) and its [diagrams](diagrams/index.md).

## Where the work is organised

- **[Milestones](https://github.com/MSKazemi/yazses/milestones)**. Each one is an
  outcome you can help reach: the Settings window, installing anywhere, hearing better,
  voice control, the first-hour experience, hands-free input, and Android.
- **[Roadmap](roadmap.md)**. The direction, from dictation tool to keyboard-optional
  computing, and the principles that do not move.
- **[Research](research/index.md)**. The cited science behind each design choice, plus
  [open questions](research/agenda.md) for students and researchers.
- **[Discussions](https://github.com/MSKazemi/yazses/discussions)**. Ideas, questions and
  show-and-tell.

## Join in

Most first contributions need no knowledge of the codebase, and many need no code at all:
testing on your own hardware, translating, adding a microphone that worked for you, or
improving a page like this one.

[:material-hand-heart-outline: Find a task that fits](contribute/start.md){ .md-button .md-button--primary }
[:material-github: Open issues](https://github.com/MSKazemi/yazses/issues){ .md-button }
[:material-robot-outline: Contributing with an AI agent](contribute/ai-agents.md){ .md-button }
