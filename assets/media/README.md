# YazSes public media library

**Create once. Share everywhere.**

This is the proposed home for **ready-to-post YazSes media**: finished images, social carousels, short videos, demo clips, thumbnails, subtitles, and accompanying captions. The goal is to let community members promote YazSes without design software, editing projects, or original production files.

**Current status:** library structure and publishing guidance, plus the two packs the project already publishes as free to use on [Share your contribution](../../docs/contribute/share.md) (the `docs/assets/share/` images and the `media-kit` release reels, listed in [CATALOG.md](CATALOG.md)). Before any other item is advertised as freely reusable, its rights and approved license must be recorded in the catalog. Other existing material elsewhere in this repository is not automatically an approved social-media pack.

## What to publish

- **Images:** final PNG, JPG, or WebP files in the resolution needed for posting.
- **Carousels:** every finished slide exported as `01.png`, `02.png`, etc., in order, plus one caption.
- **Videos:** final MP4 or WebM exports; optional cover image, captions (`.srt`/`.vtt`), and concise description.
- **Supporting copy:** accessible alt text, suggested captions and hashtags, translations, and links to installation instructions.

**Do not upload source material:** PowerPoint/Keynote projects, editable graphics, video timelines, raw footage, prompts, intermediate renders, or private strategy notes. The purpose is easy public distribution of approved **final outputs**. Keep originals in their owner's chosen workspace.

A suggested layout, created as material is added:

```text
assets/media/
  README.md
  CATALOG.md
  images/
    <campaign-name>/
  carousels/
    <campaign-name>/
      01.png
      02.png
      caption-en.md
  videos/
    <campaign-name>/
      thumbnail.png
      captions-en.srt
  captions/
    <campaign-name>/
```

The directory names are flexible; keep related assets together and use descriptive lowercase filenames. Do not create empty placeholder directories.

## For people who want to share a post

1. Open [CATALOG.md](CATALOG.md), choose an item marked **approved**, and read its usage/credit requirements.
2. Download the finished files, preferably in their original resolution. Publish the carousel pages **in numbered order**.
3. Use the included caption and alt text if useful; translate or customize them when the item's license permits.
4. Link to the project: <https://github.com/MSKazemi/yazses>. Do not claim to represent the official maintainers.
5. If you substantially modify a CC BY 4.0 item, indicate that it was adapted and preserve credit/license information.

Public reposts are welcome **only within the license and third-party permissions specified for that item**. A publicly accessible GitHub file is not, by itself, an unlimited copyright or trademark grant.

## For contributors submitting media

For each proposed media pack, provide the final exported files and an entry in the catalog containing:

- **Title and purpose** — what the post explains and its intended audience.
- **Platform / format / language** — e.g., Instagram carousel, English, 1080 x 1350 PNG.
- **Files or download URLs** — ordered pages or a final video export.
- **Suggested caption and alt text** — accessible and easy to reuse.
- **Creator and license** — rights holder, agreed license, required attribution, and any third-party credits.
- **Review status** — `proposed` until a maintainer marks it `approved`.

Review for factual accuracy, current installation instructions, spelling, legibility on mobile, privacy, third-party logos/music/photos, and evidence supporting any feature claims. Use synthetic examples; never post private user speech, transcripts, recordings, screenshots containing personal data, or unreleased plans.

## Licensing and reuse policy

The main repository currently has an [Apache-2.0 license](../../LICENSE). **No dedicated license identifier for public promotional media has been chosen yet;** the two packs on [Share your contribution](../../docs/contribute/share.md) are offered there as free to use without one. A practical option for media the project owns is [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/), which permits sharing and adaptations, including commercial use, with proper credit and a license link. A project maintainer should choose and document the actual license for each media item before approving it; do not assume the project can license third-party audio, photos, artwork, font software, people’s likenesses, or trademarks it does not own.

The default requirement for a catalog entry is to identify the license **explicitly**, not simply label the file "free." A license on artwork does not imply permission to falsely claim endorsement by YazSes.

## Filesize and repository health

Store small final images and captions directly in Git. Avoid duplicating files already under `docs/screenshots/`; link them in the catalog when suitable. For **large videos**, prefer a GitHub Release asset (with a stable link in the catalog) rather than committing heavy MP4s into regular Git history. GitHub warns about large ordinary Git objects, and a growing media library should not slow down software contributors.

The repository intentionally ignores `*.pdf` and guards against checked-in PDFs. Export slide decks as **numbered PNG/JPG files** rather than PDF documents.

## Related public resources

Existing product screenshots and a short demo can be found under [docs/screenshots](../../docs/screenshots/). These are **candidate sources for review**, not automatically approved media packs; see the catalog.

## Maintenance

Anyone may suggest or contribute a pack through the normal GitHub contribution workflow. A maintainer verifies rights and factual accuracy, marks the catalog entry `approved`, and keeps links from this page current. Keep versions when an old campaign's claims or UI screenshots become outdated; avoid silently replacing a published image with a contradictory claim.
