# YazSes public media catalog

This catalog distinguishes **approved-to-share** social assets from **candidates needing review**.

## Approved media packs

The project already publishes two packs as **free to use** on [Share your contribution](../../docs/contribute/share.md); they are listed here so this catalog and that page agree. Neither has a media-specific license identifier (SPDX or Creative Commons) recorded yet; when a maintainer chooses one, record it here and on that page. Any further item is approved only after its rights, media-specific license, and content have been reviewed.

| Pack | Files | Notes | Status |
|---|---|---|---|
| Contributor share images | [`docs/assets/share/`](../../docs/assets/share/): poster, two reel covers, a contact and download card, two QR codes | 9:16 portrait; the QR codes open the latest release | approved: published as free to use |
| Contributor reels | [Reel 1](https://github.com/MSKazemi/yazses/releases/download/media-kit/yazses-reel-1.mp4) and [Reel 2](https://github.com/MSKazemi/yazses/releases/download/media-kit/yazses-reel-2.mp4) on the [`media-kit` pre-release](https://github.com/MSKazemi/yazses/releases/tag/media-kit) | Release assets, not committed to Git | approved: published as free to use |

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
