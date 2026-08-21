# Modular distribution: what a YazSes install actually costs, and how other projects solve it

**Date:** 2026-08-15 · **Status:** research input for the feature-pack ADR · **Author:** Mohsen Seyedkazemi Ardebili

The question behind this: *a user who only wants voice dictation should download only what
voice dictation needs; anyone wanting more should fetch it separately, as a plug-in.*

The finding, stated first because it reframes the work: **YazSes already has that
architecture, and it is close to its floor.** 21 optional extras, lazy imports at every
heavy call site, on-demand installation through `yazses features enable`, and an honest
published cost page. What is missing is not modularity. It is (a) a floor set by the speech
engine that no amount of packaging can move, and (b) the user's ability to *see the price
before paying it*.

---

## 1. What an install measures, today

Measured 2026-08-15 on Linux x86_64, CPython 3.12, a clean venv with `uv pip install .` and
no extras and no dev group:

| | Measured |
|---|---|
| **Base install, on disk** | **414 MB** |
| Distributions installed | **42** (the project declares 16 direct dependencies) |
| Published estimate in `docs/install-cost.md` | ~450 MB — conservative by ~8%, which is the right direction to be wrong in |

### Where the 414 MB is

| Component | MB | Whose choice |
|---|---:|---|
| `ctranslate2` + `.libs` | 135 | faster-whisper's inference runtime |
| `av` + `.libs` (PyAV) | 103 | faster-whisper's audio decoding |
| `onnxruntime` | 53 | **faster-whisper's own dependency** — see below |
| `numpy` + `.libs` | 58 | shared by everything |
| `cryptography` | 15 | the encrypted learning corpus (ADR-012) |
| `hf_xet` + `tokenizers` | 23 | model download + tokenisation |
| everything else, incl. YazSes itself | 27 | YazSes' own code is **4 MB** |

**84% of a base install is four binary wheels that arrive with the speech engine.** YazSes'
own code is under 1% of it.

`onnxruntime` deserves a note because it looks like a budget violation and is not: it is
declared in the `tts`, `silero` and `parakeet` extras, yet appears in a base install anyway.
`uv pip show onnxruntime` gives `Required-by: faster-whisper` — it arrives with the core
engine, for its bundled Silero VAD. Two consequences:

1. The base floor cannot be reduced by moving *our* extras around.
2. Those three extras **over-declare**. Their true marginal cost is smaller than their
   declared package list implies, so any "what will this cost me" number computed naively
   from the extra's contents overstates it.

### The honest answer to "make dictation-only smaller"

**It already is dictation-only, and it is 414 MB.** The floor is set by `faster-whisper`'s
dependency tree, not by YazSes' packaging. Moving it means changing the engine — and the
`parakeet` engine seam already exists for exactly that kind of substitution, though Parakeet
adds `onnx-asr` rather than removing ctranslate2.

