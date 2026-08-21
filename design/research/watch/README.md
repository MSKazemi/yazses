# The research watch

A dated sweep of new work relevant to offline voice input, plus the index that stops it
repeating itself.

## What is here

| File | What it is |
|---|---|
| `YYYY-MM-DD-digest.md` | One run's findings, **after curation** — see below |
| `seen.json` | Every paper ID already reported, so the next run shows only what is new |

## How to run it

```sh
uv run python scripts/research-watch.py --days 30
uv run python scripts/research-watch.py --dry-run     # look without writing
```

It queries the arXiv API over seven topic searches, each tied to a direction this project
has written down. Roughly a minute, mostly spent being polite about the rate limit.

## The digest is curated, not published raw

**Every entry lands with `**So what:** _(unreviewed)_` and must be either annotated or
deleted before the digest is committed.** That is the whole discipline. An automated
feed nobody prunes is a feed nobody reads, and this repository has enough
generated-and-ignored material already.

Curating the first run removed two entries the queries had matched incidentally — a
voice-controlled *game editor* and a paper on LLM code security that used the phrase
"speech input" in passing. Both queries were then narrowed, with the reason recorded in
the script. **That loop — run, prune, tighten — is the feature.** The tool is worth
keeping only for as long as someone does it.

## What it will not do

- **No PDFs.** The repository blocks committed PDFs and the pre-commit hook enforces it.
  We publish a summary and a link to the publisher's copy; redistributing other people's
  papers is a copyright problem, not a convenience question.
- **It is not in the daemon.** [ADR-019](../../adr/adr-019-egress-inventory-and-escalation.md)
  enumerates every way data can leave the machine and fails the build on a new outbound
  call inside `src/yazses/`. A literature watcher shipped in the product would be a sixth
  network path on a tool whose central promise is that it makes none you did not ask for.
  So it is maintainer tooling, run by a person who chose to.
- **It does not rank or score.** Relevance is a judgement, and the "So what" note is where
  it goes.

## Where the results end up

A digest that produces something durable should feed it forward rather than sit here:

- A direction worth pursuing → [the direction page](../../../docs/research/directions.md),
  through the same three gates as any other idea.
- A method for an open question → [the research agenda](../../../docs/research/agenda.md).
- A term worth defining → [the glossary](../../../docs/research/glossary.md).
- Nothing at all is a legitimate outcome, and the commonest one.
