---
title: Release notes
description: YazSes release history — the current stable release, recent development previews, and the full changelog.
---

# Release notes

The canonical, always-current list of releases lives on GitHub. Each tagged
release there carries built artifacts and a signed source archive.

[:material-tag: All releases on GitHub](https://github.com/MSKazemi/yazses/releases){ .md-button .md-button--primary }
[:material-history: Full changelog](https://github.com/MSKazemi/yazses/blob/main/CHANGELOG.md){ .md-button }
[:simple-pypi: PyPI release history](https://pypi.org/project/yazses/#history){ .md-button }

## Follow the releases

Every release below is published to a feed, so you can follow YazSes without a GitHub
account, an email address, or a login of any kind — which is the same principle the
software itself runs on.

[:material-rss: RSS feed](https://mskazemi.com/yazses/feed_rss_created.xml){ .md-button }
[:material-code-json: JSON feed](https://mskazemi.com/yazses/feed_json_created.json){ .md-button }

## Current stable

**[YazSes 2.26.0](v2.26.0.md)** — when dictation stops, you find out. A microphone that hears you but yields nothing
never tripped the guard built for exactly that; the device-change watcher cannot see a
switch behind a PipeWire alias, so both now name the microphone actually in use; and
`gitvoice` truncated a branch name before aiming a destructive command at what was left.
Install it with:

```sh
pipx install yazses          # any OS, Python ≥ 3.11
pipx upgrade yazses          # upgrade an existing install
```

### Recent stable releases

- [v2.26.0](v2.26.0.md) — a mic that hears you but yields nothing now trips the guard; `default` is named as the route it is; `gitvoice` no longer truncates a branch name before deleting it.
- [v2.25.1](v2.25.1.md) — nine fixes, one theme: commands that printed something confident and wrong — a mic check suppressed when it mattered, silence transcribed as a word, a corpus size 430x low.
- [v2.25.0](v2.25.0.md) — confident answers that were wrong: an empty transcript reported as success; speaker flags that invented or ignored counts; a privacy guard that answered differently per Python.
- [v2.24.0](v2.24.0.md) — two privacy controls that never ran; a report that leaked your account name; a doctor that called a stale daemon healthy.
- [v2.23.0](v2.23.0.md) — the overlay ignored your desktop's reduce-motion setting; the mic guard's question could only be answered with a pointer.
- [v2.22.0](v2.22.0.md) — the Intel `.dmg` and ARM64 `.exe` exist for the first time; five launch paths that could not work in a bundle; the macOS download halves.
- [v2.21.0](v2.21.0.md) — guards that passed by checking nothing; a crashed daemon that stayed dead on Windows; `yazses features` prices what it offers.
- [v2.20.0](v2.20.0.md) — the Windows release that works: model download explains itself, the CLI is reachable, the icon ships.
- [v2.19.0](v2.19.0.md) — About / Help / Check for updates in the tray; three commands rejoin the CLI reference; AUR + Fedora packages.
- [v2.18.2](v2.18.2.md) — cutting a release could not publish to PyPI; the manifest gate deadlocked on its own tag.
- [v2.18.1](v2.18.1.md) — the resemblyzer and pyannote backends ship; pyannote's default-on telemetry disabled; eleven Windows defects.
- [v2.18.0](v2.18.0.md) — Qt becomes the `desktop` extra: a headless install is ~650 MB lighter.
- [v2.17.0](v2.17.0.md) — streaming no longer deletes text it never typed; snap names both interfaces; autostart on start.
- [v2.16.0](v2.16.0.md) — the snap becomes whole: bundled feature libraries; honest refusal for what cannot fit.
- [v2.15.1](v2.15.1.md) — `err` is a verb (contract 4.0.0 → 5.0.0); mypy 73 → 0.
- [v2.15.0](v2.15.0.md) — the honesty release (contract 1.1.0 → 4.0.0, supply-chain fix).
- **v2.14.0** — the perception release: Parakeet TDT, gaze deixis, sotto-voce, EMG seam.
- **v2.13.0** — the reliability release: config self-repair, `yazses verify`, supervised tray.
- **v2.12.0** — the first stable v2 release.

## Development previews

The v2 line shipped as a long series of `dev` previews before stabilising at
2.12.0. The per-preview notes are archived here (newest first):

- [v2.11.0-dev.1](v2.11.0-dev.1.md)
- [v2.10.0-dev.5](v2.10.0-dev.5.md) · [dev.4](v2.10.0-dev.4.md) · [dev.3](v2.10.0-dev.3.md) · [dev.2](v2.10.0-dev.2.md) · [dev.1](v2.10.0-dev.1.md)
- [v2.9.0-dev.5](v2.9.0-dev.5.md) · [dev.4](v2.9.0-dev.4.md) · [dev.3](v2.9.0-dev.3.md) · [dev.2](v2.9.0-dev.2.md) · [dev.1](v2.9.0-dev.1.md)
- [v2.8.0-dev.5](v2.8.0-dev.5.md) · [dev.4](v2.8.0-dev.4.md) · [dev.3](v2.8.0-dev.3.md) · [dev.2](v2.8.0-dev.2.md) · [dev.1](v2.8.0-dev.1.md)
- [v2.7.0-dev.5](v2.7.0-dev.5.md) · [dev.4](v2.7.0-dev.4.md) · [dev.3](v2.7.0-dev.3.md) · [dev.2](v2.7.0-dev.2.md) · [dev.1](v2.7.0-dev.1.md)
- [v2.6.0-dev.5](v2.6.0-dev.5.md) · [dev.4](v2.6.0-dev.4.md) · [dev.3](v2.6.0-dev.3.md) · [dev.2](v2.6.0-dev.2.md) · [dev.1](v2.6.0-dev.1.md)
- [v2.5.0-dev.5](v2.5.0-dev.5.md) · [dev.4](v2.5.0-dev.4.md) · [dev.3](v2.5.0-dev.3.md) · [dev.2](v2.5.0-dev.2.md) · [dev.1](v2.5.0-dev.1.md)
- [v2.4.0-dev.2](v2.4.0-dev.2.md) · [dev.1](v2.4.0-dev.1.md)
- [v2.3.0-dev.2](v2.3.0-dev.2.md) · [dev.1](v2.3.0-dev.1.md)
- [v2.2.0-dev.2](v2.2.0-dev.2.md) · [dev.1](v2.2.0-dev.1.md)
- [v2.1.0-dev.5](v2.1.0-dev.5.md) · [dev.4](v2.1.0-dev.4.md) · [dev.3](v2.1.0-dev.3.md) · [dev.2](v2.1.0-dev.2.md) · [dev.1](v2.1.0-dev.1.md)
- [v2.0.0-dev.4](v2.0.0-dev.4.md) · [dev.3](v2.0.0-dev.3.md) · [dev.2](v2.0.0-dev.2.md) · [dev.1](v2.0.0-dev.1.md)

## Previous stable line

- [v1.4.1](v1.4.1.md) — the final v1 release.
