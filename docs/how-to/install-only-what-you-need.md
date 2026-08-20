---
title: Install only what you need
description: YazSes ships dictation first and fetches everything else on demand. How to read the DOWNLOAD column in yazses features, what each capability costs, and how to keep a dictation-only install small.
---

# Install only what you need

A plain install gives you hold-to-talk dictation and nothing that dictation does not
need. Every heavier capability — a camera, a neural voice, speaker embeddings — is an
optional dependency that is fetched **only when you turn that capability on**.

That design has one failure mode, and it is the one this page exists to close: a
capability can be one word to type and gigabytes to download. So the price is printed
where you choose, not only where you pay.

## See what something costs before you turn it on

```console
$ yazses features
│         NAME                             TOGGLE NAME            DOWNLOAD  ADVICE
│  ● ON   Voice-activity overlay           overlay                ~256 MB   recommended (on by default)
│  ○ off  Read-Back Loop                   read-back              ~352 MB   optional
│  ○ off  Glance-Type (camera)             gaze                   ~223 MB   experimental — not advised yet
│  ○ off  Cocktail Filter (voice focus)    cocktail               ~3.1 GB   experimental — not advised yet
│  ○ off  Dictation Reflow                 reflow                           optional
```

**DOWNLOAD** is what a fresh install fetches **in total** — the whole dependency
closure, not just the top-level package, plus any model files the capability pulls
down the first time it runs. `cocktail` reads as one small feature and resolves to
`speechbrain`, which pulls PyTorch and the NVIDIA CUDA stack. `read-back` is 12 MB
of packages and a 340 MB voice model, and the column has to say 352 MB or it is
answering a question about pip rather than about your disk.

The two arrive at different times, which is why `yazses features enable` names them
separately: the packages land while you wait on the command, the model on the first
run afterwards.

!!! warning "Two engines are not priced here"

    `stt-parakeet` and `stt-moonshine` fetch their weights through their own
    libraries rather than through YazSes, so the column covers their packages only.
    Both models are substantial — expect a further download on first use.

A blank cell means there is nothing to download. Most capabilities are blank:
`reflow`, `undo`, `commands` and the rest are pure logic that ships in the base
install.

If a row reads `◌ set` rather than `● ON` or `○ off`, your config turns that
capability on and nothing in this build reads it — it costs you nothing and does
nothing. `yazses features disable <name>` clears the key. See
[`yazses features`](../cli-reference.md#yazses-features).

!!! note "Two numbers, two questions"

    The catalogue quotes the **full** size, because it is a price list read by anyone.
    `yazses features enable <name>` quotes what is missing **on your machine**, which
    is usually smaller and is the number you actually pay. If you already have
    PyTorch for something else, enable will say so.

Sizes are read from a table that ships inside the package. Listing capabilities never
touches the network
([ADR-011](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-011.md)).

## The three tiers

The **ADVICE** column says how much you should want each one:

| Tier | Meaning |
|---|---|
| `core` | dictation itself — not optional, not removable |
| `recommended (on by default)` | a fresh install enables these; they are small or free |
| `optional` | useful, off until you ask |
| `experimental — not advised yet` | works, but has a known sharp edge; `enable` refuses without `--force` |
| `planned — designed, not yet wired` | in the catalogue so it is honest, not yet callable |

Nothing in the recommended tier is expensive except the tray and overlay, which share
one Qt install (~256 MB) and give you the on-screen state that makes dictation
legible. On a headless or memory-tight machine, turn both off and the Qt dependency
is never fetched:

```bash
yazses features disable tray
yazses features disable overlay
yazses restart
```

## Turning one on

```console
$ yazses features enable read-back

⚠  Large download — this downloads ~12 MB (7 packages), plus ~340 MB of model
   files on first use.
   Ctrl-C now to stop. `--no-install` prints the packages instead of fetching them.
```

Above ~250 MB, packages and model files counted together, the warning is loud and
tells you how to stop it. It is a warning
rather than a prompt on purpose: a prompt you have to answer is one more thing to
click through, and knowing mid-download still beats knowing afterwards.

To see the packages without fetching anything:

```bash
yazses features enable gaze --no-install
```

## Keeping an install small

- **Ask what it costs first** — `yazses features --category access` or `--tier opt`
  narrows the table to the group you are considering.
- **Prefer the smaller engine.** `stt-parakeet` is ~4 MB of packages on top of what
  you have — its weights come down separately on first use — and it is more accurate
  than `whisper-large-v3` on English; see
  [choosing a model](low-ram-models.md) for the memory side of that decision.
- **Turn things back off.** `yazses features disable <name>` stops loading the
  capability. It does not uninstall the packages — `uv pip uninstall` does, if you
  want the disk back.
- **Start from nothing.** `yazses features reset` returns every capability to what a
  fresh install ships with.

## See also

- [Choosing a model on a low-RAM machine](low-ram-models.md) — resident memory, not download size
- [Running fully air-gapped](air-gapped.md) — what to fetch before you disconnect
- [CPU use and battery on a laptop](cpu-and-battery.md)
