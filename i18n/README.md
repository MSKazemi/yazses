# Translating YazSes

Translation is tracked in [#18](https://github.com/MSKazemi/yazses/issues/18) — one
language each, one PR each, no permission needed.

**There is no copy of the English text in this directory, on purpose.** A parallel copy of
`README.md` would be a second source of truth for the same prose, and the two would drift
within weeks — the translated one silently, because nobody reads it. `README.md` stays
canonical; what lives here is the *map* of which slice to translate, and the terminology
decisions that are genuinely new content.

## Where the file goes

`docs/<lang>/index.md` — `docs/fa/index.md`, `docs/pt-BR/index.md` — using the same
code as the docs site, not the repo root. They used to be `README.<lang>.md` at the
root; a GitHub blob page can carry neither `hreflang` nor `canonical`, so a
translation there was invisible to the search engines it existed to reach.

Start it with front matter, which is what earns the page that signal:

```yaml
---
title: "YazSes — فارسی"
description: "One or two sentences in your language, for search results."
alternates:
  en: index.md
---
```

`hooks/hreflang.py` reads `alternates` and emits the reciprocal tags; add the page to
the `Languages` section of `mkdocs.yml` so it is reachable. Links inside the page are
relative to `docs/<lang>/`, so the English README is
`https://github.com/MSKazemi/yazses#readme` and a screenshot is
`../screenshots/<name>.png`. Leave the badge block out — its links are root-relative
and render broken on the site. Then run `uv run python scripts/check-translations.py`,
which is the same check CI runs.

## Modules — pick one, not the whole file

`README.md` is 581 lines. Nobody should be asked to translate that as a first
contribution. It splits into slices that stand alone, in the order they matter:

The slices are defined in [`modules.yml`](modules.yml) — data, not prose, so a test can
fail when a `README.md` heading is renamed out from under the map:

| # | Module | Lines | Why it matters |
|---|---|---:|---|
| 1 | Landing | ~60 | Decides whether someone keeps reading |
| 2 | Quick Start | ~75 | Decides whether they install |
| 3 | Speaking | ~40 | First-use success |
| 4 | Requirements | ~80 | Where installs actually fail |
| 5 | Honesty | ~35 | Trust — translate faithfully, do not soften |
| 6 | Help | ~20 | Self-service support |
| 7 | Reference | ~65 | Mostly protected tokens; little prose |
| 8 | Contributing | ~30 | Grows the next translator |

**Modules 1 and 2 together are a complete, mergeable pull request.** That is what the
Hindi translation ([#165](https://github.com/MSKazemi/yazses/pull/165)) did and it was
merged. Anything beyond is welcome and never expected.

Put the rest in English behind the status banner so the next reader — and the next
translator — can see where the work stops:

```markdown
> Translation of [README.md](https://github.com/MSKazemi/yazses#readme). If anything here disagrees with the English
> version, the English version is correct.
>
> **Translation status:** modules 1–2 (landing, Quick Start) are translated; the sections
> after that are still in English.
```

## Never translated

These are in [`glossary.yml`](glossary.yml) and a wrong "translation" of any of them
produces a command that does not run:

- command names — `yazses start`, `yazses doctor`
- config keys and sections — `[stt] model`, `vad_threshold`
- file paths, URLs, and everything inside a code block
- the project name **YazSes**

## What a machine cannot do here

An AI first draft is fine and normal — say so in the PR. What it cannot certify is whether
the result reads naturally to a native speaker, whether a privacy or licence sentence still
means the same thing, and whether the commands work on that locale's typical setup. Those
are the contribution. A PR that is only machine output, unread, will be declined — not
because AI was used, but because nobody checked it.

Simplified and Traditional Chinese are separate translations, not a script conversion.
