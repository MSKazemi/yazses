# YazSes public media catalog

This catalog distinguishes **approved-to-share** social assets from **candidates needing review**.

Status values: `proposed` (submitted, not reviewed), `approved` (reviewed, licensed, free to reuse), `outdated` (kept for
history; do not promote), `candidate` (exists in the repository, not yet a pack). Only `approved` rows may be reused, under
the licence in their **License** column; new packs are [CC BY 4.0](LICENSE.md).

## Approved media packs

The project already publishes two packs as **free to use** on [Share your contribution](../../docs/contribute/share.md); they are listed here so this catalog and that page agree. They were published before the media licence and stay free to use with no credit needed. Any further item is approved only after its rights, licence and content have been reviewed, and carries its licence in the **License** column.

| Pack | Files | Notes | Status | License |
|---|---|---|---|---|
| Contributor share images | [`docs/assets/share/`](../../docs/assets/share/): poster, two reel covers, a contact and download card, two QR codes | 9:16 portrait; the QR codes open the latest release | approved: published as free to use | Free to use, no credit needed (published before the media licence) |
| Contributor reels | [Reel 1](https://github.com/MSKazemi/yazses/releases/download/media-kit/yazses-reel-1.mp4) and [Reel 2](https://github.com/MSKazemi/yazses/releases/download/media-kit/yazses-reel-2.mp4) on the [`media-kit` pre-release](https://github.com/MSKazemi/yazses/releases/tag/media-kit) | Release assets, not committed to Git | approved: published as free to use | Free to use, no credit needed (published before the media licence) |
| Carousel: What YazSes is | [`carousels/01-what-it-is/`](carousels/01-what-it-is/): 7 slides (`slide-01.png` to `slide-07.png`), `alt-text-en.md`, `caption-en.md` | Instagram, English, 1080 x 1350 PNG; hold a key, speak, it types; the default hotkey per OS; speed | approved | [CC BY 4.0](LICENSE.md) |
| Carousel: Install on Linux | [`carousels/02-install-linux/`](carousels/02-install-linux/): 7 slides (`slide-01.png` to `slide-07.png`), `alt-text-en.md`, `caption-en.md` | Instagram, English, 1080 x 1350 PNG; the one-line installer, `--dry-run`, `yazses doctor`, other channels | approved | [CC BY 4.0](LICENSE.md) |
| Carousel: Install on macOS and Windows | [`carousels/03-install-mac-windows/`](carousels/03-install-mac-windows/): 7 slides (`slide-01.png` to `slide-07.png`), `alt-text-en.md`, `caption-en.md` | Instagram, English, 1080 x 1350 PNG; Homebrew, winget, the unsigned-build warnings, `yazses doctor` | approved | [CC BY 4.0](LICENSE.md) |
| Carousel: Your first five minutes | [`carousels/04-first-five-minutes/`](carousels/04-first-five-minutes/): 7 slides (`slide-01.png` to `slide-07.png`), `alt-text-en.md`, `caption-en.md` | Instagram, English, 1080 x 1350 PNG; `quickstart`, `doctor`, `mic-level --set`, `start`, `verify`, `autostart` | approved | [CC BY 4.0](LICENSE.md) |
| Carousel: Configure it | [`carousels/05-configure/`](carousels/05-configure/): 7 slides (`slide-01.png` to `slide-07.png`), `alt-text-en.md`, `caption-en.md` | Instagram, English, 1080 x 1350 PNG; hotkey, pinned microphone, the accuracy and speed trade-off, other languages, vocabulary | approved | [CC BY 4.0](LICENSE.md) |
| Carousel: Voice commands | [`carousels/06-voice-commands/`](carousels/06-voice-commands/): 7 slides (`slide-01.png` to `slide-07.png`), `alt-text-en.md`, `caption-en.md` | Instagram, English, 1080 x 1350 PNG; undo, go to line, voice punctuation, the command key, macros | approved | [CC BY 4.0](LICENSE.md) |
| Carousel: Transcribe files offline | [`carousels/07-transcribe-files/`](carousels/07-transcribe-files/): 7 slides (`slide-01.png` to `slide-07.png`), `alt-text-en.md`, `caption-en.md` | Instagram, English, 1080 x 1350 PNG; `yazses transcribe`, output formats, `--diarize`, Docker with no network | approved | [CC BY 4.0](LICENSE.md) |
| Carousel: Meeting mode | [`carousels/08-meeting-mode/`](carousels/08-meeting-mode/): 7 slides (`slide-01.png` to `slide-07.png`), `alt-text-en.md`, `caption-en.md` | Instagram, English, 1080 x 1350 PNG; who-said-what transcripts with no bot, voiceprints you enroll, optional minutes | approved | [CC BY 4.0](LICENSE.md) |
| Carousel: Privacy you can check | [`carousels/09-privacy-and-numbers/`](carousels/09-privacy-and-numbers/): 7 slides (`slide-01.png` to `slide-07.png`), `alt-text-en.md`, `caption-en.md` | Instagram, English, 1080 x 1350 PNG; the test that enforces offline, benchmarks, honest limits, the install cost | approved | [CC BY 4.0](LICENSE.md) |
| Video: how a dictation flows through the nine stages | [heart voice](https://github.com/MSKazemi/yazses/releases/download/media-kit/pipeline-animation-en-heart-1080x1920.mp4), [michael voice](https://github.com/MSKazemi/yazses/releases/download/media-kit/pipeline-animation-en-michael-1080x1920.mp4); [thumbnail, transcript](videos/pipeline-animation/) | Reels / Shorts / TikTok, English, 1080 x 1920 MP4, 26 s, 7.2 MB each, same animation with two synthetic voices; sha256 `f321b501…f2a2` (heart), `17352604…7d67` (michael) | approved | [CC BY 4.0](LICENSE.md) |

## Provenance of the packs above

- **Creator and rights holder:** the YazSes project (Mohsen Seyedkazemi Ardebili). Licence for all rows added on 2026-11-05: [CC BY 4.0](LICENSE.md).
- **What was checked on 2026-11-05, against v2.49.0:** every number, default and command on the nine carousels' alt text was compared with the current docs and
  CLI (word error rates, decode times, install and model sizes, the diarization download, default hotkeys, the install channels), and the 19 facts shown in the
  video were re-matched to `docs/architecture.md`. Every QR code target on the slides returned HTTP 200. The files are byte-identical to the exports whose
  checksums were recorded when they were made.
- **Third-party material:** none. The narration is synthetic speech from Kokoro-82M (Apache-2.0), run offline. Fonts (Ubuntu Sans, Inter, JetBrains Mono) appear
  only as rendered text. The slides contain QR codes that open the project's own pages. No real user speech, transcript or screenshot is used.
- **Not shown on the slides and not claimed:** that any feature was tried on real hardware. For that, read the [release notes](../../docs/releases/index.md).
- **Held back:** the tenth carousel, "Turn on what you need". It says a recommended set of *ten* features switches on at first start; `yazses features --tier rec`
  lists nine and `docs/features.md` says eight. It returns when the number is corrected at the source.
- **A caption is a draft to adapt.** The captions point to a link in bio because Instagram does not make caption links clickable.

## Candidate materials already in this repository

These links are useful starting points for creating ready-to-post media packs. **Candidate** does not mean blanket permission to repost beyond applicable licenses and permissions.

| Candidate | Files | Notes | Status |
|---|---|---|---|
| Short product walkthrough | [YazSes reel GIF](../../docs/screenshots/yazses-reel.gif), [WebP](../../docs/screenshots/yazses-reel.webp) | Existing demo displayed in project README; check current features, accuracy of captions and rights | candidate |
| Desktop UI screenshots | [Screenshots directory](../../docs/screenshots/) | Tray, settings, overlay and diagnostics; curate and redact if necessary | candidate |
| Project social preview | [OG card](../../docs/screenshots/og-card.png) | Could be reused as a post cover once reviewed | candidate |

## Media pack entry template

Copy the following for each new pack:

```md
### <Pack title>

- **Status:** proposed
- **Purpose:** <what people will learn>
- **Audience / platforms:** <e.g. new users; Instagram / TikTok / YouTube>
- **Language:** <locale>
- **Files:** <ordered files or final export links>
- **Format / size:** <e.g. 1080x1350 PNG; 1080x1920 MP4>
- **Creator / rights holder:** <name or organization>
- **License:** <SPDX / CC identifier or link; explicit permission required>
- **Attribution:** <exact credit and license link to retain>
- **Third-party material:** <none, or exact rights and credits>
- **Suggested caption:** <plain text with installation link>
- **Alt text / subtitles:** <link>
- **Reviewed for:** current features, installation steps, privacy, permissions
- **Reviewed by / date:** <maintainer and YYYY-MM-DD>
```

When the license and all rights are confirmed, a maintainer can change the status to `approved`. If a claim, logo, instruction or UI has become obsolete, change the status to `outdated` and avoid promoting it as current.

For publishing instructions, see [README.md](README.md).
