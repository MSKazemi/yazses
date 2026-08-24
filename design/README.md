# `design/` — the YazSes design record

This is the **public** engineering and scientific record of YazSes: why the software is
built the way it is, what the evidence says, and what is still unknown. It is licensed
with the rest of the repository (Apache-2.0) and is meant to be read.

If you want to know *how to use* YazSes, you want the [documentation
site](https://mskazemi.com/yazses/) instead. This directory answers the other question:
**why does it behave this way?**

## What is here

| Path | What it holds |
|---|---|
| [`adr/`](adr/) | ~150 Architecture Decision Records — one per real decision, with the context, the options, and the consequence. The primary record. |
| [`specs/`](specs/) | Implementation-ready feature specs in ADR house style. |
| [`research/`](research/) | The scientific layer: the [105-reference HCI corpus](research/2026-08-11-hci-reference-corpus.md), the [research agenda](research/2026-08-11-hci-research-agenda.md), literature sweeps, and [`hci-corpus.bib`](research/hci-corpus.bib). |
| [`research/studies/`](research/studies/) | State-of-the-art studies: scope, SoA matrix, gap analysis, capability cards. |
| [`architecture.md`](architecture.md) | The as-built architecture reference. |
| [`threat-model.md`](threat-model.md) | The privacy and threat model behind the offline-by-construction stance. |
| [`emg-protocol.md`](emg-protocol.md) | The YESP serial protocol for the EMG activation source. |
| [`v2-cognitive-layer/`](v2-cognitive-layer/) | Design notes for the opt-in perceptual/personalization features. |
| [`meeting-mode/`](meeting-mode/), [`mobile/`](mobile/) | Subsystem design notes. |
| [`packaging/`](packaging/) | Release-engineering runbooks: APT, PPA, Snap, macOS notarisation, Windows signing. Procedures only — they name GitHub Secret *keys*, never values. |

## The visibility contract

**One directory, one visibility.** There is no per-file exception list to keep in sync,
and a new file's status is never ambiguous.

| Directory | Visibility | Why |
|---|---|---|
| `design/` | **Public** | Engineering and science. The argument for the software is the software's best evidence. |
| `docs/` | **Public** | User-facing documentation, published to the docs site. |
| `strategy/` | **Private** | Marketing copy, SEO analysis, vision/idea notes for features that may never ship, distribution status. Tactics lose value when public, and unbuilt ideas read as promises. |
| `paper/` | **Private** | The manuscript, until the preprint is posted. |
| `paper/benchmark/`, `paper/results/` | **Public** | The exception, and a deliberate one: `docs/benchmarks.md` publishes numbers and tells the reader to reproduce them. While these were private, those instructions 404'd and the page's central promise was false. Harness code and small result JSON only — no audio, no transcripts, no manuscript. |
| `.claude/` | **Private** | Coding-agent artifacts: plans, memory, project-local skills. |

Enforced in three places, all of which must agree: `.gitignore`,
`.git/hooks/pre-commit`, and `hooks/design_tier.py` — the hook that mirrors this tree onto
the documentation site. Changing one without the others is a bug.

The third one used to be the odd one out, and the way it failed is worth recording. It
carried its own list of directories to publish, so `packaging/`, `v2-cognitive-layer/`,
`mobile/` and `meeting-mode/` — named as public in the table above, and committed to this
public repository — were absent from the site for months because no line in the hook
mentioned them. Nothing failed: an omission produces no warning, no broken link, no red
build. It now publishes **everything git tracks under `design/` that is not under a private
prefix**, which is the same rule the table states, derived rather than restated.

Tracked-ness, not the filesystem, is what decides. A file that is not committed is not in
the public repository, and the site must never be the first place it appears.

| Excluded from the site today | Why |
|---|---|
| `design/vision/` | Unbuilt-feature idea notes. Private by the contract above, and untracked, so two independent things would have to be wrong before it could be published. |

Nothing else is excluded.

### A public file must never contain a path into a private tree

The link dangles, and the filename itself leaks what is being held back. Where a document
here refers to internal material, it names it in prose — "the Punch-In vision card
(internal)" — rather than linking a path. The pre-commit hook rejects commits that
reintroduce one. Everything load-bearing from an internal note is restated here, so these
documents stand alone.

## No third-party PDFs. Ever.

Papers we cite are downloaded for personal research use. **Redistributing them would
violate the authors' copyright**, so no PDF is committed to this repository — the
pre-commit hook blocks `*.pdf` outright.

What we publish instead is strictly better for the reader anyway:

- the **citation**, with a DOI resolved against Crossref or DataCite;
- **our own summary** of what the work establishes and which decision it drives.

If you want to add a reference, put it in
[`research/hci-corpus.bib`](research/hci-corpus.bib), verify it with
[`research/verify_refs.py`](research/verify_refs.py), and cite it. Do not commit the paper.

**Link the landing page, not the file.** A URL ending in `.pdf` is the wrong citation
even though linking is not redistribution: it skips the abstract or publisher page that
carries the version, the licence and the DOI, and it breaks as soon as the author
reorganises their site — which is most of why link rot exists in bibliographies. Cite
`arxiv.org/abs/1710.10468`, not `.../1710.10468.pdf`.

Both rules are enforced by `tests/test_citation_hygiene.py`, which also asserts that no
PDF is *tracked* — the ignore rule and the hook guard the commit, and neither notices one
that arrived by a merge or a `git add -f`. It keeps a short, named exception list for
sources that genuinely have no landing page, such as a conference presentation hosted by
its author; that list is a debt, and the test fails if it grows.

## Contributing to the design record

- **Changing behaviour that had an ADR?** Update the ADR or supersede it. An ADR is a
  historical record: supersede, don't silently rewrite.
- **Proposing something new?** An ADR or a spec is the right first artifact, and it is a
  genuinely welcome contribution on its own — a well-argued decision record is worth more
  than a rushed implementation.
- **Adding a research claim?** It needs a verified citation. See the [verification
  protocol](research/2026-08-11-hci-reference-corpus.md#verification-protocol--and-what-it-caught)
  — fifteen entries in the corpus would have been wrong if written from memory, so this
  is not ceremony.

Start with [`CONTRIBUTING.md`](../.github/CONTRIBUTING.md) for the code side.
