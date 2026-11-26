---
description: >-
  Draft text for an evergreen research issue on the Meta Neural Band as a YazSes switch. Records the unofficial community tools and their licences, the Meta-account enrolment, protocol and firmware risk, Meta's official preview scope, and when to revisit.
---

# Draft issue — Meta Neural Band as a switch: research only, revisit on a trigger

**Status:** Draft issue text (2026-11-20). **The GitHub issue has not been created.** A
maintainer files it, if at all. It proposes no code, dependency, config key or default.
**Source:** item M7 of the [November 2026 start plans](2026-11-19-landscape-start-plans.md#m7--meta-neural-band-gesture-adapter) and the [landscape note](2026-11-19-offline-voice-tech-landscape.md#the-meta-neural-band-is-the-first-mass-market-wrist-switch-reachable-only-unofficially)
**Governing records:** [ADR-030 freeze and its 2026-11-01 amendment](../adr/adr-030-agent-era-direction.md) (new device families stay frozen), [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md), [ADR-v2-152](../adr/adr-v2-152-biosignal-artifact-switches.md), [ADR-v2-153](../adr/adr-v2-153-biosignal-false-positive-governor.md)

Everything below the line is the proposed issue: title, labels and body.

---

**Title:** Research: Meta Neural Band as a YazSes switch — unofficial access only, revisit on an official desktop SDK or a real user

**Labels:** `evergreen:research`. No milestone, per the [milestone policy](../milestone-policy.md).

## Question

Can the Meta Neural Band, a mass-market, calibration-free sEMG wristband, serve as an
offline YazSes switch on a desktop, without YazSes advertising something that a firmware update
can silently break?

**Answer today: not yet.** This issue records why, and what would change the answer. ADR-030
§3 and its 2026-11-01 amendment keep new device families frozen. A proposal like this one stops
at an `evergreen:research` issue.

## Why it is interesting

- Meta's generic sEMG decoder works across people without per-user calibration. This is
  reported in Nature 645, 702–711 ([RePEc landing page](https://ideas.repec.org/a/nat/nature/v645y2025i8081d10.1038_s41586-025-09255-w.html)),
  as relayed by the landscape note and not re-read here.
- Discrete gestures (thumb swipe, finger tap, pinch) are intentional motor events. They fit the
  existing switch path: detector → abstract event → action ([ADR-v2-152](../adr/adr-v2-152-biosignal-artifact-switches.md)).
- `docs/research/muscle-brain-control.md` still says the band has "no raw EMG for third parties"
  and is "Not readable". The community tools below suggest that is out of date. Correcting it
  is a docs task, separate from this issue.

## What Meta offers officially (checked 2026-11-20)

Meta's developer blog of 2026-05-14, ["The wait is over: Build for display glasses starting today"](https://developers.meta.com/blog/build-for-display-glasses/),
describes **two developer-preview paths for Meta Ray-Ban Display**:

- the Wearables Device Access Toolkit, a native SDK for iOS (Swift) and Android (Kotlin);
- Web Apps in HTML, CSS and JavaScript, which "can access … Neural Band input".

Both are in developer preview, with sharing limited to up to 100 testers per channel. **The page
names no desktop, PC or Mac path**, and does not say which band gestures or events reach
developers. So there is **no official desktop access to the band** today. "Only phone and web
apps for the glasses" is what the page shows; whether that excludes a desktop SDK on Meta's
roadmap is `[Unknown]`.

## Community projects (checked on their GitHub pages 2026-11-20)

All three are unofficial and reverse-engineered. None is endorsed by Meta.

| Project | What it does | Licence | Verified how |
|---|---|---|---|
| [callbacked/kinesis](https://github.com/callbacked/kinesis) | macOS menu-bar app (macOS 14+): gestures switch desktops, open Mission Control, control music, pinch-and-turn volume and brightness. Labelled "highly experimental". Builds on the author's `neural-band-poc` | **MIT** (repository sidebar) | GitHub page read |
| [896kb/air-gestures](https://github.com/896kb/air-gestures) (a mirror; the primary is on GitLab, `gitlab.com/896kb/air-gestures`) | Linux daemon and CLI in Rust, described as a "Rust port of callbacked/kinesis", on BlueZ. Thumb swipes, index and middle taps and holds, pinch-and-turn, each running a user-configured shell command; also a control socket, a waybar module and a raw sEMG viewer. Tested on one band with Arch, BlueZ and Hyprland. Companion Android app [896kb/air-gestures-android](https://github.com/896kb/air-gestures-android) | **MIT**. The repository has `LICENSE` plus `LICENSE-kinesis` carrying kinesis's MIT notice. The project site [band.896.ro](https://band.896.ro/) says "Open source, MIT licensed" and "Not affiliated with Meta" | GitHub page and project site read. Android app licence from search results only `[Unverified]` |
| RawMeta (Triton NeuroTech, UCSD) | macOS recorder for raw 8-channel, 2048 Hz EMG at about 60 ms latency, publishing an LSL stream | **MIT according to [Mixed News, 2026-10-13](https://mixed-news.com/en/rawmeta-meta-neural-band-eight-channel-2048hz-emg-recorder/)** `[Secondary]` | **Not verifiable on GitHub.** The workshop repository [Triton-Neurotech/EMG-Workshop](https://github.com/Triton-Neurotech/EMG-Workshop) links `github.com/Triton-Neurotech/RawMeta`, but that URL returned 404 on 2026-11-20, and the organisation lists no such public repository. It may be private, renamed or removed `[Unknown]` |

## The enrolment step is outside YazSes's offline boundary

Every route needs a **one-time Meta-account step**:

- kinesis: "sign in with Meta once". It stores the session token in the keychain, and later
  connections do not need Meta (README).
- air-gestures: "Claiming needs a one-time Meta sign-in on Meta's own page; after that,
  connecting uses only a locally stored key." Claiming also unlinks the band from Meta's glasses
  and phone app until a factory reset (README; site).
- RawMeta: enrolment is "tied to a Meta account", and after it "no internet or Meta account is
  needed" `[Secondary]` (Mixed News).

Even if nothing is sent during use, **setup needs a cloud account and a network sign-in with a
third party.** YazSes must never perform, proxy or automate that step. It would be a new egress
path under [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md), and a credential flow
AGENTS.md forbids an agent to handle. If an adapter is ever built, it consumes a band **already
claimed by a separate tool the user ran themselves**. The docs must say plainly that the
enrolment happens outside YazSes and involves Meta's servers.

## Protocol and firmware risk

- **Is the link encrypted? Sources disagree.** Notebookcheck (2026-09-15) says kinesis decoded
  the band's "unencrypted Bluetooth Low Energy (BLE) packet stream" `[Secondary]`
  ([article](https://www.notebookcheck.net/Open-Source-Kinesis-reverse-engineers-Meta-s-Neural-Band-for-muscle-Mac-controls.1399361.0.html)).
  Later sources describe an owner-key scheme. Mixed News says RawMeta's link is "encrypted and
  bound to one host" `[Secondary]`. air-gestures' README names "AirShield encryption" and
  "encryption scheme 26" on the September 2026 firmware it tested. Our reading, an inference
  `[Unknown]`: the BLE transport may be unencrypted at the link layer while the payload uses an
  application-level, owner-keyed scheme. Either way YazSes would be speaking a protocol Meta
  has not published.
- **Firmware can break it.** RawMeta's workshop page warns "A firmware update can break RawMeta"
  and "never pair the band with the Meta AI phone app", which is how firmware arrives.
  air-gestures says the tested firmware "differs from earlier versions" and "Meta can change it
  at any time"; its site says the protocol "can change with the band's firmware".
- **Pillar 1 consequence.** An adapter built on this would advertise a capability that can stop
  working overnight with no change on YazSes's side. ADR-030 Pillar 1 ("make what is advertised
  true before adding anything") forbids exactly that unless it is labelled unsupported and fails
  loudly.

## Conditions to revisit (any one)

1. **Meta publishes an official desktop path** (Linux, macOS or Windows) that exposes discrete
   band gestures to third-party software, under terms that allow offline use after setup.
2. **A real user asks.** A substantive issue from someone who is not a contributor and who owns
   a band and wants it as a YazSes switch. This is ADR-030 Pillar 4's leading signal and
   ADR-021's "investment follows evidence".
3. The ADR-030 freeze is lifted, or amended to name this device family. Any build still needs
   condition 1 or 2.

## If it is ever built

- **Reuse, don't invent.** Map band gestures onto the existing biosignal switch events
  (`biosignal/types.py::EventKind` and the ADR-v2-152 pipeline). Put every source behind the
  [ADR-v2-153 false-positive governor](../adr/adr-v2-153-biosignal-false-positive-governor.md),
  with its one-action release. Follow the BCI HID consumer plan (start plans, item M3) for the
  event mapping, so all discrete-switch sources share one path.
- **Prefer consuming an existing daemon to speaking BLE.** air-gestures already exposes a control
  socket and shell hooks. A thin YazSes source reading discrete gesture events from a tool the
  user installed keeps the reverse-engineered protocol out of YazSes. That trades protocol risk
  for a dependency on a third-party tool's interface, which also needs a stability check
  `[Unknown]`.
- **If YazSes ever speaks BLE itself:** off by default, a lazily imported BLE library as an
  optional extra (AGENTS.md rules 2–3), registered in the ADR-019 inventory beside
  `biosignal/myo.py`, the same "a radio, not an IP network" case. Never any Meta network call.
- **Discrete gestures only.** Raw EMG recording is a research tool, not a switch, and stays out
  of product scope.
- **Labelled unsupported and fragile**, with a `doctor` check that says so when the band stops
  answering, rather than failing silently.

## Not in scope

Building the adapter. Automating enrolment. Raw EMG capture. Any claim of support.

## Sources (fetched 2026-11-20 unless marked)

- [Meta developer blog, 2026-05-14](https://developers.meta.com/blog/build-for-display-glasses/)
- [callbacked/kinesis](https://github.com/callbacked/kinesis)
- [896kb/air-gestures](https://github.com/896kb/air-gestures) and [band.896.ro](https://band.896.ro/)
- [Triton-Neurotech/EMG-Workshop](https://github.com/Triton-Neurotech/EMG-Workshop); RawMeta repository URL returned 404
- [Mixed News on RawMeta, 2026-10-13](https://mixed-news.com/en/rawmeta-meta-neural-band-eight-channel-2048hz-emg-recorder/) (secondary)
- [Notebookcheck on kinesis, 2026-09-15](https://www.notebookcheck.net/Open-Source-Kinesis-reverse-engineers-Meta-s-Neural-Band-for-muscle-Mac-controls.1399361.0.html) (secondary)
- [Nature 645, 702–711 via RePEc](https://ideas.repec.org/a/nat/nature/v645y2025i8081d10.1038_s41586-025-09255-w.html) (relayed from the landscape note, not re-read)

Pages were read through a fetch tool that returns a summary rather than the full text. Quoted
phrases are as that summary gave them. Re-check them against the pages before filing.
