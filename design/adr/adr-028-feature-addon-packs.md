# ADR-028 — Feature add-on packs: a frozen install fetches a feature's libraries when it is turned on

**Status:** Proposed (2026-10-20); the eight owner questions answered 2026-10-21
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-019-egress-inventory-and-escalation]] (the egress row this adds),
[[adr-018-feature-packs-and-the-plugin-question]] (no third-party plug-ins; show the price
first), [[adr-016-dependency-budget]], [[adr-011]] (nothing leaves the machine),
[[adr-021-invest-in-error-cost]], ADR-027 *One-click update on Windows* (on the unmerged
`integ/wave3-2026-10-20` branch at `95ddd869`, whose download code this ADR reuses).
Implementation spec: [`design/specs/feature-addon-packs.md`](../specs/feature-addon-packs.md).

---

## Context

**Owner decision (2026-10-20).** A packaged install cannot install any feature's extra
libraries. The Windows Inno `.exe` comes first. MSIX, Scoop, Chocolatey and winget run the
same frozen payload, and the macOS `.app` follows later. Turning on Parakeet or eye control
in one of these installs ends at `system/deps.py::fixed_payload_reason`, whose message is
"install YazSes from PyPI instead". The owner wants the base app to stay light, and wants
each heavy feature to install what it needs, automatically and as a separate step, when the
user turns it on. The direction chosen is **downloadable add-on packs**.

What the code does today:

- `system/features.py::_FEATURE_DEPS` maps a capability slug to the import names it probes
  and the requirement strings it installs. `tests/test_feature_pins_match_the_extras.py`
  holds those strings to the `[project.optional-dependencies]` extras character for character.
- `system/deps.py::install_blocked_reason` refuses before writing config. It asks
  `cameraperm/matrix.py::current_profile()`, and `can_add_runtime` is false for
  `windows-exe`, `windows-msix`, `macos-app`, `snap` and `flatpak`.
- `scripts/build-windows.ps1` runs `uv sync --no-dev --extra desktop` and then PyInstaller
  with `packaging/windows/yazses.spec`. The result is a one-folder bundle, `dist/YazSes/`
  with `_internal/`, built on CPython 3.12 (`uv python install 3.12` in
  `build-windows.yml`). Inno wraps it as `YazSes-<v>-windows-<arch>.exe`. Only x64 ships;
  the arm64 leg is gone because `ctranslate2` publishes no `win_arm64` wheel.
- Each release publishes `SHA256SUMS.txt` (`checksums.yml`, built from the attached assets)
  and a `YazSes-<v>-windows-<arch>.intoto.jsonl` SLSA provenance bundle
  (`actions/attest-build-provenance`). The installer is **not code-signed**: the SignPath
  steps depend on secrets that were never set.

**What the lockfile says, measured 2026-10-20** with a script over `uv.lock`. It takes
the closure of each extra, subtracts the Windows base plus the `desktop` closure, and
checks for `cp312`/`abi3`/`none-any` wheels. The marginal sets are much smaller than the
extras' names suggest, because the base already freezes `numpy`, `onnxruntime` (1.28.0, a
faster-whisper dependency), `huggingface-hub`, `tokenizers`, `av` and `ctranslate2`:

| Extra | Wired features it serves | Distributions beyond base | Native code beyond base | Win x64 wheels for all? |
|---|---|---|---|---|
| `parakeet` | `stt-parakeet` | 1 (`onnx-asr`) | none | yes |
| `diarization` | `diarize`, `recimport`, `meeting` | 2 | `sherpa-onnx`, `sherpa-onnx-core` | yes |
| `prosody` | `prosody` | 1 | `praat-parselmouth` | yes |
| `chinese` | `chinese-script` | 1 | none | yes |
| `tts` | `read-back` | 7 | `espeakng-loader` | yes |
| `denoise` | `denoise` | 10 | scipy, matplotlib, contourpy, kiwisolver | yes |
| `gaze` | `gaze`, `facegesture`, `headpointer`, `gesture` | 11 | mediapipe, opencv-python, opencv-contrib-python, matplotlib… | yes |
| `moonshine` | `stt-moonshine` | 23 | numba, llvmlite, scipy, scikit-learn, soxr… | yes |
| `voiceprint` | `cocktail` (`voiceguard`, `multiprofile` unwired) | 16 | torch, torchaudio, scipy, sentencepiece… | yes |
| `slm` / `notes` | `llm-cleanup` | 4 | — | **no**: `llama-cpp-python` is sdist-only in the lock |
| `voiceprint-resemblyzer` | (backend only) | 29 | — | **no**: `webrtcvad` is sdist-only |

The owner's own example, Parakeet, needs **one pure-Python distribution** on Windows. Eye
control needs about 220 MB (the Linux figure in `system/feature_sizes.json`; the Windows
figure has not been measured). Packs are therefore worth building, and the first ones are
small enough to prove the mechanism cheaply.

**ADR-018 §3 still applies.** It forbids loading third-party plug-ins, because a plug-in
would sit on the dictation hot path. An add-on pack is not a plug-in, and §3 below keeps
it that way. A pack contains only distributions that this repository's `uv.lock` already
pins for an extra this repository declares. The release workflow builds it from the same
commit as the installer. The app loads it only when its hash is listed in an index built
into that same installer. No third party can publish a pack, and a user cannot point the
app at an arbitrary one.

## Decision

### 1. Pack format and ABI

**One pack per qualifying extra, per platform and architecture.** The unit is the
pyproject extra, because the lockfile already resolves at that level and
`test_feature_pins_match_the_extras.py` already ties features to extras. A pack is a ZIP
file with the suffix `.yazpack`:

```
pack.json        manifest (below)
RECORD.json      every file: relative path, size, SHA-256
site/            the extra's wheels minus the base, unpacked as `pip install --target` lays them out (*.dist-info kept)
stdlib/          optional: stdlib modules the pack imports that the frozen base did not collect
LICENSES/        third-party licence texts copied from each distribution's dist-info
```

The manifest pins the pack to **one specific base build**:

