# Publication planning and governance

This directory is the **public publication process** for YazSes: research syntheses, claim ledgers,
manuscript plans, authorship governance, review protocols, publication checklists, and any manuscript draft that is explicitly designated public.

Paper v2 is the first such public draft: its LaTeX source lives at `paper-v2/manuscript/`. Private manuscript/reference working material may still remain under the ignored `paper/` tree.

## Visibility boundary

YazSes uses one-directory-one-visibility:

- `design/publication/` is **public**. It contains process, evidence interpretation, and
  publication-safe metadata/templates.
- `paper/` remains **private** for private manuscript/reference working material. An intentionally public draft belongs under `design/publication/<paper-id>/manuscript/` instead.
- `paper/benchmark/` and `paper/results/` remain the existing narrow public exceptions for
  reproducibility artifacts.
- private contributor contact details, consent messages, and approval evidence are never stored
  here. They live in an access-controlled registry outside the public repository.

This separation prevents a publication plan or authorship checklist from weakening the repository's
existing manuscript privacy boundary.

## Current packages

- [paper-v2/](paper-v2/) — research synthesis, public LaTeX manuscript draft, manuscript plan, all-contributor authorship protocol,
  final-approval process, and Internet Archive publication checklist for the second YazSes paper.
  Start with [paper-v2/STATUS.md](paper-v2/STATUS.md) for the current results/gaps and execution map.
  Work is coordinated in [issue #510](https://github.com/MSKazemi/yazses/issues/510); authorship and
  final-publication operations are tracked separately in
  [issue #484](https://github.com/MSKazemi/yazses/issues/484).

## Rule for future papers

Create public planning/governance under `design/publication/<paper-id>/`. If a manuscript is intentionally public during drafting, keep its source under `design/publication/<paper-id>/manuscript/` so the visibility is explicit and reviewable. Otherwise keep manuscript source and rendered files in the private `paper/` tier. Do not widen the `paper/` allow-list merely to make a draft easier to commit.