The one packaging lever with real leverage was already pulled: PySide6 (648 MB of Qt) moved
out of the base into the `desktop` extra (#259), which is why a headless install is 414 MB
rather than ~1.1 GB.

---

## 2. How other projects solve this

The pattern worth stealing is not any one implementation; it is **which layer each project
chose to make modular**.

| Project | Unit of modularity | Where it comes from | Trust model |
|---|---|---|---|
| **VS Code** | Extension (`.vsix`) | Marketplace, resolved at runtime | Publisher verification; extensions run in a separate host process |
| **JetBrains IDEs** | Plugin | Marketplace | Signed, reviewed |
| **Blender** | Add-on (Python) | Bundled or user-dropped; 4.2+ adds *extensions* with a repository | Trusted-by-install; no sandbox |
| **Neovim / Obsidian** | Plugin (git repo) | Third-party manager, no central store | None — the user is the reviewer |
| **Ollama** | *Model*, not code | `ollama pull`, content-addressed layers | Registry, digest-verified |
| **conda** | Package + environment | Channels | Channel trust + signatures |
| **PyTorch** | Wheel *variant* (cpu/cu121/…) | A separate index URL per variant | PyPI/registry trust |

Three lessons transfer directly:

1. **The heavy thing is usually data, not code.** Ollama's whole distribution model is about
   pulling weights on demand and never shipping them in the program. YazSes already does
   this — models download on first use, and `gaze/download.py` and `recimport/download.py`
   fetch their ~3.7 MB and ~15 MB model sets lazily. This is the single biggest reason the
   install is 414 MB and not several gigabytes.

2. **Runtime discovery is what makes a plug-in a plug-in.** VS Code, Blender and Neovim all
   resolve capability at start-up from what is present on disk, not from what the shipped
   binary was compiled to know. YazSes resolves capability from a **static in-tree registry**
   (`system/features.py`), which is why a capability cannot exist without being in this
   repository. That is the actual architectural gap behind the note's "plug-in" question.

3. **Nobody makes the user pay in the dark.** Every store above shows a size before install.
   YazSes shows a feature list with no prices attached.

---

## 3. The Python-native mechanisms, and which are usable

| Mechanism | Status | Verdict for YazSes |
|---|---|---|
| `[project.optional-dependencies]` (extras) | Standard, universal | **In use — 21 of them.** The right tool for "this feature needs that library". |
| `importlib.metadata` **entry points** | Standard, universal | **The missing piece.** This is how an out-of-tree package announces itself. Modern guidance is to use entry points for discovery and keep extras separate — the old "extras on an entry point" form is deprecated and consumers may ignore it. |
| **PEP 771 — default extras** | **Draft. Not implemented in pip or uv.** | Would let `pip install yazses` mean "minimal + recommended" with `yazses[]` as the opt-out. Exactly the shape wanted here — and **unusable today**. Reference implementations exist in unmerged branches only. Do not design against it; revisit if it lands. |
| Wheel variants (per-hardware builds) | Emerging; PyTorch does it with separate indexes | Out of scope. YazSes ships `py3-none-any`; the binary weight is in dependencies, not in us. |
| `--no-deps` staged installs | Works, fragile | Rejected: it makes the resolver's job the user's job. |

---

## 4. What is actually missing

Ordered by value, and this is the input to the ADR.

**A. The user cannot see what a feature costs before enabling it.** `yazses features` lists
144 capabilities with a description and an on/off state, and no size. `features enable gaze`
downloads mediapipe and opencv; `enable voiceprint` pulls speechbrain and its torch stack.
The user finds out by watching the progress bar. This is the gap with the clearest fix and
the most direct connection to the original question — and note that the naive fix is wrong,
because of the over-declaration above: the number must be the **marginal** cost given what
is already installed, not the sum of the extra's contents.

**B. There is no seam for a capability that does not live in this repository.** The registry
is a Python literal in `system/features.py`, and `test_feature_wiring_honesty.py` enforces
that every entry is reachable from an in-tree entry point. That guard is *correct* and
should stay — but it means the answer to "can I ship a YazSes plug-in?" is currently no.
Entry-point discovery is the standard mechanism, and it needs a deliberate trust decision
(see D) rather than being added because it is easy.

**C. There is no `minimal` intent.** Install paths ask for `desktop`, or nothing. There is no
way to say "I am a server, give me the least you can" and be told what that means. Related:
`install.sh`, the `.deb` and the Snap all pull `desktop`, so the 414 MB figure is not what
most users actually get — they get ~1.1 GB, correctly, because they have a desktop.

**D. Any plug-in seam is a security decision before it is a packaging one.** A YazSes
plug-in would sit on the dictation hot path, with access to the microphone, the transcript
and the injection backend — that is every keystroke the user speaks. ADR-011 promises
nothing leaves the machine. A third-party plug-in mechanism is the most direct way that
promise could be broken, and it would be broken by someone else's code wearing our name.
VS Code answers this with a separate extension host process; Blender does not answer it at
all. **The ADR must choose deliberately, and "defer third-party plug-ins" is a legitimate
outcome** — the note's underlying goal (don't download what you don't need) is fully served
by A and C, which need no trust model at all.

---

## 5. Recommendation to the ADR

1. **Do A first.** Marginal-cost reporting in `yazses features`, computed against what is
   installed. Small, no new dependency, no trust model, and it is the thing the user asked
   for.
2. **Do C next.** A named `minimal` profile plus honest documentation of what each install
   path actually pulls.
3. **Design B, ship it behind a decision on D.** Entry-point discovery is ten lines; the
   trust model is the work. If the answer is "not yet", say so in the ADR with the reason,
   so it is a decision on record rather than an omission.
4. **Do not design against PEP 771.** It is a draft with no implementation in pip or uv.

## Sources

- Measurements: this repository, 2026-08-15, method above; reproducible with
  `uv venv && uv pip install . && du -sm .venv/lib/python3.*/site-packages`.
- [PEP 771 – Default Extras for Python Software Packages](https://peps.python.org/pep-0771/) (Draft)
- [Entry points specification](https://packaging.python.org/en/latest/specifications/entry-points/), Python Packaging User Guide
- [Dependency specifiers](https://packaging.python.org/en/latest/specifications/dependency-specifiers/), Python Packaging User Guide
- [Dependency management in setuptools](https://setuptools.pypa.io/en/latest/userguide/dependency_management.html)
- `docs/install-cost.md` and issue [#259](https://github.com/MSKazemi/yazses/issues/259) (the PySide6 move)
