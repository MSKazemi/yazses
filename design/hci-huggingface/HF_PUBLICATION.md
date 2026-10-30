# Hugging Face publication playbook (HCI Lab artifacts)

Status: draft playbook dated 2026-10-28; documentation only. Part of epic #692 / issue #698.
**This is a plan, not permission.** It does not create an account, organization, Space, repository,
token, collection or paid resource, and nothing in it is an approval to publish. The account owner
decides each step. The privacy gate that must pass first is in
[HF_PRIVACY_PREPUBLISH.md](HF_PRIVACY_PREPUBLISH.md) (#701); model provenance is in
[model-provenance.md](model-provenance.md) (#694).

Hub facts below were read from the Hugging Face documentation on 2026-10-28 and can change;
re-check the cited page before relying on one.

## 1. What goes where

GitHub stays the canonical home of all source. Hugging Face is a **venue and a registry**, never a
runtime dependency and never a place where something exists only once.

| Artifact | On Hugging Face? | Why |
|---|---|---|
| Static Space: the synthetic multimodal simulator (`examples/hci-hf-lab/`) | Yes, as a copy | A browser-only demo is easy to try and costs nothing. The source and tests stay in GitHub. |
| Dataset: the synthetic fixtures (#699) | Yes, once the schema is canonical | Synthetic only, so it carries no consent or rights risk. The viewer and citation metadata help reuse. |
| Model repository | **No.** Only an audited redistribution would qualify, and none is planned | YazSes downloads upstream weights from their owners; it does not re-upload them. A conversion's declared licence can differ from the upstream card (see the provenance inventory). |
| Collections, papers, profile text | Owner's account surface | Not repository content; the owner edits these by hand. |
| Anything with real audio, transcripts, camera frames, voiceprints, learning-corpus data, EEG/EMG recordings or participant data | **Never** | See the standing rules in #692 and ADR-019. |

Decision rule for a contributor: if it is code, a test, a design record or a measurement with
provenance, it lives in GitHub. If it is a self-contained synthetic demo or a synthetic table that
helps people try or cite the work, a copy may go to the Hub after the checklist passes.

## 2. Who owns the public Hub assets

Two owners exist in practice: the maintainer's personal Hub profile and the project's organization.
The options, and what each costs:

| Option | What it means | Trade-offs |
|---|---|---|
| A. Personal profile | The HCI artifacts live under the maintainer's own namespace | Simple, the maintainer is the only account that can change them, and the artifacts sit next to the maintainer's other research. A single person is a single point of failure for continuity. |
| B. Project organization | The artifacts live under the project's organization | Fits a shared project; roles and 2FA are managed in one place. Needs members and review rules, and is more visible as "the project's" than the research track warrants today. |
| C. Personal first, move later | Create under the personal namespace; transfer to the organization only if the research track becomes a project deliverable | A transfer redirects the old URL and preserves download counts and likes. Cheapest to start and reversible in one direction. |

**Recommendation (for the owner to confirm): C, starting personal.** The HCI track is research
under ADR-030, not a product commitment; a personal namespace avoids presenting it as a supported
YazSes feature. The organization keeps the YazSes product assets and can link to the HCI Space from
its collection once the Space is reviewed.

Transfer rules, as documented: a repo can move from a user to an organization (the user needs at
least contributor rights there), from an organization to the user (admin rights), and between
organizations (admin in the source, contributor in the target). A transfer **from one user to
another user is not supported**. Renames and transfers redirect the old URL.

Ownership hygiene, regardless of option:

- One accountable maintainer per artifact, named in its card.
- Two-factor authentication on every account that can write.
- No collaborators or admins added without the owner's decision.
- No tokens in the repository, in chat, in issues or in logs. Publishing from CI uses the Hub's
  OIDC trusted-publisher mechanism, not a stored token.
- Free resources only: static Spaces are free; do not select a paid plan, hardware upgrade, credit
  purchase or auto-renew for any HCI artifact.

## 3. Naming and linking

| Item | Proposed name | Notes |
|---|---|---|
| Space | `yazses-multimodal-hci-lab` | Static SDK. Short description 60 characters or fewer. |
| Dataset | `yazses-multimodal-hci-fixtures` | Only after #699 fixes the schema. |
| Model repository | none | See section 1. |
| Hub URL field in repo docs | **TBD** | Stays TBD until the owner publishes; no document may state a Hub URL that does not exist. |

Every Hub card links back to the canonical GitHub source and to the issue or PR that governs it,
and every GitHub page that mentions a Hub copy says it is a copy. README badges and website links
to a Hub artifact are added only after that artifact exists and has been opened and checked.

## 4. Draft cards (unfilled templates)

These are templates only. Every `<TBD>` is a decision or a measured fact that does not exist yet.
No placeholder here is a licence grant, a result or a URL.

### 4.1 Space README front matter and opening

```yaml
---
title: YazSes Multimodal HCI Lab (synthetic)
sdk: static
pinned: false
license: <TBD: owner decision>
short_description: <= 60 characters, says "synthetic" and "no sensors"
---
```

Opening paragraphs must say, in this order: what is simulated; that no camera, microphone or sensor
is used and nothing leaves the browser; that every number is illustrative; that it is not a YazSes
product feature; the maintainer; and the GitHub source link.

### 4.2 Dataset card

| Field | Content |
|---|---|
| Intended use | Replaying synthetic scenarios against an interaction resolver; reproducing the published checks |
| Not intended for | Training or evaluating on real people; any claim about device or human accuracy |
| Licence | `<TBD: owner decision; also check any upstream licence the fixtures derive from>` |
| Source and version | GitHub path and commit, schema version, generator seed if any |
| Contents | Case count, modalities, which cases are negative or failure examples |
| Synthetic-data statement | "Every record is hand-authored or generated; no person was recorded" |
| Consent and rights | None required because no human data is included; state this explicitly |
| Limitations | Illustrative confidences and ages; no hardware measurement; coverage is what the schema lists |
| Exact hashes | File checksums, produced by the exporter, not typed by hand |
| Maintenance owner | `<TBD: named maintainer>` and the issue tracker link |

### 4.3 Model card (only if an audited redistribution is ever approved)

Not planned. If it ever is: the card must name the exact upstream repository, the commit it was
taken from, the upstream licence and the redistributor's, a hash of every file, the conversion
steps, and who maintains it. A mismatch between the conversion's declared licence and the upstream
card blocks the upload until the owner resolves it.

## 5. Manual creation, change control and review

1. The privacy checklist (#701) has no open blocker for the artifact, and the owner has accepted
   in writing any OPEN row.
2. The owner opens the Hub in a browser and creates the empty repository by hand, with the visibility
   decided in advance (private first is allowed and recommended for the first upload).
3. Content comes only from a reviewed GitHub commit. Upload exactly that commit's files; record the
   commit hash in the card.
4. After upload, open the artifact in a clean browser profile and repeat the checks from #701:
   no permission prompt, same-origin requests only, the card text matches the page.
5. Only then set it public, and only then add the Hub link to GitHub docs.
6. Any later change repeats steps 3 to 5. No automation publishes to a public artifact without a
   human approval step.

## 6. Retirement and rollback

| Situation | Action |
|---|---|
| A defect or a doubtful claim is found | Set the artifact private first (public to private hides it from search and returns 404 to visitors), then fix, review, republish |
| The artifact should not exist any more | Delete it, remove the Hub links from GitHub docs in the same change, and record why in the issue |
| Ownership must change | Transfer under the rules in section 2; do not recreate and duplicate |
| The maintainer can no longer maintain it | Mark the card as unmaintained, or retire it; do not leave a stale demo that looks supported |

Setting something private or deleting it removes it from the public Hub, but copies already fetched,
mirrored or indexed elsewhere can persist. Treat publication as effectively irreversible and publish
only what would be acceptable to leave out there.

## 7. What this playbook does not do

- It does not choose a licence, a name, or an owner; those are the owner's decisions above.
- It does not authorise any upload; the release gate is in #701.
- It does not describe the existing YazSes product pages on the Hub, which are covered by their own
  review.

Cross-references: epic #692; #693 (draft PR #703); #694 (draft PR #704); #699; #701; #683;
ADR-019; ADR-030; `AGENTS.md`; the research roadmap (draft PR #697).
