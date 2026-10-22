# Paper v2 LaTeX manuscript

This directory contains the **public working LaTeX draft** of the second YazSes paper.

The draft is intentionally public so contributors can review the text against the same evidence archive, open issues against specific sections, and propose changes through normal GitHub review.

## Build

With a standard TeX distribution and `latexmk`:

```bash
cd design/publication/paper-v2/manuscript
latexmk -pdf main.tex
```

The generated PDF is a build artifact and must **not** be committed. The repository-wide PDF guard remains in force.

## Source layout

- `main.tex` — document preamble and section order
- `macros.tex` — small manuscript macros
- `sections/` — manuscript prose, one logical section per file
- `references.bib` — manuscript bibliography

## Evidence rule

Every quantitative statement must remain traceable to the public benchmark archive under `paper/results/` and the interpretation constraints in `../RESULTS_DELTA.md`, `../CLAIM_LEDGER.md`, `../AZURE_CAMPAIGN.md`, and `../MANUSCRIPT_PLAN.md`.

Tables currently written inline are marked for replacement by generated LaTeX from issue #508.

### Generated tables and figure data (`generated/`)

`generated/` is written by `scripts/gen-paper-v2-tables.py` from the committed result files under
`paper/results/` and is **never edited by hand**:

```bash
uv run python scripts/gen-paper-v2-tables.py            # regenerate
uv run python scripts/gen-paper-v2-tables.py --check    # fail if a committed output is stale
```

Each `.tex` file is a complete `table` environment (`\input{generated/clean_asr}` replaces the inline
table of the same label); each `.csv` is plot data for pgfplots (`comment chars={\#}`). Every file starts
with the source artifacts and their sha256. Where the archive holds two runs of one measurement, both are
shown; caveats (sample size, host load, unpaired ratios, multiplicity) are carried into the table notes.
`tests/test_gen_paper_v2_tables.py` enforces all of this. A table is *provisional* while its input is: the
clean engine matrix awaits the frozen artifact from #495.

## Draft policy

This is a working draft, not an approved publication. Author names/order are intentionally not frozen here; the title page uses **YazSes Contributors** until the authorship process in issue #484 reaches the appropriate gate.

Do not use "first", "novel", "best", or universal superiority language until issue #507 completes the current literature check.
