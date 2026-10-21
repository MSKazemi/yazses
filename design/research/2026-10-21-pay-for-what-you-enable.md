# Pay for what you enable: the name, the state of the art, and the path for YazSes

**Date:** 2026-10-21 · **Status:** research input to [ADR-028](../adr/adr-028-feature-addon-packs.md)
and to a proposed runtime-residency ADR · **Author:** Mohsen Seyedkazemi Ardebili ·
**Builds on:** [the 2026-08-15 survey](2026-08-15-modular-distribution-survey.md),
[ADR-016](../adr/adr-016-dependency-budget.md), [ADR-018](../adr/adr-018-feature-packs-and-the-plugin-question.md),
[ADR-027](../adr/adr-027-one-click-windows-update.md), [ADR-028](../adr/adr-028-feature-addon-packs.md)

The brief: *a user who selects a few features downloads and runs only those features'
libraries and models; a user who selects everything downloads more and uses more CPU and
RAM. Each feature installs what it needs, automatically, as a separate step, when it is
turned on.*

Evidence labels: **[F]** a primary source says so · **[S]** secondary source only ·
**[M]** measured in this repository on 2026-10-21 · **[O]** engineering judgment ·
**[U]** not verified.

---

## 1. What the approach is called

| Term | Meaning | Fit |
|---|---|---|
| **Zero-overhead principle** ("what you don't use, you don't pay for") | Stroustrup's rule for C++: an unused feature costs nothing. [F] [cppreference](https://cppreference.com/cpp/language/Zero-overhead_principle) | **The principle.** ADR-016 already states it as "a capability must pay for itself". |
| **On-demand feature delivery** | Android Play Feature Delivery: feature modules split from the base and delivered at install time, conditionally (by device), or on demand when the app asks. [F] [Android](https://developer.android.com/guide/playcore/feature-delivery) | **The mechanism, and the best name for it.** "Enable → fetch → load" is on-demand delivery. |
| **Features on Demand** | Windows optional capabilities added after install, from Windows Update or an offline source. [F] [Microsoft Learn](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/features-on-demand-v2--capabilities) | Same idea. Good wording for users ("features on demand"). |
| **Workloads and components** | The Visual Studio Installer composes the product from bundles and components the user can add or remove later. [F] [Microsoft Learn](https://learn.microsoft.com/en-us/visualstudio/install/modify-visual-studio) | Model for a Settings → Features page with profiles. |
| **Optional dependencies (extras) + lazy loading** | PEP 508 `name[extra]`, plus importing a module only inside the function that needs it. [F] [spec](https://packaging.python.org/en/latest/specifications/dependency-specifiers/) | The Python building blocks, both already in use. |
| **Plug-in / microkernel architecture** | A small core plus independently published extensions found at runtime. | **Not this.** It means third-party code on the dictation path, which ADR-018 §3 rules out. |

**Recommended naming [O]:** call it **"features on demand"** in user documentation and
**"on-demand feature delivery under a pay-for-what-you-use budget"** in design documents.
Avoid "plug-ins". The accurate architecture term is a *modular monolith with optional
first-party components*: one repository, one lock file, many independently installable
and independently loaded parts.

The principle has **four costs**, and a feature should pay none of them while it is off:

1. **Download** (bytes fetched),
2. **Disk** (bytes kept),
3. **RAM** (bytes resident while running),
4. **CPU** (work and wake-ups while idle or active).

YazSes is close to the state of the art on 1 and 2. Most of the remaining work is 3 and 4.

---

## 2. How others do it, and what went wrong for them

The projects that succeed with this are all **first-party**: the vendor builds every
module, each module is locked to one base build, and the base knows the catalogue.
Failures cluster in **open** ecosystems, from two causes: installing requirement strings an
extension supplies at runtime, and a shared module namespace with no global lock.

| Precedent | How it works | Lesson for YazSes |
|---|---|---|
| **Home Assistant** (closest Python analogue) | Each integration's manifest pins exact `requirements`. They are installed before the integration loads, now with uv under a constraints file, and "if installing fails, the integration does not load". [F] [manifest](https://contributors.home-assistant.io/core/integrations/manifest/), [package.py](https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/util/package.py) | The base must constrain every feature install. YazSes does this (`system/install_txn.py`). Custom integrations hit `ResolutionImpossible` against core's pins [S] [forum](https://community.home-assistant.io/t/unable-to-install-package/692233). |
| **Android feature modules** | Built from one bundle and signed with the base. The app checks that a module is installed before touching its code. [F] [Android](https://developer.android.com/guide/playcore/feature-delivery) | A module is only valid with the base it was built with. ADR-028's `base_build_id` is exactly this. |
| **MSIX related sets** | The latest version of a package is not used "until all … are installed"; removal needs a restart. [F] [Microsoft Learn](https://learn.microsoft.com/windows/msix/package/optional-packages) | Lock-step versions and restart-to-apply are normal. |
| **Blender extensions (4.2+)** | ZIPs that bundle unmodified PyPI wheels, one per platform. [F] [manual](https://docs.blender.org/manual/en/4.2/advanced/extensions/python_wheels.html) | One namespace means two versions cannot coexist [S] [#119681](https://projects.blender.org/blender/blender/issues/119681). Keep one lock across all features. |
| **VS Code** | Extensions run in a separate extension-host process and activate lazily on events. [F] [docs](https://code.visualstudio.com/api/advanced-topics/extension-host) | The runtime pattern to copy (§5). Its open marketplace carried the GlassWorm worm from October 2025 [S] [The Hacker News](https://thehackernews.com/2025/12/glassworm-returns-with-24-malicious.html). |
| **ComfyUI custom nodes** | Git repos with `requirements.txt`, installed into one environment. | ComfyUI_LLMVISION (2024) pulled trojanised wheels that stole passwords [S] [404 Media](https://404media.co/hackers-target-ai-users-with-malicious-stable-diffusion-tool-on-github). The official docs admit "the later installed plugin will break the existing environment" [F] [docs](https://docs.comfy.org/development/core-concepts/dependencies). **Never install runtime-supplied requirement strings.** |
| **Ultralytics on PyPI (Dec 2024)** | A normal package. | A script injection in the publish workflow shipped a crypto miner [S] [Wiz](https://wiz.io/blog/ultralytics-ai-library-hacked-via-github-for-cryptomining). A version pin is not enough: pin hashes. |
| **Flatpak extensions / snap components** | Channel-native optional parts, built and published with the host package. [F] [Flatpak](https://docs.flatpak.org/en/latest/extension.html), [snap](https://snapcraft.io/docs/explanation/how-snaps-work/snap-components/) | The right route for those two channels, not a custom format. |
| **Firefox language packs, Playwright browsers** | Version-locked add-ons, re-fetched on update. Playwright garbage-collects versions no client needs. [S] [bug 1038317](https://bugzilla.mozilla.org/show_bug.cgi?id=1038317), [F] [Playwright](https://playwright.dev/python/docs/browsers) | Re-sync on update with one prompt; garbage-collect stale builds. |
| **Ollama** | Models stay loaded 5 minutes after last use by default (`keep_alive`); a cap bounds loaded models. [F] [FAQ](https://docs.ollama.com/faq) | **The RAM precedent**: unload after idle. |
| **NLTK data** | The downloader unpickled data; CVE-2024-39705 allowed remote code execution. [S] [Tenable](https://tenable.com/cve/CVE-2024-39705) | Model files can be code. Pin their hashes; prefer ONNX and safetensors. |

---

## 3. Python standards, status on 2026-10-21

Statuses were checked against the PEP index (`peps.python.org/api/peps.json`) on this date. [M]

| Mechanism | Status | Use for YazSes |
|---|---|---|
| PEP 508 extras | Standard | Keep as the unit of a feature's libraries. |
| [PEP 751](https://peps.python.org/pep-0751/) `pylock.toml` | **Final**. One lock can cover all extras; hashes are mandatory. | Candidate hashed source for PyPI-channel `features enable` (§6, item 4). |
| [PEP 735](https://peps.python.org/pep-0735/) dependency groups | **Final**, but groups are never included in built wheels | Development only; cannot be the user-facing unit. |
| [PEP 771](https://peps.python.org/pep-0771/) default extras | **Draft** | Same verdict as the August survey: do not design against it. |
| [PEP 810](https://peps.python.org/pep-0810/) explicit lazy imports | **Final, Python 3.15** | `lazy import` is a SyntaxError on 3.11–3.14, so YazSes cannot use the keyword yet. `__lazy_modules__` is ignored before 3.15 and costs nothing. Neither replaces in-function imports of *optional* packages. |
| PEP 740 attestations | Live on PyPI; not checked by pip or uv by default [S] | Audit evidence, not an install gate. |
| Hash-checking mode (`--require-hashes`) | Supported by pip and uv [F] [pip](https://pip.pypa.io/en/stable/topics/secure-installs/) | Not used by YazSes's PyPI-channel install today [M]. |
| Subinterpreters (PEP 734) | Python 3.14; many native packages unsupported | Not an isolation boundary for numpy or ONNX Runtime. Use processes. |
| PyInstaller | `sys.executable` is the bootloader, not Python [F] [docs](https://pyinstaller.org/en/stable/runtime-information.html) | Why frozen builds need prebuilt packs (ADR-028), not runtime pip. |

---

## 4. Where YazSes stands, measured

Measured on `origin/main` `fa058766` in throwaway environments (base-only install, Linux
x86_64, CPython 3.12). [M]

**Done, and at the state of the art:**

- 22 extras plus `all`. The 149-row capability registry maps features to extras
  (`system/features.py::_FEATURE_DEPS`), and a test holds the pins to `pyproject.toml`.
- No optional extra is imported at module scope (AST scan; guards green).
- Disabled subsystems are not constructed at daemon start.
- Models download on first use.
- The marginal cost is shown before install (`system/feature_sizes.json`). There is an
  import-time budget in CI.
- The PyPI-channel install is a transaction (`system/install_txn.py`). It holds the base
  pinned as constraints, records the install where the channel keeps it (uv receipt,
  `pipx inject`), and rolls back on failure.
- Frozen Windows builds have a verified add-on-pack path (ADR-028 Phase 1, on `main`, not
  yet in a release).

**Base weight:**

- `import yazses.cli`: 63–73 ms, 18 MB RSS.
- `import yazses.core.daemon`: 250–310 ms, 33 MB RSS.
- Base site-packages: 451 MB. Four wheels are 85% of it: av, ctranslate2, onnxruntime,
  numpy, all from faster-whisper's dependency tree (the August survey's finding still
  holds).

**Gaps** (ranked by what they cost a user who did not ask for the feature):

| # | Gap | Cost it imposes | Where |
|---|---|---|---|
| 1 | The speech model loads at daemon start and **is never unloaded**. | base.en holds 188 MB after load and 216 MB after the first decode; the load peaks at 343 MB. | `core/daemon.py`, `stt/faster_whisper.py` |
| 2 | **`latency` is in the RECOMMENDED tier**, which first run switches on, although its own description says "Off by default". On POSIX its second model (tiny.en) loads once the CPU is busy and stays resident. | About 75 MB download and about 116 MB RAM, unasked. | `system/features.py` (the `latency` row; `_DEFAULT_ENABLED_TIERS`) |
| 3 | **The `gaze` extra installs two OpenCV distributions.** It declares `opencv-python`, while mediapipe 1.0.1 requires `opencv-contrib-python`. Both install, and both write the same `cv2/` package. | About 70 MB duplicated per eye-control install. Which `cv2` wins depends on install order. | `pyproject.toml` `gaze` |
| 4 | **Packaged channels cannot add features.** The `.exe` and `.app` ship base + Qt only. The snap bundles sherpa-onnx, kokoro, onnx-asr and PySide6 for every user. | Snap users download features they never enable. | `snap/snapcraft.yaml`, ADR-028 phases |
| 5 | **Nothing is reclaimed on disable.** Packages stay installed and models stay on disk; there is no "free 220 MB?" prompt. | Disk only grows. | `system/deps.py`, `packs/manage.py` |
| 6 | The PyPI-channel install resolves live from PyPI against version floors: no hashes, no lock. It asks no y/N even for the multi-GB voiceprint set (the CLI warns at 250 MB and proceeds). | Supply-chain exposure; surprise downloads. | `system/deps.py`, `cli.py` `features enable` |
| 7 | `voiceprint` on Linux resolves CUDA torch, about 3.4 GB, for one experimental feature. | A 3.4 GB download for a CPU-only app. | `pyproject.toml` `voiceprint` |
| 8 | No RAM or idle-CPU budget anywhere; the import-time ceiling (1.76 s) is about 6× the measured 0.30 s. | Regressions are invisible until a user notices. | `tests/` |
| 9 | Download sizes are measured on Linux x86_64 only. | Windows and macOS quotes are estimates. | `scripts/gen-feature-sizes.py` |
| 10 | Eight extras have no feature row, so enabling a feature can never install them. | Those features are reachable only by `pip install yazses[x]`. | `system/features.py` |

---

## 5. The runtime half: making RAM and CPU proportional

The August survey and ADRs 016, 018 and 028 cover download and disk. The brief also says
"more CPU and RAM when you select more". That only holds if a feature's memory and CPU
also **leave** when it is not in use. The state of the art, in order of value [O, each
with a precedent]:

1. **Import nothing for a disabled feature.** Already enforced.
2. **Load on first use, not at start.** VS Code's activation events
   ([docs](https://code.visualstudio.com/api/advanced-topics/extension-host)).
3. **Unload after idle**, per feature, with a configurable keep-alive. Ollama's default is
   5 minutes ([FAQ](https://docs.ollama.com/faq)).
   - Core dictation STT should stay resident by default, because first-word latency is the
     product. It should still offer an opt-in idle unload for low-RAM machines.
   - Meeting diarization, gaze, TTS, the LLM and voiceprint should all have timeouts.
4. **Run the heaviest features in worker processes**: gaze/mediapipe, llama-cpp,
   torch voiceprint, diarization. They would talk to the daemon over the existing IPC.
   This is the VS Code extension host and Chromium's process model
   ([Chromium](https://chromium.googlesource.com/chromium/src/+/main/docs/process_model_and_site_isolation.md)).
   - Native allocators (ONNX Runtime, CTranslate2, torch) do not reliably return freed
     memory to the OS. **A worker's exit is the only guaranteed release.**
   - It is also a fault boundary: a mediapipe crash does not kill dictation.
   - It is the isolation boundary that ADR-018 names as the condition for ever reopening
     plug-ins: a process with no network and no injector handle.
5. **A memory-bounded scheduler**: at most N heavy models resident; evict the least
   recently used. This is Ollama's `OLLAMA_MAX_LOADED_MODELS`.
6. **Budgets in CI**, so proportionality is a test and not a hope:
   - import time (exists; tighten it);
   - "disabled features add zero modules" (`sys.modules` allowlist);
   - per-feature peak RSS (pytest-memray `limit_memory`, or a subprocess RSS probe) on a
     nightly job with real models;
   - idle-CPU budget: daemon CPU seconds over 60 s idle with everything off.
7. **Show RAM and CPU at consent time**, next to the download size: "Eye control: 220 MB
   download, about N MB RAM while active". This extends ADR-018 §1. The figures would come
   from the nightly table, the way `feature_sizes.json` supplies disk figures.

---

## 6. Target architecture and roadmap

| Layer | Content | Precedent | Status |
|---|---|---|---|
| L0 Principle | A disabled feature costs 0 bytes, 0 imports, 0 RAM, 0 CPU wake-ups | Zero-overhead | ADR-016 covers disk and imports → extend to RAM and CPU |
| L1 Catalogue | One in-tree registry: feature → extra → models → download / disk / RAM / CPU → channels | VS workloads, Android manifest | `features.py` + `feature_sizes.json` → add runtime columns |
| L2 Lock | One lock co-resolving base + all extras; shipped hashed | PEP 751, HA constraints | `uv.lock` → hashed export for PyPI-channel installs |
| L3 Artefacts per channel | PyPI: hashed binary-only install under constraints · frozen Windows/macOS: `.yazpack` locked to `base_build_id` · snap: components · flatpak: extensions | Android splits, snap/flatpak | PyPI done (unhashed) · Windows on `main` · rest open |
| L4 Install transaction | Consent with price → download → verify → stage → child-process probe → atomic commit → rollback; offline `--from` | Windows FoD offline source | Done / designed |
| L5 Activation | Dormant until verified; restart to apply | MSIX, Android | Done (`system/dormant.py`) |
| L6 Runtime residency | Lazy import → load on first use → idle unload → heavy features in workers | VS Code, Ollama, Chromium | **Missing: the main new work** |
| L7 Lifecycle | Re-sync on update with one prompt; GC stale builds; "free N MB?" on disable; uninstaller cleanup | Playwright, Flatpak `autodelete` | Designed (ADR-028); disable-reclaim missing |
| L8 Verification | Budgets (import, modules, RSS, idle CPU); install matrix (none / each alone / all); frozen probe per pack | pytest-memray | Partial |

**Roadmap, smallest and safest first:**

1. **Quick fixes.** Each is a small diff with its own test.
   - Move `latency` out of the RECOMMENDED tier (gap 2).
   - Drop `opencv-python` from the `gaze` extra, because mediapipe's `opencv-contrib-python`
     is a superset (gap 3).
   - Pin `voiceprint` on Linux to the CPU torch index (gap 7).
2. **ADR-028's eight questions.** Answered on 2026-10-21 (see that ADR). Two code facts
   from this research change Phase 1:
   - The diarization pack fails §1's DLL rule as written, because `sherpa-onnx-core`
     ships its own unsigned `onnxruntime.dll` (1.28.2) next to the base's Microsoft-signed
     1.28.0. The build would withhold the pack.
   - Torch collides with the base's `libiomp5md.dll`.
3. **A runtime-residency ADR (L6).**
   - Idle-unload defaults per feature.
   - The out-of-process rule for gaze, LLM, voiceprint and diarization.
   - A per-feature RSS budget on a nightly job.
4. **Hashed PyPI-channel installs (L2/L3).**
   - Export a hashed lock covering all extras, install the feature's slice with
     `--require-hashes --only-binary :all:`, and ask y/N above a size threshold (gap 6).
5. **Reclaim on disable (L7).**
   - Offer to remove a disabled feature's packages, packs and models, with the size.
6. **Channel-native routes.**
   - Snap components instead of bundling every engine into the snap (gap 4).
   - Flatpak extensions.
7. **CI install matrix.**
   - none / each feature alone / all, on Linux nightly, plus the existing frozen probe per
     pack.

**What not to do:**

- Do not add third-party plug-ins (ADR-018 §3 stands).
- Do not design against PEP 771.
- Do not adopt the `lazy` keyword while 3.11–3.14 are supported.
- Do not use per-feature virtual environments for in-process features: they duplicate
  numpy and ONNX Runtime and cannot share one process. A per-feature environment is right
  only for a *worker* that needs a conflicting stack, such as torch.

---

## Sources

Primary: [PEP 751](https://peps.python.org/pep-0751/) ·
[PEP 735](https://peps.python.org/pep-0735/) · [PEP 771](https://peps.python.org/pep-0771/) ·
[PEP 810](https://peps.python.org/pep-0810/) ·
[pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/) ·
[uv export](https://docs.astral.sh/uv/concepts/projects/export/) ·
[PyInstaller runtime information](https://pyinstaller.org/en/stable/runtime-information.html) ·
[Home Assistant manifest](https://contributors.home-assistant.io/core/integrations/manifest/) ·
[Android Play Feature Delivery](https://developer.android.com/guide/playcore/feature-delivery) ·
[Windows Features on Demand](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/features-on-demand-v2--capabilities) ·
[MSIX optional packages](https://learn.microsoft.com/windows/msix/package/optional-packages) ·
[Visual Studio workloads](https://learn.microsoft.com/en-us/visualstudio/install/modify-visual-studio) ·
[Blender extension wheels](https://docs.blender.org/manual/en/4.2/advanced/extensions/python_wheels.html) ·
[VS Code extension host](https://code.visualstudio.com/api/advanced-topics/extension-host) ·
[Flatpak extensions](https://docs.flatpak.org/en/latest/extension.html) ·
[snap components](https://snapcraft.io/docs/explanation/how-snaps-work/snap-components/) ·
[Playwright browsers](https://playwright.dev/python/docs/browsers) ·
[Ollama FAQ](https://docs.ollama.com/faq) ·
[ComfyUI dependencies](https://docs.comfy.org/development/core-concepts/dependencies) ·
[Chromium process model](https://chromium.googlesource.com/chromium/src/+/main/docs/process_model_and_site_isolation.md) ·
[pytest-memray](https://pytest-memray.readthedocs.io/en/latest/usage.html) ·
[cppreference: zero-overhead principle](https://cppreference.com/cpp/language/Zero-overhead_principle)

Secondary: [HA forum, ResolutionImpossible](https://community.home-assistant.io/t/unable-to-install-package/692233) ·
[Blender #119681](https://projects.blender.org/blender/blender/issues/119681) ·
[GlassWorm (The Hacker News)](https://thehackernews.com/2025/12/glassworm-returns-with-24-malicious.html) ·
[ComfyUI_LLMVISION (404 Media)](https://404media.co/hackers-target-ai-users-with-malicious-stable-diffusion-tool-on-github) ·
[Ultralytics (Wiz)](https://wiz.io/blog/ultralytics-ai-library-hacked-via-github-for-cryptomining) ·
[CVE-2024-39705 (Tenable)](https://tenable.com/cve/CVE-2024-39705) ·
[Mozilla bug 1038317](https://bugzilla.mozilla.org/show_bug.cgi?id=1038317)

Measurements: this repository, `origin/main` `fa058766`, base-only environments built from
`git archive`, CPython 3.12, Linux x86_64; Windows wheels downloaded from the `uv.lock` URLs
and checked against their lock hashes.

Not verified: TUF on PyPI; snap components' production readiness; whether Microsoft Store
certification checks every inner PE file for a signature.
