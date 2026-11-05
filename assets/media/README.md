# YazSes public media library

**Create once. Share everywhere.**

This is the proposed home for **ready-to-post YazSes media**: finished images, social carousels, short videos, demo clips, thumbnails, subtitles, and accompanying captions. The goal is to let community members promote YazSes without design software, editing projects, or original production files.

**Status: open.** Finished media listed as **approved** in [CATALOG.md](CATALOG.md) is free to reuse under
[CC BY 4.0](LICENSE.md): post it, embed it, subtitle it, translate it, with a one-line credit. Growth by other
people sharing YazSes is the point. Nothing else in this repository is an approved pack until it is listed.

## Start here

| You are... | Do this |
|---|---|
| **Posting about YazSes** (social media, a blog, a talk) | Open [CATALOG.md](CATALOG.md), pick an **approved** row, download the files, credit with `YazSes — https://github.com/MSKazemi/yazses (CC BY 4.0)`. |
| **Making a video, carousel or image** | Export the **final** files only, add a catalog row ([template](CATALOG.md#media-pack-entry-template)), open a pull request. Never upload editable sources. |
| **Writing or reporting** about YazSes | Use the screenshots and cards in the catalog, link to the [release notes](../../docs/releases/index.md) for what a version actually does, and do not describe a feature as verified on hardware unless those notes say so. |
| **A maintainer** | Review against the checklist below, set the row to `approved`, and for a video follow [Videos](#videos). |

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

## Videos

Final videos are **not committed to Git**. Upload the export to the
[`media-kit` release](https://github.com/MSKazemi/yazses/releases/tag/media-kit) (a pre-release, so it never
becomes "latest" and never sits beside an installer), then add a catalog row with:

- the download URL, the size and the `sha256` of the file, so a reader can check what they got;
- the format and length, for example `1080x1920 MP4, 38 s`;
- a thumbnail and the captions (`.srt` or `.vtt`) committed beside the catalog as small files;
- the language, the licence, and any third-party material.

Name files `<campaign>-<platform>-<language>-<width>x<height>.<ext>`, lowercase, for example
`offline-dictation-reel-en-1080x1920.mp4`. Keep a video that has become out of date, marked `outdated` in the
catalog, instead of replacing it with one that says something else.

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

Finished media made by the project is licensed **[CC BY 4.0](LICENSE.md)**: reuse and adapt it freely, credit with
a link, do not imply endorsement. The software stays under [Apache-2.0](../../LICENSE). Two earlier packs, the
share images and the two reels on [Share your contribution](../../docs/contribute/share.md), were published as
free to use with no credit needed, and stay that way.

A contributor who adds media keeps their authorship and agrees to the licence in the catalog row. Do not submit
audio, photos, artwork, fonts or likenesses the project cannot license: name them in the row with their rights,
or leave them out. A licence on artwork never lets anyone claim to speak for the maintainers.

## Filesize and repository health

Store small final images and captions directly in Git. Avoid duplicating files already under `docs/screenshots/`; link them in the catalog when suitable. For **large videos**, prefer a GitHub Release asset (with a stable link in the catalog) rather than committing heavy MP4s into regular Git history. GitHub warns about large ordinary Git objects, and a growing media library should not slow down software contributors.

The repository intentionally ignores `*.pdf` and guards against checked-in PDFs. Export slide decks as **numbered PNG/JPG files** rather than PDF documents.

## Related public resources

Existing product screenshots and a short demo can be found under [docs/screenshots](../../docs/screenshots/). These are **candidate sources for review**, not automatically approved media packs; see the catalog.

## Maintenance

Anyone may suggest or contribute a pack through the normal GitHub contribution workflow. A maintainer verifies rights and factual accuracy, marks the catalog entry `approved` (a row needs a licence to be approved), and keeps links from this page current. Keep versions when an old campaign's claims or UI screenshots become outdated; avoid silently replacing a published image with a contradictory claim.