```json
{
  "format": 1,
  "name": "parakeet",
  "extra": "parakeet",
  "features": ["stt-parakeet"],
  "app_version": "2.44.0",
  "base_build_id": "sha256:<64 hex>",
  "python": {"cache_tag": "cpython-312", "version": "3.12.9", "abi": "cp312"},
  "platform": "win-amd64",
  "arch": "x64",
  "distributions": [{"name": "onnx-asr", "version": "0.12.0"}],
  "entry_modules": ["onnx_asr"],
  "native_dirs": [],
  "unpacked_bytes": 1234567,
  "files": 210
}
```

`base_build_id` is the SHA-256 of a canonical `base-manifest.json`. That file lists every
file of `dist/YazSes/` with its size and hash, and is written in the same CI job right after
PyInstaller. A pack is loadable **only** into a base whose build id matches exactly. Version
equality alone is not enough, for three recorded reasons:

- The base freezes `numpy`, `onnxruntime` and the rest. A pack built against different
  copies can import successfully and then fail inside a native call.
- `uv python install 3.12` takes whichever 3.12 patch is current. Two runs of the same tag
  can freeze different interpreters. CPython's ABI is compatible across patch releases "if
  these are compiled the same way"
  ([C API Stability](https://docs.python.org/3/c-api/stable.html)). The stdlib supplement is
  tied to the exact patch, though.
- Releases have been rebuilt for the same tag (v2.32.0, recorded in `checksums.yml`). A user
  who installed the first build must not be handed packs from the second.

The `python`, `platform` and `arch` fields are redundant with the build id. They are kept so
that a refusal can say *why* ("built for Python 3.12.8, this app runs 3.12.9") instead of
showing an opaque hash.

**On mismatch the pack is never loaded.** This includes every pack after an app update.
Each installed pack lives under a directory named after its build id (§6), so a new base
simply finds no directory for itself. The user is offered a re-download (§6). Matching is
never relaxed to "same minor version, probably fine".

**Three build rules apply to every pack** (§7 lists all the checks):

- No top-level module name a pack ships may already exist in the base. The base always wins,
  so this rule makes shadowing impossible rather than merely unlikely.
- **No DLL basename collision.** Windows answers a DLL request from the *loaded-module list*
  "no matter which folder it was loaded from"
  ([DLL search order](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order)).
  A pack DLL called `onnxruntime.dll` would therefore silently bind to the base's copy. A
  pack DLL whose basename matches a base DLL or another pack's DLL fails the build, unless
  the bytes are identical, in which case the duplicate is dropped. This is expected to be
  the first real obstacle: `sherpa-onnx-core` carries its own ONNX Runtime on Linux, per the
  note in `features.py`. Whether its Windows wheel does too is unverified. The check, not
  this ADR, will answer it.
- `.pth` files are not executed. A `.pth` line that only adds a path becomes an entry in
  `pack.json`. A `.pth` that runs `import` code fails the build. Console-script launchers
  (`Scripts/`) are removed, since they point at a `python.exe` that does not exist.

**Rejected alternatives:**

- *Running pip inside the frozen app.* There is no interpreter: `sys.executable` is
  `YazSesApp.exe`. It would also resolve against PyPI at the moment of enabling, so the
  result would not be reproducible, could build sdists, and would need a new egress row to
  `pypi.org` plus `files.pythonhosted.org`. It would also put back exactly the failure
  `fixed_payload_reason` exists to prevent.
- *Keeping the ZIP on `sys.path` (zipimport).* "ZIP import of dynamic modules (`.pyd`,
  `.so`) is disallowed" ([zipimport](https://docs.python.org/3/library/zipimport.html)),
  and almost every pack has a `.pyd`.
- *A second PyInstaller bundle per feature, run out of process.* This gives full ABI
  isolation, but each pack would carry a copy of the base runtime, and in-process features
  (an STT engine, camera frames) would need new IPC. It is recorded as the route if a pack
  ever cannot coexist in-process (for example, an irreconcilable DLL collision). It also
  matches the isolation boundary ADR-018 names for any future plug-in story.
- *Inno Setup optional components.* The choice is made only at install time. Silent
  installs (Chocolatey, Scoop, winget, the ADR-027 hand-off) skip it, MSIX has no
  equivalent, and it cannot respond to "turn this on now".
- *A fat installer.* The owner rejected it, and ADR-016 forbids it.

### 2. Loading

**When.** Packs are mounted by a PyInstaller **runtime hook**
(`packaging/windows/rthook_yazses_packs.py`, listed in the spec's `runtime_hooks`).
PyInstaller documents runtime hooks as scripts that "manipulate the environment before your
main script runs"
([Changing runtime behavior](https://pyinstaller.org/en/stable/when-things-go-wrong.html)).
This also covers frozen `multiprocessing` children, which start through the same bootloader.
The hook calls one function and swallows every exception from it. A pack must never be able
to stop YazSes from starting.

**How.** The pure core decides what to mount and the Windows backend applies it:

1. Skip all packs when not frozen, when the install profile is not pack-capable (§8), when
   `YAZSES_NO_PACKS=1` is set (the recovery switch), or **when the process is elevated**.
   Pack files are writable by the user. Loading them into an administrator process would
   turn a same-user file write into elevation, which is the race ADR-027 refused for
   all-users installs.
2. Read the **embedded pack index** from `_internal/yazses-packs-index.json` (§3). It gives
   this base's `base_build_id` and the expected SHA-256 of every pack built for it.
3. For each pack under `packs/<build-id>/<name>/`:
   - The `COMPLETE` marker must exist. It is written last, by an atomic rename (below).
   - `pack.json` must parse, and every field must match this base and the index entry.
   - The archive hash recorded at install time must equal the index entry.

   Any failure stops that pack before anything is touched (§2 quarantine).
4. `sys.path.append(<pack>/site)` and then `<pack>/stdlib`: **appended, never prepended**,
   so the frozen archive and the base's files always come first. PyInstaller's bootstrap
   searches its own archive first and then, as its next step, "examine[s] paths in the
   sys.path. There could be any additional location with python modules"
   ([Advanced topics](https://pyinstaller.org/en/stable/advanced-topics.html)).
   `site.addsitedir` is not used, because it would execute `.pth` lines.
5. For each `native_dirs` entry, call `os.add_dll_directory(path)` through the
   `PackRuntime` platform Protocol, and **keep the returned handle alive for the life of
   the process**. Closing the handle removes the directory. Since 3.8 this search path is
   what CPython uses "when resolving dependencies for imported extension modules … and also
   by `ctypes`", and `PATH` is no longer consulted
   ([`os.add_dll_directory`](https://docs.python.org/3/library/os.html#os.add_dll_directory)).
   `PATH` is not modified and `SetDllDirectory` is not called.
6. `importlib.invalidate_caches()`.

Mounting imports **nothing** from a pack. A pack's modules load lazily, when its feature
runs, through the existing lazy-import call sites (AGENTS.md rule 3).

**The startup check is O(1) per pack, not a re-hash.** Hashing hundreds of MB on every tray
start would be paid by every user on every login. Partial installs cannot reach the startup
check anyway. Extraction happens in `staging/`, the tree is checked against `RECORD.json`,
an import probe runs (§6), and only then is the tree moved into place with one same-volume
`os.replace` and the `COMPLETE` marker written. Later damage is a separate case. Security
software deleting a DLL is the realistic Windows instance. That damage is caught where it
shows up: an `ImportError` or `OSError` from a module inside a mounted pack triggers a full
`RECORD.json` check of that pack, and `yazses packs verify` and `doctor` run the same check
on demand.

**Quarantine.** A pack that fails a check is not deleted on the spot. It is moved with
`os.replace` to `packs/quarantine/<name>-<UTC timestamp>/`, beside a `reason.txt`. Its
features read as *damaged — reinstall* (§5), and the folder is kept for diagnosis until the
next successful install of that pack or `yazses packs clean`. A pack that is merely **stale**
(another build id) is not quarantined. It is left alone for rollback (§6).

### 3. Trust

Packs are executable code, so they get the installer's trust treatment and more. The trust
chain:

1. **The pack index is built into the base.** CI writes
   `YazSes-<v>-windows-<arch>-packs.json` (names, sizes, SHA-256s, `base_build_id`) and
   copies it into `dist/YazSes/_internal/` **before** Inno packages the bundle. The installed
   app therefore knows the exact hash of every pack that belongs to it, offline. This is the
   decisive choice in this ADR: **a pack is exactly as trustworthy as the installer the user
   already chose to run.** Someone who gains write access to the release *after* the user
   installed cannot get a substituted pack accepted, because its hash is not in the index
   inside the installed app. `SHA256SUMS.txt` cannot give that, since an attacker can
   replace both files together. The index also gives the UI exact sizes without a network
   call (§5).
2. **`SHA256SUMS.txt` from the same release is a second, independent check.** It is fetched
   with ADR-027's `fetch_checksums` and read with its `expected_sha256`, which requires
   exactly one line. Its value must equal the embedded one. If they disagree, the user is
   told the release assets have changed since this copy was built (the v2.32.0 case) and
   nothing is installed.
3. **Transport:** HTTPS to `github.com/MSKazemi/yazses/releases/download/v<running
   version>/` only, with redirects only to GitHub's https asset hosts
   (`is_trusted_download_url`, `is_allowed_redirect`).
4. **Provenance for auditors:** CI attests every `.yazpack` and the index with
   `actions/attest-build-provenance`, and attaches
   `YazSes-<v>-windows-<arch>-packs.intoto.jsonl`. Anyone can check it with
   `gh attestation verify --bundle … --repo MSKazemi/yazses --signer-workflow …`
   ([gh attestation verify](https://cli.github.com/manual/gh_attestation_verify)), and
   `scripts/verify-provenance.py` will require it automatically. It derives the attested
   suffixes from `subject-path`.

**What is protected:** truncation, corruption and CDN or proxy substitution; a release asset
replaced after the user installed; a mixed-up build (wrong version, Python or arch); a
partial extraction.

**What is not protected, stated plainly:**

- *The installer itself.* It is unsigned. Whoever can replace the `.exe` **before** a user
  downloads it controls the embedded index too. Packs inherit exactly the installer's
  authenticity, no more and no less. When SignPath signing goes live, the index sits inside
  an Authenticode-signed installer and the whole chain becomes authenticated with no change
  to packs. Signing is therefore the single upgrade that matters, and it is already
  ADR-027's recorded next step.
- *A compromised build or maintainer account.* A pack built from a malicious commit is
  attested as faithfully as an honest one. SLSA provenance says which workflow built an
  artifact from which source. It "does not cover a compromised build platform itself"
  ([SLSA: verifying artifacts](https://slsa.dev/spec/v1.0/verifying-artifacts)).
- *Same-user tampering after install.* The pack directory is user-writable, like a per-user
  `{app}`. A same-user process could edit it, just as it could edit `YazSesApp.exe`. No new
  boundary is crossed: packs never load into an elevated process (§2.1).
- *Upstream wheels.* A pack is only as safe as the PyPI wheels pinned by hash in `uv.lock`,
  which is the same exposure every `pip install yazses[gaze]` user has today.

**In-app provenance verification is rejected for Phase 1.** Checking a Sigstore bundle
offline needs a Sigstore trust root inside the app. A pinned root goes stale when Fulcio or
Rekor keys rotate, and refreshing it is a new egress path. It would also add a heavy
dependency for a guarantee the embedded index already gives against the threats in scope.
**A project Ed25519 signature over the index** (verifiable with `cryptography`, already a
base dependency) was also considered. It adds nothing while the index ships inside the
installer, because the public key would ship the same way. It becomes useful only for
§6's offline `--from` install on an install from before this ADR, so it is listed as an
open question rather than built.

**Smart App Control.** On Windows 11 machines with Smart App Control enforcing, unsigned
code is blocked unless it has cloud reputation
([Sign your app for Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)).
That already applies to the unsigned base. Most pack DLLs are unsigned upstream binaries, so
packs carry the same limitation. Code signing does not fix it for third-party DLLs that YazSes
does not re-sign. The Windows checklist (spec §Phase 1) records what happens.

### 4. Egress

This is a **new outbound path**, registered under ADR-019 as **Class A — fetch**. It
fetches **code that then runs**, the same wording ADR-019 uses for `system/deps.py` and
ADR-027 uses for the installer.

| Field | Value |
|---|---|
| Module | `packs/fetch.py` (the only module that starts a pack download) |
| Destination | `https://github.com/MSKazemi/yazses/releases/download/v<running version>/`, with redirects only to https `github.com` / `*.githubusercontent.com` |
| What crosses the wire | ← `SHA256SUMS.txt`, ← `YazSes-<v>-windows-<arch>-pack-<extra>.yazpack`. → only an HTTP GET with a fixed `User-Agent`, no cookie, no token |
| Trigger | the user confirms enabling a pack-backed feature in the tray, Settings or `yazses features enable` / `yazses packs install`; or confirms the post-update re-download (§6) |
| Never | in the background, from the update watcher, at startup, or from the daemon |

**No API call.** The asset URLs are deterministic from the running version's tag, so packs
never touch `api.github.com`. That rules out the 415 `Accept`-header failure ADR-027's
revision recorded, and the unauthenticated API rate limit with it.

**What the request reveals,** so nobody can claim otherwise later: GitHub learns that this
IP address downloaded add-on *X* for YazSes version *Y*. That is download metadata, the same
as a manual download from the releases page. No user content, no identifier, no config value
and no dictation is sent. A test pins it: every `Request` the default opener builds during a
pack install is captured, and its URL must be one of the two computed URLs and its headers
must equal the asset headers exactly. This is the test ADR-027 wished it had before the 415.

**What `tests/test_egress_inventory.py` needs.** `packs/fetch.py` does not import `urllib`.
It calls ADR-027's shared download helpers, so **none of the three existing scans will find
it**. ADR-019 already learned this lesson three times: "a stated limitation is not a guard".
So the implementation adds a **fourth scan**: an AST scan for calls to the shared release
download entry points (`download_verified`, `fetch_checksums`, `fetch_release_payload`,
whichever module defines them after the refactor in §4a), from anywhere outside their
defining module. The result must equal a new declared dict, `FETCH_VIA`, with
`"packs/fetch.py": "add-on pack + SHA256SUMS.txt from the running version's release (ADR-028)"`.
The test is equality in both directions: no undeclared caller, no stale entry. Two further
assertions go with it:

- **User-initiated only.** No module reachable from `core/daemon.py`,
  `system/update_notify.py` or the runtime hook imports `packs.fetch` or `packs.install`.
  This uses the same import-closure machinery as `test_feature_wiring_honesty.py`.
- ADR-019's table gains the row above, and its Class A count is recomputed from `FETCH` and
  `FETCH_VIA` in the test, never written by hand.

ADR-019 itself is **not edited by this Proposed ADR**, because a row for a module that does
not exist yet would be false. The PR that adds `packs/fetch.py` edits both the ADR and the
test, and adds a sentence to `docs/privacy-statement.md`.

#### 4a. Reusing ADR-027's downloader, and the follow-up refactor it needs

This ADR adds **no second downloader**. From `system/installer_update.py` at
`integ/wave3-2026-10-20@95ddd869` it reuses `is_trusted_download_url`,
`is_allowed_redirect`, `parse_sha256sums`, `expected_sha256`, `fetch_checksums`,
`download_verified` (bounded `.part` file, deleted on mismatch, 30 s read timeout, overall
deadline), `request_headers` and `acquire_update_lock`'s `O_CREAT | O_EXCL` single-flight
pattern.

That module's owner will not rename anything, so the following is proposed as a
**separate follow-up refactor** with no behaviour change to the installer path:

- Introduce a neutral `ReleaseAsset(name, url, size, digest=None)`. `InstallerAsset` becomes
  a subclass that adds `version` and `arch`, or `ReleaseAsset` becomes an alias at first,
  so packs do not depend on a type named "Installer". `download_verified` reads only `name`,
  `url` and `size`, so its signature can be widened to `ReleaseAsset` without breaking
  callers. Until then, Phase 1 builds an `InstallerAsset` with the pack's `version` and
  `arch`, which works today.
- Optionally, move the transport half (allowlist, redirect handler, headers, bounded reads,
  checksums, `download_verified`) to `system/release_download.py` and re-export it from
  `installer_update.py`. ADR-019's FETCH row then moves with the `urllib` import.
- Add `cancel: Callable[[], bool] | None = None` to `download_verified`, checked per chunk.
  Today the only cancellation is raising from `progress`, which fires only every 10 %. On a
  220 MB pack that is 22 MB per step, too coarse for a Cancel button.
- **Per-pack `max_bytes`.** `download_verified` already takes it and caps at
  `min(max_bytes, asset.size)`. Packs pass the index's exact size and a hard ceiling of
  `PACK_MAX_BYTES = 1.9 GiB`, under GitHub's "under 2 GiB" per-asset limit
  ([About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)).
  The default `MAX_INSTALLER_BYTES` is never relied on.
- **A size-proportional deadline.** Pass `deadline_s = max(DOWNLOAD_DEADLINE_S, size / 50
  kB/s)`, so a 220 MB pack on a slow link is not cut off at 30 min while a stalled
  connection still dies on the 30 s read timeout.

### 5. UX

A pack-backed feature has these states. Every surface takes them from one pure function:

| State | Tray / Settings shows | CLI shows |
|---|---|---|
| not installed | "Needs the *Parakeet* add-on — 0.3 MB download, 1.2 MB on disk" + **Download & enable** | same line, then a `[y/N]` prompt (`--yes` skips) |
| downloading | progress bar in Settings; tray balloon at start, 50 % and done; **Cancel** button and tray menu item | `Downloading… 42 % (93 of 220 MB)`; Ctrl-C cancels |
| verifying / installing / testing | "Checking…", "Installing…", "Testing the add-on…" | same |
| installed | feature toggles normally; Settings › Add-ons lists size on disk | `yazses packs` lists it as `ok` |
| needs download for this version | "YazSes was updated. This add-on was built for 2.44.0 and is not loaded. **Download again (0.3 MB)**" | same, and `features` shows the feature as *waiting for add-on* rather than `on` |
| damaged | "The add-on is damaged (a file is missing — security software may have removed it). It was set aside. **Reinstall**" | same + `yazses packs verify` |
| unavailable here | "Add-ons are not available in the MSIX/Store version yet" (and so on per channel, §8) | the current `fixed_payload_reason` text, kept for these channels |

The rules behind it:

- **Dormant until installed.** `features enable` keeps its refuse-before-write rule. Config
  is written only after the pack has installed and passed its probe. A feature whose config
  says on but whose pack is missing or stale must read *waiting for add-on* on every
  surface, never `on`. This is the `Feature.inert` lesson, now applied to packs.
- **Price before charging (ADR-018).** Download size and unpacked size come from the
  embedded index, exact and offline. Free disk space is checked before the download starts
  (archive plus unpacked size plus 10 %). Model downloads that follow on first use
  (Parakeet weights, MediaPipe) are still announced by the existing `depsize` note,
  separately: a pack carries libraries, never models.
- **Failure messages are actionable** (the #310 lesson). Offline: "Couldn't reach
  github.com to download the Parakeet add-on. Check your connection or proxy and try again.
  Nothing was changed." Each failure message also names the asset to download by hand and
  the `yazses packs install --from <file>` command (Phase 2). Checksum mismatch: "did not
  match the checksum built into this copy of YazSes; it was deleted and nothing was
  installed."
- **Cancel leaves no trace.** The `.part` file is deleted and nothing is written to config.
- **Location is visible.** Packs live in `%LOCALAPPDATA%\yazses\packs\`, which is
  `Paths.data_dir / "packs"`, local and not roaming. Settings › Add-ons shows the folder,
  the total size, **Open folder** and **Remove unused**. `yazses packs path` prints it.
- **Removal is explicit.** Disabling the last feature that uses a pack *offers* to remove
  it ("Free 220 MB?"). It never deletes silently. `yazses packs remove <name>|--all`.
- **Who does the work.** The process where the user clicked does it: the tray, the
  Settings window or the CLI. The daemon does not, and no IPC method is added in Phase 1.
  The daemon then restarts through the existing `features enable` → restart path, which is
  also when the new pack is mounted. **Hot-mounting into a running daemon is rejected.**
  An earlier failed import of the same name leaves state in `sys.modules` and the import
  caches, and a restart is already the contract (`Apply it: yazses restart`).

### 6. Lifecycle

- **Install transaction:** take the single-flight lock `packs/<name>.lock`, check disk
  space, `download_verified` into `packs/downloads/`, cross-check against
  `SHA256SUMS.txt`, extract to `packs/staging/<name>.<random>/`, check against
  `RECORD.json`, then run the **import probe**. The probe starts a child process,
  `yazses-cli.exe --cli packs probe <name>`, which mounts the staged tree and imports
  `entry_modules`, with a 120 s timeout. A native crash kills only the child. If every step
  passes: `os.replace` into `packs/<build-id>/<name>/`, write `COMPLETE`, update
  `packs/state.json`, delete the archive. If any step fails: delete staging and the
  download, leave config unchanged, and report the step that failed.
- **Extraction is defensive** even though the archive is hash-verified. Every entry name is
  checked against an allowlist: relative, no drive or UNC prefix, no `..`, no symlink or
  absolute path, length within budget. The entry count and total size must equal the
  manifest, and the compression ratio is capped. Python's own documentation says "never
  extract archives from untrusted sources without prior inspection" and names
  decompression bombs ([zipfile](https://docs.python.org/3/library/zipfile.html)).
- **Path length:** the build rejects any relative path inside a pack longer than 140
  characters, and the install directory uses short components. The total therefore stays
  under `MAX_PATH` (260) without relying on the opt-in long-path mode, which needs both a
  registry value and a `longPathAware` manifest
  ([Maximum path length](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation)).
- **Upgrades:** packs follow the app version and are **never carried across builds**. After
  ADR-027's one-click update relaunches YazSes, the new base finds no
  `packs/<new-build-id>/` and `state.json` still lists what the user had. The tray then
  shows **one** notification: "Updated to 2.45.0 — 2 add-ons (Parakeet, Diarization; 21 MB)
  need to be downloaded again. **Download now** / Later". The re-download follows that
  click. It is user-initiated, so it does not break §4. Until then those features read
  *waiting for add-on*. Folding the re-download into the update confirmation itself
  ("this update also re-downloads your add-ons, 21 MB") is a later refinement, because it
  needs the *new* release's index before the update runs.
- **Rollback:** the previous build's pack directory is kept until the new build has
  completed one successful start (a `started-ok` marker the tray writes after it is up).
  ADR-027 relaunches the *old* version when an update fails, and it needs its packs.
  Directories for any other build are then garbage-collected.
- **Removal:** `yazses packs remove` deletes the directory and the `state.json` entry. The
  per-user Inno uninstaller deletes `{localappdata}\yazses\packs` (`[UninstallDelete]`),
  because it is code only this app can use. Config and models keep their current policy.
  An all-users uninstall runs elevated as the administrator and cannot reach other users'
  folders, which is an open question below.
- **Integrity at load:** see §2. The startup check is O(1), and a full check runs on any
  pack import failure, in `doctor`, and in `yazses packs verify`.

### 7. Build

Packs are produced **in the same `build-windows.yml` job as the installer, from the same
`.venv`, interpreter and `uv.lock`**, by `scripts/build-packs.py`. The steps go between
PyInstaller and Inno:

1. Write `base-manifest.json` over `dist/YazSes/` and compute `base_build_id`.
2. Compute the base distribution set with `uv export --frozen --no-dev --extra desktop`.
3. For each pack declared in `packaging/packs/packs.toml`:
   - `uv export --frozen --no-dev --extra desktop --extra <X>` minus the base set gives a
     hash-pinned requirements file.
   - Install it with `uv pip install --target <work>/site --no-deps --require-hashes
     --only-binary :all: --compile-bytecode --python <the build venv's python>`. The
     packages go into a separate directory, **never into the venv PyInstaller analysed**.
   - Run the checks: module, DLL and distribution collisions; `.pth`; path length; size;
     licence manifest. Then write `pack.json` and `RECORD.json`, and zip
     **deterministically**: sorted entries, a fixed timestamp, fixed permissions.
4. Write the index and copy it into `dist/YazSes/_internal/`. Then **recompute the base
   manifest without that one file and require it to be byte-identical to step 1.** This is
   the guard that the base installer's contents are unchanged by pack production.
5. **Frozen probe on the runner.** For each pack, run `dist\YazSes\yazses-cli.exe --cli
   packs probe <name>` against a sandboxed data dir. This is the CI gate that a pack
   actually imports inside the frozen app on real Windows, and it is the check that will
   find stdlib gaps and missing base metadata (§ open risks).
6. Inno, smoke test, attestation (`subject-path` covering the packs and the index) and
   release upload, as today.

**Which extras qualify.** An extra becomes a pack only if all of these hold:

- (a) A **wired** feature consumes it: its slug is in `_FEATURE_DEPS` and not in
  `_UNWIRED`.
- (b) Every distribution beyond the base has a wheel for the target. `--only-binary :all:`
  rules out sdist builds.
- (c) It is not already in the base (`desktop`/`overlay` serve `tray`/`overlay`, which are
  bundled).
- (d) It passes the collision checks and the frozen probe.
- (e) The archive is under the 1.9 GiB ceiling. A pack over **500 MB** needs an explicit
  `approved_large = true` entry with the owner's name in `packs.toml`.

"Native libs" are not a disqualifier; they are what the DLL checks and the probe are for.
Below a size floor (1 MB, pure Python: `chinese`, possibly `parakeet`), bundling into the
base instead is the cheaper option. That would change the base, so it is the owner's call
(open question). Until it is made, those extras are packs too. A test holds `packs.toml` to
the extras in `pyproject.toml` and the slugs in `_FEATURE_DEPS`. Every wired dependency-
carrying slug is either served by a declared pack or listed with a reason
(`no-windows-wheel`, `bundled`, `unwired`, `deferred`). A new extra cannot silently be
missing a decision.

**Release asset naming** (per arch; x64 only today):

- `YazSes-<v>-windows-<arch>-pack-<extra>.yazpack`
- `YazSes-<v>-windows-<arch>-packs.json` (the index; the same bytes as the embedded copy)
- `YazSes-<v>-windows-<arch>-packs.intoto.jsonl`

These names cannot match the installer patterns other consumers anchor on
(`installer_update._ASSET_RE` `…-windows-(x64|arm64)\.exe$`, `render-chocolatey.py`,
`publish-channels.yml`'s `windows-x64\.exe$` count). Several hand-written lists must gain
the new suffixes in the same PR, or `SHA256SUMS.txt` will silently not cover the packs:

- `checksums.yml`'s glob `*.deb *.dmg *.exe *.intoto.jsonl` and its "prove" regex
  `\.(exe|dmg|deb)$`;
- `scripts/verify-release-assets.py`'s `ARTIFACT_SUFFIXES`.

The spec lists the full set. Each list is one more place a new asset kind can go uncovered
without anything turning red.

### 8. Scope by channel

| Channel | Decision | Why |
|---|---|---|
| **Inno `.exe`, per-user** | **Phase 1.** `profile=windows-exe`, `install_method=windows-installer` | The case the owner named. The data dir is user-writable and the process is unelevated. |
| Inno `.exe`, all-users | Phase 1 too: packs are per-user and load unelevated | Nothing elevated ever loads them (§2.1). The uninstaller gap is an open question. |
| winget | Rides with the `.exe` | ADR-027: a winget install is the same Inno payload and cannot be told apart from it. Same build id, same behaviour. Verified with the `.exe` checklist. |
| Chocolatey | Phase 2 | Same payload, installed machine-wide and elevated. Packs are still per-user and unelevated. Gated off by an explicit allowlist (`PACK_INSTALL_METHODS`) until its checklist item passes. |
| Scoop | Phase 2 | Same payload, extracted to `~\scoop\apps\yazses\current`. `scoop update` changes the build, so packs re-fetch. Same allowlist gate. |
| **MSIX** | Out of Phase 1–2 | Three unknowns. (1) Writes to AppData are redirected to "a private per-user, per-app location", visible only to the app and "removed on uninstall" ([Flexible virtualization](https://learn.microsoft.com/en-us/windows/msix/desktop/flexible-virtualization)). That is workable, but loading DLLs from the redirected location is unverified. (2) Packaged processes always use the packaged-app DLL search order, which lists no `AddDllDirectory` step ([DLL search order](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order)), so §2.5 might not work at all. (3) Store policy 10.2.2 forbids extending "described functionality … through any form of dynamic inclusion of code" ([Store policies](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies)). Packs would have to be in the listing's described functionality, or MSIX would need a Store-native mechanism (optional packages). Owner question. |
| **macOS `.app`** | Later phase, own ADR addendum | Same format with `macosx_*` wheels, `DYLD`-free loading through `sys.path`, and no DLL step. The bundle's entitlements already include `com.apple.security.cs.disable-library-validation`, which is what lets a hardened-runtime process load libraries not signed by its team ([Apple](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.cs.disable-library-validation)). The index ships inside the signed and notarised `.app`, so packs inherit that authenticity, which is better than on Windows today. Whether notarisation should also cover each `.yazpack`, and the Intel-Mac deadline (ADR-017), go in that addendum. |
| snap | Out of scope | Not PyInstaller: a staged Debian Python on a read-only squashfs. A pack format for it would be a different ABI. The channel-native route is snap components. |
| flatpak | Out of scope | Likewise; the native route is a flatpak extension. |
| PyPI / pipx / uv tool | Unchanged | `deps.install_packages` keeps working. Packs never activate when `sys.frozen` is unset. |

`cameraperm/matrix.py::PackageProfile` gains `can_add_packs: bool`, and
`deps.fixed_payload_reason` returns `None` for a pack-capable profile when a pack exists for
the feature in the embedded index. So `doctor`, the camera matrix and `features enable`
cannot disagree, which is the EYE-PERM-001 rule.

### 9. Test plan (summary; the spec has the full list)

**Pure and offline, run in the ordinary suite:**

- manifest and index parsing;
- the match function (build id, Python, arch, name, hash), with every refusal reason;
- path layout;
- zip-member validation (traversal, drive or UNC, symlink, length, count, size and ratio);
- `RECORD.json` checking;
- the quarantine and stale decisions;
- the state machine behind §5;
- the feature → pack catalogue against `pyproject.toml` and `_FEATURE_DEPS`;
- the disk-space arithmetic;
- the GC and rollback policy.

**Backends and orchestration with fakes:** the install transaction with injected download,
extract and probe, covering each failure point (nothing left behind, config untouched).
Mounting goes through a fake `PackRuntime` that records `add_dll_directory` calls and
`sys.path` order. The captured-`Request` egress test. The fourth egress scan
(`FETCH_VIA`) and the "never from the daemon or watcher" closure test. The build-script
collision checks run on synthetic wheel trees.

**On the Windows CI runner (real, not mocked):** the frozen probe of every pack and the
base-manifest invariance check.

**Needs real consumer Windows (manual checklist in the spec):** Defender and Smart App
Control behaviour on first load; a pack DLL that depends on a base DLL; a user name with a
space, an apostrophe and non-ASCII characters; a long `%LOCALAPPDATA%`; cancel mid-download;
re-fetch after a one-click update; rollback after a failed update; the all-users install;
Chocolatey and Scoop; and, later, MSIX DLL loading from virtualised AppData.

## Revision (2026-10-21, first Phase 0 spike)

`packs-spike.yml` run 39631811305 (windows-latest, main c946e71e): risks (a)–(d) measured and
passed for `diarization`; sherpa-onnx binds to the base's MS-signed onnxruntime 1.28.0 (the bind
row's FAIL was a relative-vs-absolute path comparison in the probe, fixed in the build script).
The out-of-process fallback (§1) is not needed. Details: the spec, *Implementation status*.

## Consequences

**Good.** The base `.exe` stays as it is. A Windows user turns on Parakeet and gets it,
with no move to PyPI. Every pack is tied to one exact build and checked against a hash the
installed app already holds, so it is exactly as authentic as the installer, and becomes
fully authenticated the day signing goes live. The egress row is narrow: one host, the
running version's tag, after a click, carrying nothing about the user.

**Costs, accepted.**

- Release CI grows by one pack build plus one frozen probe per pack, and each release
  publishes about 10 more assets.
- Every app update means re-downloading the add-ons the user had. That is the price of
  never loading a stale ABI, and it is announced.
- A second interpreter-adjacent tree exists on users' disks, and the build has to keep
  collision checks for it.

**Open risks this ADR names rather than solves.** The Phase 0 spike settles them:

- **Stdlib gaps.** PyInstaller collects only the stdlib modules the base imports, so a pack
  may import one that is absent. The `stdlib/` supplement covers it.
- **Base distributions' metadata.** The spec only runs `copy_metadata("yazses")`, so a pack
  calling `importlib.metadata.version("numpy")` fails. The remedy is metadata-only additions
  for the base distributions packs depend on, and it is the one permitted base change.
- **Base distributions' uncollected submodules.** A pack may need a submodule of a frozen
  base package that PyInstaller pruned. The remedy is `collect_submodules` for those
  packages, measured, and also a base change.
- **The `sherpa-onnx` ONNX Runtime collision** (§1).

Each of these is caught by the frozen probe in CI before a release ships, rather than on a
user's machine.

## Owner questions: answered 2026-10-21

The owner asked for these eight questions to be researched and answered. The evidence is in
[`design/research/2026-10-21-pay-for-what-you-enable.md`](../research/2026-10-21-pay-for-what-you-enable.md),
plus a measured pass over the `uv.lock` Windows wheels (each wheel downloaded and its
SHA-256 checked against the lock). Until the code changes listed below land, the code keeps
its most cautious behaviour, which is what landed in `e50e35f2`. This ADR stays
**Proposed**, because acceptance waits on the Phase 0 spike.

1. **Bundle the tiny pure-Python extras: yes, both, in the frozen base only.**
   - `onnx-asr` 0.12.0 is MIT, a 3.98 MB `py3-none-any` wheel (7.0 MB unpacked). Its
     `[cpu,hub]` dependencies are already in the base.
   - `opencc-python-reimplemented` 0.1.7 is Apache-2.0, a 0.48 MB wheel.
   - Neither ships native code. Together they add about 4.5 MB, about 2.4% of the 188 MB
     v2.43.2 installer.
   - The heavy part of Parakeet is its model (int8, about 661–670 MB, CC-BY-4.0, which
     requires attribution). It downloads on first use either way, so a pack would save
     almost nothing.
   - The PyPI base does not change; ADR-016 still governs it.
   - Consequence: Phase 1 is proven on `diarization`, the pack with native code, which is
     where the mechanism can actually fail.
   - Code change:
     - `scripts/build-windows.ps1` syncs `--extra parakeet --extra chinese`;
     - `packaging/packs/packs.toml` marks both `bundled`.
2. **Torch packs: no. `voiceprint` stays PyPI-only, and its replacement is an ONNX backend.**
   - The voiceprint set is about 173 MB compressed and well over 500 MB unpacked. The
     torch 2.13.0 Windows wheel alone is 122 MB (466 MB unpacked) and is already CPU-only.
   - It serves one EXPERIMENTAL feature (`cocktail`).
   - Torch's `libiomp5md.dll` shares a basename with the base's (it ships with
     ctranslate2) but has different bytes. Torch loads its DLLs by full path, so two OpenMP
     runtimes can load into one process. That is the documented
     "OMP: Error #15" failure for CTranslate2 + PyTorch on Windows.
   - torchaudio 2.11.0 declares no torch requirement and is locked against torch 2.13, so
     that ABI pairing is unverified.
   - The route forward is a `sherpa_onnx.SpeakerEmbeddingExtractor` backend for
     `voiceprint`:
     - `recimport/diarizer.py` already uses that extractor with a 39.6 MB model;
     - 26–30 MB models exist;
     - it would ride on the diarization pack;
     - existing enrolments must be re-enrolled, because embeddings differ across models.
   - Code change: none now; `voiceprint` stays `deferred`, with this reason.
3. **Re-download after an update: ask at update-confirm, download from the new build.**
   - The update confirmation names the installed packs and their sizes from the *old*
     index ("this update will also re-download Diarization, 19 MB").
   - The *new* app then fetches them on first launch and verifies them against its own
     embedded index.
   - This is how Steam DLC and Windows Features on Demand behave.
   - It adds no pre-update fetch and no second trust path.
   - If the user declines, or a download fails, it falls back to the proposed one click
     after relaunch.
   - Code change: today nothing is re-fetched (`packs remove --all` is the only cleanup).
     The ADR-027 confirm text and a first-launch re-sync job both need to be added.
4. **All-users uninstall: accept the gap and document it.**
   - Inno Setup's own guidance is that in administrative mode "user-level files and
     settings must be handled by the application itself"
     ([Inno Setup](https://jrsoftware.org/ishelp/topic_admininstallmode.htm)).
   - The uninstaller removes the elevating user's `packs\`.
   - The uninstall page and `doctor` name `yazses packs remove --all` for the other users.
   - Leftover packs are inert: nothing loads them without the app, and a later build
     ignores them because its build id differs.
   - Active Setup is rejected. It is undocumented on Microsoft Learn, runs synchronously at
     every logon with no timeout, and leaves a registry entry behind after uninstall.
   - Code change: `[UninstallDelete]` for the running user's pack root, plus documentation.
5. **Offline install from a file: yes, in Phase 2.**
   - `yazses packs install --from <file>` accepts only a file whose SHA-256 is in the
     embedded index. It reuses the verify, extract, probe and commit pipeline.
   - Because the expected hash comes from the installed app, a matching file is
     byte-identical to the CI output, however it was carried. This is the same trust as a
     fetched pack, and the same limit (an unsigned installer).
   - The UI names the exact asset file for this build id.
   - Precedents: `code --install-extension <file.vsix>`, `pip --no-index --find-links`,
     and DISM `/Source /LimitAccess`.
   - It closes the firewall class of failure first reported by a real user in #310.
6. **MSIX: no MSIX packs. The Store route stays the unpackaged `.exe` (policy 10.2.9).**
   - `packaging/store/README.md` already chose that route.
   - The Store listing describes the optional add-ons as downloaded on request. That keeps
     them within "described functionality" under policy 10.2.2 (Store Policies v7.20,
     2026-09-15).
   - MSIX optional packages that contain code need Microsoft's permission and UWP-era
     tooling, and MSIX is not a released asset today.
   - **Risk to raise with Microsoft before submitting:** 10.2.9 requires that "the binary
     and all of its Portable Executable (PE) files" be signed. The base already carries
     unsigned upstream PE files (ctranslate2, numpy, PortAudio), and SignPath forbids
     signing upstream binaries.
7. **Licences: yes to per-pack `LICENSES/` plus a build gate, with three rules.**
   1. **Permissive licences and LGPL pass.** LGPL is already in the frozen base (PySide6),
      and libsndfile, FFmpeg (inside opencv) and soxr are LGPL. LGPL needs a source offer
      and loose, replaceable DLLs; the pack layout already gives the latter.
   2. **GPL needs the owner's explicit, recorded approval per pack**, as a `packs.toml`
      field, plus a `SOURCE.md` giving exact upstream source URLs, tags and hashes. This
      covers:
      - `tts`: espeak-ng inside `espeakng-loader`, and **`phonemizer` 3.4.0, which the
        first draft missed**;
      - `prosody`: `praat-parselmouth`.
      
      YazSes is Apache-2.0, which is GPLv3-compatible, so these packs are permissible. The
      FSF treats in-process loading as one combined program, even when the parts are
      downloaded separately. Distributing the packs therefore carries GPLv3 source duties.
      This is engineering analysis, not legal advice.
   3. **An unknown licence or a missing licence file fails the build.** Today that catches
      `espeakng-loader` (empty metadata, no licence file) and `sherpa-onnx-core` (no
      notices, although it bundles MIT ONNX Runtime). Metadata-only tools cannot see a
      GPL binary inside a wheel, so the gate uses `pip-licenses` for metadata and ScanCode
      or a reviewed per-pack allowlist for bundled files.
   - Code change: today there is no gate, the licence texts are copied, and `tts` is
     deferred.
8. **Signing: yes, move it ahead of other release work, justified by the base installer.**
   - A signed installer:
     - builds SmartScreen reputation on the certificate (EV no longer bypasses
       SmartScreen);
     - meets Store policy 10.2.9;
     - gets past Smart App Control;
     - anchors the embedded pack index, and with it every pack hash.
   - It does **not** make pack DLLs pass Smart App Control. Almost all of them are unsigned
     upstream builds; the exceptions are Microsoft's ONNX Runtime and Intel's OpenMP.
     SignPath's terms forbid signing them, and an Authenticode signature on a ZIP is
     invisible to Windows. Smart App Control behaviour for packs stays a Phase 1 manual
     checklist item.
   - Routes:
     - **SignPath Foundation** (application answered 2026-09-13; current status
       unverified);
     - **Certum's open-source certificate** (€69 with a hardware card; listed out of stock
       on 2026-10-21; impractical from hosted CI);
     - Azure Trusted Signing is excluded by owner policy.

**Findings from the same pass that change Phase 1:**

- **`sherpa-onnx-core` 1.13.8's Windows wheel ships its own `onnxruntime.dll`.** It is an
  unsigned 1.28.2 build. The base has Microsoft's signed 1.28.0.
  - §1 asked whether the Windows wheel carries its own ONNX Runtime: it does.
  - Under §1's rule the diarization pack therefore fails the build, and the build withholds
    it.
  - Proposed resolution:
    - drop sherpa's copy and bind to the base's ONNX Runtime (same 1.28 line);
    - prove that with the spike's loaded-module probe (`rthook_pack_spike.py`, check (d));
    - if the probe fails, take §1's recorded out-of-process route.
- **The `gaze` closure contains both `opencv-python` and `opencv-contrib-python`.** The
  extra declares the first; mediapipe 1.0.1 requires the second. Both own `cv2`, which
  fires the module-collision rule and duplicates about 70 MB on every platform.
  - Fix: drop `opencv-python` from the extra, because contrib is a superset.

