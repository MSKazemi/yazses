# Spec: Feature Add-on Packs — fetch, verify and load a feature's libraries in a frozen install

| Field | Value |
|---|---|
| **ID** | spec-feature-addon-packs |
| **Status** | Proposed |
| **Date** | 2026-10-20 |
| **Decision record** | [ADR-028](../adr/adr-028-feature-addon-packs.md) |
| **Related** | ADR-019 (egress), ADR-018 (price first, no plug-ins), ADR-016 (dependency budget), ADR-027 (one-click Windows update, unmerged branch `integ/wave3-2026-10-20`) |
| **Modules** | new `src/yazses/packs/` (pure core + orchestration), new `PackRuntime` Protocol in `platform/base.py`, `platform/windows/packs.py`, `packaging/windows/rthook_yazses_packs.py`, `scripts/build-packs.py`, `packaging/packs/packs.toml` |

## Goal

When a user turns on a heavy feature in a frozen Windows install, YazSes shows the price,
downloads that feature's add-on pack from the running version's GitHub release, verifies
it against the hash built into the installed app, installs it per user and loads it on the
next start. The base installer does not change.

## Non-goals

- **Third-party plug-ins.** ADR-018 §3 stands. Only packs listed in the embedded index of
  the running build can be installed or loaded.
- **Models.** Packs carry libraries. Model weights keep their existing first-use fetch
  paths and egress rows.
- **Background or automatic downloads**, including after an update.
- **Hot-mounting** into a running daemon. Mounting happens at process start.
- MSIX, macOS `.app`, snap and flatpak in Phases 0–2 (see ADR-028 §8).
- In-app Sigstore/SLSA verification (rejected for now, ADR-028 §3).

## Module list

The house split applies: pure modules with no I/O beside thin backends that are injected.

| Module | Kind | Responsibility |
|---|---|---|
| `packs/manifest.py` | pure | Parse and validate `pack.json`, `RECORD.json` and the index (`format: 1`). Return typed dataclasses or a `ManifestError` with a user sentence. Never raise anything else. |
| `packs/abi.py` | pure | `BaseIdentity` (build id, Python cache tag and patch version, platform, arch, app version), read from the embedded index plus `sys` facts that are passed in. `match(pack, base, index_entry) -> Match` returns `ok`, `stale` or `refused`, with one reason per field. |
| `packs/layout.py` | pure | The paths below `data_dir/packs`, short components, and the 140-character budget. `build_dir(build_id)` uses the first 12 hex digits plus a collision guard read from `state.json`. |
| `packs/archive.py` | pure | Zip member validation (names, kinds, counts, sizes, ratio) over a list of `(name, size, compressed, is_dir, external_attr)` tuples, so no real archive is needed in tests. `check_tree(record, stat_fn)`. |
| `packs/catalog.py` | pure | Feature slug to pack name, derived from `_FEATURE_DEPS` and the extras in `pyproject.toml`, plus the `packs.toml` decisions (`pack`, `bundled`, `no-windows-wheel`, `unwired`, `deferred`). |
| `packs/state.py` | pure | The per-feature state machine in ADR-028 §5 and the `state.json` schema. Inputs: catalogue, index, installed trees, config. Output: one `PackStatus` per feature. |
| `packs/policy.py` | pure | Disk-space arithmetic, the size-proportional deadline, the `PACK_MAX_BYTES` ceiling, GC and rollback choices (keep the current build, keep the previous build until `started-ok`, delete the rest), and the quarantine-or-stale decision. |
| `packs/fetch.py` | I/O, **egress** | Builds the two URLs (`SHA256SUMS.txt` and the pack) for tag `v<running version>`, then calls ADR-027's `fetch_checksums`, `expected_sha256` and `download_verified`. It is the only module that starts a pack download, and the `FETCH_VIA` entry in the egress test. |
| `packs/install.py` | orchestration | The install transaction (ADR-028 §6) with injected `fetch`, `extract`, `probe`, `replace` and `clock`. Returns `InstallResult(ok, title, message, steps, log_file)`. It never raises to the UI. |
| `packs/mount.py` | pure decision + backend call | `plan_mount(base, installed, env, elevated) -> MountPlan` (paths to append, native dirs, quarantines). `apply(plan, runtime)`. |
| `packs/probe.py` | CLI-side | `yazses packs probe <name> [--staged <dir>]` mounts one tree and imports `entry_modules`. Exit 0, or a non-zero code naming the module that failed. |
| `platform/base.py` | Protocol | `PackRuntime`: `supported() -> bool`, `is_elevated() -> bool`, `add_native_dir(path) -> object` (a handle that is kept alive), `embedded_index_path() -> Path \| None`. |
| `platform/windows/packs.py` | backend | `os.add_dll_directory`, a token-elevation check (`GetTokenInformation(TokenElevation)` via pywin32, already a base dependency), and `Path(sys._MEIPASS) / "yazses-packs-index.json"`. Registered in `platform/factory.py`. |
| `platform/{linux,macos}/…` | backend | `supported() -> False` until their phase. |
| `packaging/windows/rthook_yazses_packs.py` | runtime hook | Three lines: import, call `mount.mount_at_startup()`, swallow every exception. |
| `cli.py` | surface (L3) | `yazses packs [list] / install / remove / verify / path / probe / clean`. `features enable` integration. |
| `tray/…`, `settingsui/controller.py` | surface | States and actions from `packs/state.py`. Progress and cancel go through `install.py` callbacks. |
| `cameraperm/matrix.py` | data | `PackageProfile.can_add_packs`. |
| `system/deps.py` | integration | `fixed_payload_reason` returns `None` when the profile can add packs and the index has the feature's pack. |
| `scripts/build-packs.py` | build | ADR-028 §7. Stdlib plus `uv` only, so it runs on the Windows runner without new dependencies. |
| `packaging/packs/packs.toml` | build data | Per-extra decision, entry modules, `approved_large`, `shared_with`. |

**A rule for every module above:** nothing under `packs/` branches on `sys.platform`. The
OS facts come through `PackRuntime` (AGENTS.md rule 6).

## On-disk layout (Windows)

```
%LOCALAPPDATA%\yazses\packs\
  state.json                    installed packs per build, last results, started-ok
  b-<12hex>\<name>\             one tree per pack per base build
      COMPLETE                  written last
      pack.json  RECORD.json  site\  stdlib\  LICENSES\
  staging\<name>.<rand>\        extraction in progress; deleted on any failure
  downloads\<asset>.part        ADR-027 download_verified's bounded .part file
  quarantine\<name>-<UTC>\      + reason.txt
  <name>.lock                   O_CREAT|O_EXCL single-flight; stale after 2 h
```

## Phases

### Phase 0: spike on the Windows runner (no user-visible change)

The goal is to settle ADR-028's open risks with evidence before any surface is built.

- A throwaway workflow (`workflow_dispatch` only) builds the base as today, then builds
  the `parakeet` and `diarization` packs with a first version of `scripts/build-packs.py`,
  and runs `yazses-cli.exe --cli packs probe` for each, using a hand-written mount in a
  test entry point.
- Record and decide:
  1. whether appending to `sys.path` imports pack modules in the frozen app (expected yes,
     per PyInstaller's bootstrap order);
  2. stdlib gaps hit by each pack's imports, and whether the `stdlib/` supplement is
     needed;
  3. `importlib.metadata` lookups against base distributions;
  4. pruned submodules of base packages (`onnxruntime`, `huggingface_hub`, `numpy`);
  5. the DLL-basename collision report for `sherpa-onnx-core` against the base's
     `onnxruntime`;
  6. Windows pack sizes, which replace the Linux figures in ADR-028's table.

**Acceptance:**

- A written result, recorded in the ADR's Revision section, with the run id.
- A decided list of permitted base changes: metadata-only and/or `collect_submodules` for
  named base distributions, each with its measured size cost.
- If the collision is real, a decision for `diarization`: a shared ONNX Runtime, an
  out-of-process route, or deferral.

### Phase 1: mechanism + `parakeet` and `diarization` packs, Inno `.exe` only

> **Changed by ADR-028 Q1 (answered 2026-10-21):** `parakeet` is bundled into the frozen
> base instead of packed, so Phase 1 ships one pack, `diarization`. Criteria below that
> name `parakeet` or `stt-parakeet` apply to `diarization` and `diarize`; on a pack-capable
> install `stt-parakeet` needs no add-on, only its model download.

Build:

- `scripts/build-packs.py` and `packs.toml` with the two packs.
- `build-windows.yml` steps between PyInstaller and Inno (ADR-028 §7, steps 1–5).
- Provenance attestation with `subject-path: dist/packs/*`, and the
  `…-packs.intoto.jsonl` asset.
- `checksums.yml`: glob gains `*.yazpack` and `*-packs.json`, and the "prove" regex gains
  them too. `scripts/verify-release-assets.py` `ARTIFACT_SUFFIXES` gains `.yazpack`.
  `release-complete.yml` checks that every pack in the published index is attached and
  listed in `SHA256SUMS.txt`. The list is read from the index, not written by hand.
- The runtime hook in `packaging/windows/yazses.spec`.

Runtime:

- Every pure module, `packs/fetch.py`, `install.py`, `mount.py` and `probe.py`, the
  Windows `PackRuntime`, `PackageProfile.can_add_packs` (true for `windows-exe` only), and
  `PACK_INSTALL_METHODS = {"windows-installer"}`. winget rides with it (ADR-027: it cannot
  be told apart).
- Surfaces:
  - CLI: `yazses packs`, `install`, `remove`, `verify`, `path`, `probe`, `clean`, plus the
    `features enable` prompt with size, `--yes`, Ctrl-C cancel and the `--no-install`
    message.
  - Tray: Download & enable, progress balloons, Cancel menu item, and the post-update
    re-download notification.
  - Settings: per-feature button, progress bar, Cancel, and the Add-ons section with
    location, size, Open folder and Remove unused.
- `[UninstallDelete]` for `{localappdata}\yazses\packs` in `installer.iss`.

Egress:

- The ADR-019 row and Class A recount.
- The fourth scan (`FETCH_VIA`), the user-initiated closure test, and the captured-`Request`
  test.
- `docs/privacy-statement.md` sentence; `tests/test_docs_network_claims_are_complete.py`
  extended.

Docs:

- `CHANGELOG.md` `[Unreleased]`.
- Regenerated `docs/cli-reference.md` and `docs/command-index.md` (`make docs`, `make man`).
- A user page `docs/addons.md`: what an add-on is, where it lives, how to remove it, and
  manual download.
- `docs/install-cost.md` rows for Windows.
- `design/architecture.md` (new module and the new invariant: "no stale pack is ever
  loaded").

**Acceptance criteria:**

1. On a release build, the base-manifest invariance check passes. The `_internal` DLL set
   and the distribution set equal those of the previous release, apart from the Phase 0
   permitted changes.
2. `SHA256SUMS.txt` lists both packs and the index. `gh attestation verify` succeeds for
   each pack with `--signer-workflow MSKazemi/yazses/.github/workflows/build-windows.yml`.
3. The frozen probe passes on the runner for both packs, or the job fails and the release
   gets no packs. It never publishes a pack that did not probe.
4. Enabling `stt-parakeet` in a per-user `.exe` install shows exact sizes. A click
   downloads, verifies, probes and installs the pack, then writes config, then restarts
   the daemon. Parakeet then transcribes. `yazses doctor` shows the pack as `ok`.
5. A corrupted archive (one byte flipped in the cache), a wrong `SHA256SUMS.txt` line, a
   pack from another build id, a truncated download, a cancelled download and a full disk
   each end with nothing installed, config unchanged and an actionable message.
6. After a one-click update (ADR-027) to a build with a new id, the old pack is not
   loaded. The feature reads *waiting for add-on*, and one click re-downloads it. After the
   new build's first `started-ok`, the old build's tree is removed. If the update fails and
   the old version relaunches, its packs still load.
7. Deleting one DLL from an installed pack shows *damaged — reinstall* at the next import
   attempt. The tree is in `quarantine\` with a reason, and Reinstall restores the feature.
8. With `YAZSES_NO_PACKS=1`, YazSes starts and every pack-backed feature reads *waiting for
   add-on*.
9. Every pure-module test runs in the ordinary offline suite. `ruff` and `pytest` are green
   and `mypy src` reports no issues.

### Phase 2: the remaining qualifying packs, Chocolatey, Scoop, offline install

- `packs.toml` adds whichever of `gaze`, `tts`, `prosody`, `denoise` and `moonshine`
  pass the licence gate (ADR-028 Q7, answered: permissive and LGPL pass; GPL needs a
  recorded owner approval and a `SOURCE.md`; an unknown licence fails). `chinese` is not
  among them: ADR-028 Q1 bundled it, with `parakeet`, into the frozen base.
- `PACK_INSTALL_METHODS` adds `choco` and `scoop` once their checklist items pass.
- `yazses packs install --from <file>` (ADR-028 Q5, answered yes): the file name must
  equal the expected asset name and its SHA-256 must equal the embedded index entry. No
  network.
- `cancel` and `ReleaseAsset` from the ADR-028 §4a follow-up refactor, if it has landed.
  Otherwise Phase 1's coarse cancel (raising from `progress`) is documented as a known
  limit.

**Acceptance:**

- Each new pack meets Phase 1 criteria 1–7.
- `gaze`'s pack loads OpenCV and MediaPipe from `native_dirs`, and the camera matrix,
  `doctor` and `features enable` agree on every row (EYE-PERM-001).

### Phase 3: large packs and other channels (each needs an owner decision)

- Not `voiceprint`: ADR-028 Q2 answered no torch packs. It stays PyPI-only; the route
  forward is an ONNX speaker-embedding backend riding on the `diarization` pack.
- MSIX, after the spike in ADR-028 §8 on `AddDllDirectory` inside a packaged process and
  DLL loading from virtualised AppData, and after the Store-policy question.
- The macOS `.app`, in an ADR-028 addendum.

**Acceptance:** whatever the deciding addendum defines. None of it is implied by this
spec.

## Contracts

### Index (`YazSes-<v>-windows-<arch>-packs.json`, also `_internal/yazses-packs-index.json`)

```json
{
  "format": 1,
  "app_version": "2.44.0",
  "base_build_id": "sha256:…",
  "python": {"cache_tag": "cpython-312", "version": "3.12.9", "abi": "cp312"},
  "platform": "win-amd64",
  "arch": "x64",
  "packs": [
    {"name": "parakeet", "asset": "YazSes-2.44.0-windows-x64-pack-parakeet.yazpack",
     "sha256": "…", "size": 312345, "unpacked_bytes": 1234567, "files": 210,
     "features": ["stt-parakeet"]}
  ]
}
```

Rules:

- Unknown `format`: refuse every pack, and say "this add-on index needs a newer YazSes".
- Unknown keys are ignored. Missing required keys: refuse.
- `asset` must equal `YazSes-<app_version>-<platform os>-<arch>-pack-<name>.yazpack`,
  re-derived and compared rather than trusted.

### `features enable` in a pack-capable install

1. The unwired and experimental refusals stay as they are.
2. If `_missing_feature_deps(feat)` is empty, the existing path runs.
3. Otherwise, look up the catalogue:
   - no pack for this build: the existing `fixed_payload_reason` message, reworded for the
     reason (`no-windows-wheel`, `deferred`);
   - pack stale or absent: price, confirm, `install.py`; on success write config and
     restart; on failure write nothing.

### Error semantics

Every user-facing entry point returns a result object, as ADR-027 does. Exceptions are
for programming errors only. Every message names the next step.

## Tests

**Offline, in `tests/`:**

- `test_packs_manifest.py`: valid, unknown format, missing keys, wrong types, the asset name
  re-derivation.
- `test_packs_abi.py`: every field mismatch yields its own reason; equal build id with a
  different Python is still refused (defence in depth); `stale` versus `refused`.
- `test_packs_archive.py`: `../x`, `C:\x`, `\\server\share\x`, an absolute path, a symlink
  attribute, a name over budget, count or size different from the manifest, ratio over the
  cap, a duplicate name, case-insensitive duplicates (`A.py` and `a.py`).
- `test_packs_layout.py`: path budget at the worst-case `%LOCALAPPDATA%` length; build-dir
  prefix collision.
- `test_packs_state.py`: every state in ADR-028 §5 from fixtures; *waiting for add-on* never
  reads as `on`.
- `test_packs_policy.py`: disk-space math, deadline, GC and rollback, quarantine versus
  stale.
- `test_packs_catalog.py`: every wired `_FEATURE_DEPS` slug has a `packs.toml` decision;
  every `pack` extra exists in `pyproject.toml`; no `pack` row for an unwired slug. It fails
  on an empty catalogue (guard the guard).
- `test_packs_install.py`: the transaction with fakes. A failure injected at each step
  leaves no staging dir, no download and no config write. Single-flight lock, cancel.
- `test_packs_mount.py`: with a fake `PackRuntime`: appended (never prepended) order,
  handles retained, elevated means no mount, `YAZSES_NO_PACKS` means no mount, a missing
  `COMPLETE` means no mount, and an exception inside the plan never propagates out of
  `mount_at_startup`.
- `test_packs_egress.py`: the captured `Request` objects (URLs and exact headers). No
  `api.github.com`.
- `test_egress_inventory.py`: the `FETCH_VIA` scan (equality in both directions, fails on
  an empty scan) and the closure test (daemon, watcher and runtime hook cannot reach
  `packs.fetch` or `packs.install`).
- `test_build_packs.py`: collision checks on synthetic `--target` trees (module, DLL with
  equal or different bytes, distribution overlap), `.pth` handling, deterministic zip (two
  runs give equal bytes), path budget.
- `test_checksums_cover_packs.py`: `checksums.yml`'s glob and prove regex, and
  `verify-release-assets.py`, cover `.yazpack` and `-packs.json`. Derived from the asset
  names `build-packs.py` produces, not from a second hand-written list.
- `test_frozen_bundles_ship_the_gui.py` / `test_windows_build_architectures.py`: extended
  so the runtime hook is in the spec and `build-windows.ps1` still syncs only `--extra
  desktop`.

**On the Windows CI runner:** the frozen probe per pack and the base-manifest invariance
check, both in `build-windows.yml`, failing the job.

**Manual Windows checklist** (definition of done for the first release that carries packs):

1. Per-user `.exe`: enable Parakeet from the tray. Size shown → download → balloon →
   restart → dictation uses Parakeet. Then repeat from Settings and from
   `yazses features enable stt-parakeet`.
2. Cancel at about 50 %: no `.part`, no config change.
3. Unplug the network after confirming: an actionable message, and nothing changed.
4. Flip a byte in `downloads\*.part` during the download: mismatch, deleted, nothing
   installed.
5. Delete one DLL from the installed diarization pack: *damaged* at the next use, the
   tree is quarantined, Reinstall works.
6. One-click update (ADR-027) to the next version: the old pack is not loaded, one click
   re-downloads it, and the old tree is gone after the first good start. Force a failed
   update: the old version relaunches with its packs.
7. A user name with a space, an apostrophe and a non-ASCII letter: every path survives.
8. Microsoft Defender with real-time protection: note first-load time and any quarantine.
9. Smart App Control (evaluation and enforce): note whether pack DLLs are blocked. Record
   it in the ADR either way.
10. All-users install: packs install per user and load unelevated. Run `yazses` elevated:
    no pack is mounted and the features say why.
11. `YAZSES_NO_PACKS=1`: starts clean.
12. Uninstall (per-user): `packs\` removed; config and models follow the current policy.
13. winget-installed copy: identical behaviour to item 1.

## Live smoke evidence

Filled in by the Phase 0 spike and the Phase 1 checklist: run ids, Windows build numbers and
measured sizes.

- 2026-10-21, `packs-spike.yml` run 39631811305 (windows-latest, main c946e71e), pack
  `diarization` (sherpa-onnx 1.13.8): probes (a)–(d) PASS; the bound `onnxruntime.dll` was the
  base's `_internal\onnxruntime\capi\onnxruntime.dll`, onnxruntime 1.28.0, and an ONNX Runtime
  session ran. The bind row's FAIL was a probe path-comparison bug, fixed afterwards (see
  *Implementation status*). Pack and installer sizes on Windows: not yet recorded.

## Implementation status

### First Phase 0 spike on Windows (2026-10-21, run 39631811305 on main c946e71e)

`packs-spike.yml` ran the frozen app on `windows-latest` with the `diarization` pack (sherpa-onnx
1.13.8) mounted. Every risk the ADR called unmeasured **passed**: the probe ran inside the frozen
app (`sys.frozen`, `_MEIPASS`); a `sys.path` append made the pack importable; (a) the 7 stdlib
modules the pack references import; (b) `importlib.metadata` sees `sherpa_onnx` and
`sherpa-onnx-core` 1.13.8; (c) no pruned base submodule is referenced; (d) no DLL collision
remains (sherpa's `onnxruntime.dll` dropped, 1 bound to the base). The bind row reported FAIL
although its own detail shows the bind is right: the only `onnxruntime.dll` loaded was the base's
`_internal\onnxruntime\capi\onnxruntime.dll`, `onnxruntime` 1.28.0, and an ONNX Runtime session
ran. The hook had recorded the preload request as a relative path and the verdict compared it with
the loader's absolute one. Fixed (branch `fix/spike-bind-abspath`): the hook records the absolute
path, and `bind_verdict` accepts a relative expected path that ends the loaded one on a directory
boundary. Tests reproduce this run's exact paths. **Not yet re-run on Windows after the fix**, and
`diarization` is still withheld at release by the Q7 licence gate until the owner signs its two
licence entries.


### Build side, phases 0–1 (2026-10-21)

**Landed:** `scripts/build-packs.py` (pure logic plus a CLI), `packaging/packs/packs.toml`,
the pack steps in `scripts/build-windows.ps1`, the pack attestation and attachment in
`build-windows.yml`, `.yazpack` and `-packs.json` coverage in `checksums.yml`,
`verify-release-assets.py` and `verify-provenance.py`, an index-driven check in
`release-complete.yml`, and the Phase 0 spike (`.github/workflows/packs-spike.yml` with
`packaging/packs/spike/rthook_pack_spike.py`). Tests: `tests/test_build_packs.py` and
`tests/test_checksums_cover_packs.py`.

**Not landed (runtime side, a separate change):** everything under `src/yazses/packs/`,
`PackRuntime`, `packaging/windows/rthook_yazses_packs.py`, the `packs` CLI and
`[UninstallDelete]`. The build talks to that work only through the formats below and the
probe command.

**Not yet run:** neither the spike nor a release build has run on a hosted Windows runner.
The Live smoke evidence section is still empty. A Linux dry run on a developer machine,
using a fake bundle and Linux wheels, produced `parakeet` at 4.08 MB archived (7.27 MB
unpacked) and `diarization` at 15.0 MB (44.7 MB). These figures are not Windows sizes; the
spike replaces them. (`parakeet` is no longer a pack; see the answers below.)

**Where the spec was open, the build chose the following.** The runtime should read the
formats the same way.

1. **Counts.** `files` and `unpacked_bytes`, in `pack.json` and in the index, count *every*
   member of the ZIP, `pack.json` and `RECORD.json` included. `pack.json` is computed to a
   fixed point, because its own size depends on those numbers. An extractor can therefore
   compare the entry count and the total uncompressed size against them directly.
2. **`RECORD.json`** has the form `{"format": 1, "files": [{"path", "size", "sha256"}]}`.
   It lists every member except `RECORD.json` and `pack.json`. Paths are POSIX and relative
   to the pack root.
3. **Archive shape.** The ZIP holds regular files only (Unix mode `0o100644`), with no
   directory entries. Entries are sorted, carry the timestamp 1980-01-01 and use DEFLATE
   level 9. A member whose DEFLATE ratio would exceed **100:1** is STORED, so a per-member
   ratio cap of 100 or more never refuses a genuine pack.
4. **`path_entries`** is a new `pack.json` key, a list of pack-root-relative paths taken
   from `.pth` lines that only add a path. The `.pth` file itself is removed. The loader
   appends these after `site/`. A `.pth` that runs `import` code fails the build. Both
   phase 1 packs have an empty list.
5. **`native_dirs`** lists pack-root-relative directories that still hold a `.dll` after
   any DLL byte-identical to the base's, or bound to the base's (item 16), has been
   dropped.
6. **The OS word in asset names.** `win-*` becomes `windows` and `macosx-*` becomes `macos`.
   The `platform` field holds the build venv's `sysconfig.get_platform()` (`win-amd64`).
   `python` is `{cache_tag: sys.implementation.cache_tag, version:
   platform.python_version(), abi: "cp3XY"}`.
7. **Base manifest.** `base-manifest.json` is canonical JSON (sorted keys, no whitespace):
   `{"format": 1, "files": [{"path", "size", "sha256"}]}`. It covers every file in
   `dist/YazSes/` except `_internal/yazses-packs-index.json`. `base_build_id` is
   `sha256:` followed by the hex digest of those bytes. The manifest is kept in the build's
   work directory and is not a release asset.
8. **Index bytes.** The embedded index and the release asset are byte-identical: UTF-8,
   sorted keys, 2-space indent, trailing newline. The index lists only packs that passed
   every check *and* the frozen probe. When none passed, no index is embedded or published.
9. **The same DLL in two packs.** When two packs carry byte-identical copies of a DLL, both
   packs keep it, because either pack may be installed alone. The "dropped" rule in ADR-028
   §1 applies only to copies identical to the base's. Different bytes still fail the build.
10. **The probe command the build calls:** `yazses-cli.exe --cli packs probe <name>
    --staged <dir>`. `<dir>` is the *extracted pack root*, the folder holding `pack.json`
    and `site/`. During the probe, `LOCALAPPDATA`, `APPDATA`, `USERPROFILE`, `HOME` and
    `XDG_*` point at a sandbox, a provisional index of every built pack is embedded, and
    the timeout is 120 s. Exit 0 publishes the pack. **Until the runtime side ships this
    command, every pack is withheld**, which keeps the rule never to publish an unprobed
    pack.
11. **Withhold, not fail (acceptance 3).** A pack that fails a check or its probe is
    withheld: no index entry, no asset, a warning annotation and a row in the job summary.
    The job still ships the base installer. The job fails only if the base bundle changed
    during pack production (the step 4 invariance guard). `build-packs.py build --strict`
    is available for a release that should fail instead.
12. **`packs.toml` schema.** `format = 1` plus one `[extras.<name>]` table per pyproject
    extra. Each table has a `decision` (`pack`, `bundled`, `no-windows-wheel`, `unwired`
    or `deferred`), and a `reason` for anything that is not a pack. A pack also has
    `features`, `entry_modules` and optionally `approved_large` / `approved_by` and
    `bind_to_base` / `bind_reason` (item 16). A non-pack entry carrying `features`,
    `entry_modules` or `bind_to_base` fails validation. The large threshold is 500 MiB.
    `shared_with` is not used yet.
13. **Provenance.** One `actions/attest-build-provenance` step attests the packs and the
    index through a multi-line `subject-path: |`. `verify-provenance.py` now reads such
    blocks, so `.yazpack` and `.json` became attested suffixes. Only `-packs.json` assets
    are in `SHA256SUMS.txt`, so no other JSON file is affected.
14. **Licences.** Each distribution's licence files go to `LICENSES/<dist>/`. The Q7
    licence gate (owner answer, 2026-10-21) is `scripts/pack_licences.py`, called once
    per pack from `build_one` after the wheels are installed. It classes each
    distribution permissive / LGPL (LGPL, MPL-2.0) / GPL (GPL, AGPL) / UNKNOWN from
    `License-Expression` (SPDX; `OR` → most permissive, `AND` → strictest, `WITH` only a
    known exception, which can relax GPL to LGPL), otherwise from `License` plus the
    `License ::` classifiers, the stricter of the two. A pack is withheld on UNKNOWN, on a
    distribution with no licence file in its dist-info (unless a signed
    `[[licence_text]]` supplies one, below), on LGPL/GPL without an upstream URL
    in METADATA, and on GPL without an `[[approval]]` in
    `packaging/packs/licence-approvals.toml` naming that pack, distribution, exact version
    and licence. A `[[clarification]]` records a person's reading of a free-text licence
    as an SPDX expression for one exact version. An entry that no longer matches is
    reported as stale and approves nothing. A copyleft pack carries `LICENSES/SOURCE.md`
    (`LICENSES/`, not the root, because the runtime's `archive.TOP_LEVEL` allows only
    five root names). The result is `licence_gate` in the build report and `licences`
    (`name`, `version`, `licence`, `class` per distribution) in `pack.json`, which the
    runtime ignores. Under `--skip-probe` (the spike) a failure is recorded, not
    withheld, as for DLL conflicts.
    - **Two differences from the ADR text.** Approvals live in
      `licence-approvals.toml`, not as a `packs.toml` field, so the per-version record
      and its staleness check have their own schema. The gate is the standard library
      only, not `pip-licenses`, and has no ScanCode step, so it cannot see a GPL binary
      vendored in a wheel that declares MIT.
    - **Verified:** `tests/test_pack_licences.py`, synthetic METADATA only, with each rule
      shown to fail its tests when removed. **Not verified:** a run on real Windows
      wheels. Read offline from the Linux 1.13.8 wheels in a local uv cache:
      `sherpa-onnx-core` has no licence file and `sherpa-onnx` declares free text
      (`Apache licensed, as found in the LICENSE file`), so **the first real build
      withholds `diarization`** on two counts. `parakeet`'s
      `onnx-asr` 0.12.0 passes (`License-Expression: MIT`). `espeakng-loader` was not in
      the cache, so the ADR's finding for it is not re-checked here.
    - **A reviewed licence text for a distribution that ships none
      (`[[licence_text]]`, 2026-10-21).** Fields: `pack`, `dist`, `version`, `spdx`,
      `source_url`, `file` (relative to the approvals file, under `licence-texts/`, no
      `..`), `sha256` (of the file's bytes, lower-case hex), `reviewed_by`, `date`. The
      build copies the file to `LICENSES/<dist>/<file name>` only when pack, dist and
      exact version match, `spdx` equals the declared licence (legacy spellings such as
      `Apache 2.0` mapped; a clarification's licence counts as declared), the file exists
      inside `licence-texts/` (a symlink out reads as missing) and hashes to `sha256`,
      and `reviewed_by` is not empty. Otherwise the pack keeps its "no licence file"
      problem, with the reason appended, and the entry is reported in `stale_approvals`:
      another version, a wrong hash, a missing file, another licence. An entry for a
      distribution that ships its own licence file is reported as **redundant** and never
      overrides that file. `build_one` refuses a vendored member that would overwrite an
      existing one. The build report lists the copied members as `vendored_licences` and
      the entry under the distribution's `vendored_licence`. `.gitattributes` marks
      `packaging/packs/licence-texts/**` `-text`, because Git for Windows would otherwise
      check the text out with CRLF and change its hash.
    - **Prepared but unsigned.** A `[[clarification]]` or `[[licence_text]]` whose
      `reviewed_by` is empty (`date` may be empty too) parses cleanly, is listed in the
      build report's `awaiting_review`, and honours nothing. An `[[approval]]` cannot be
      unsigned: an empty `approved_by` is an error. Two such entries are committed for
      `diarization`, both with `reviewed_by = ""`: a clarification of `sherpa-onnx`
      1.13.8 as `Apache-2.0`, and a licence text for `sherpa-onnx-core` 1.13.8 at
      `packaging/packs/licence-texts/sherpa-onnx-core/1.13.8/LICENSE`. That text is the
      repository's `LICENSE` at tag `v1.13.8` (a lightweight tag on commit
      `11afbd009a7f8c08f4bcf2fc1b265d0df4670fbf`, whose `CMakeLists.txt` sets
      `SHERPA_ONNX_VERSION "1.13.8"`), fetched 2026-10-21; it is byte-identical (11,358
      bytes, SHA-256 `cfc7749b…3d30`) to `https://www.apache.org/licenses/LICENSE-2.0.txt`
      and to the `licenses/LICENSE` in the `sherpa-onnx` 1.13.8 Linux wheel.
      `tests/test_pack_licences.py` holds both entries inert
      (`DIARIZATION_LICENCES_SIGNED = False`) and rehearses on a copy that filling in
      the two fields is all that is left.
    - **What the owner does to release `diarization` (licence side only).** (1) Read
      `packaging/packs/licence-texts/sherpa-onnx-core/1.13.8/LICENSE` and compare it with
      its `source_url`; read the `LICENSE` in the `sherpa-onnx` 1.13.8 wheel's dist-info.
      (2) In `packaging/packs/licence-approvals.toml`, set `reviewed_by` to your full name
      and `date` to the day, in both diarization entries. (3) In
      `tests/test_pack_licences.py`, set `DIARIZATION_LICENCES_SIGNED = True` in the same
      commit. (4) Run `uv run python -m pytest tests/test_pack_licences.py`. A coding
      agent does none of (1)–(3). The licence gate is not the only gate: the pack still
      needs the bind probe (item 16) and a real Windows build, and the Windows wheels'
      METADATA has not been read, so the first real build may still report something the
      Linux wheels did not show.
15. **No `stdlib/` supplement yet.** The spike measures the stdlib gaps first (Phase 0 item 2).
16. **`bind_to_base`: a reviewed DLL exception (ADR-028 finding on sherpa-onnx-core).**
    `packs.toml` may list bare DLL basenames under `bind_to_base` for a pack, with a
    `bind_reason`. When the base ships a DLL of a listed basename, *every* copy of it in
    the pack is dropped although the bytes differ (sherpa-onnx-core 1.13.8 ships an
    unsigned onnxruntime 1.28.2 in `sherpa_onnx/lib/` and again under
    `.data/data/Scripts/`; the base has Microsoft's signed 1.28.0). The build report
    records the dropped paths (`dll_bound_to_base`) and any listed name that collided
    with nothing (`dll_bind_unused`, a warning), and `pack.json` gains
    `bind_to_base`: the sorted, lower-case basenames the pack relies on the base for,
    always present and usually empty. The runtime must load the base's copy of each
    before it imports the pack's entry modules. Every other differing collision still
    withholds the pack; the byte-identical drop (item 5) is unchanged.
17. **The base is the `bundled` extras.** `build-packs.py` measures the base from the
    extras `packs.toml` decides `bundled` (today `desktop`, `overlay`, `parakeet`,
    `chinese`), not from a hard-coded `desktop`, and subtracts their closure from every
    pack. If the build venv lacks a bundled extra's distribution, every pack is withheld
    and the base still ships. `build-packs.py validate` (and `tests/test_build_packs.py`)
    holds `scripts/build-windows.ps1`'s `uv sync` extras, and the spike workflow's, to the
    `bundled` set in both directions. A bundled extra is never built as a pack.

**Owner answers (ADR-028, "Owner questions: answered 2026-10-21") and their build-side
effect.**

- **Q1, bundle the tiny pure-Python extras: yes.** `parakeet` (onnx-asr, MIT, ~4 MB
  wheel) and `chinese` (opencc-python-reimplemented, Apache-2.0, ~0.5 MB) are `bundled`.
  `scripts/build-windows.ps1` runs `uv sync --no-dev --extra desktop --extra parakeet
  --extra chinese`, and `packaging/windows/yazses.spec` adds `copy_metadata("onnx-asr")`,
  `collect_data_files("onnx_asr")` and its submodules, because onnx-asr reads its own
  version through `importlib.metadata` at import and its preprocessor `.onnx` files
  through `importlib.resources` (opencc is covered by pyinstaller-hooks-contrib's
  `hook-opencc`). Both files are therefore part of the base manifest and its
  `base_build_id`. Phase 1 builds one pack, `diarization`. The PyPI base is unchanged.
- **Q2, torch packs: no.** `voiceprint` stays `deferred`, with that reason.
- **Q7, licence gate: yes, three rules** (item 14). `tts` and `prosody` stay `deferred`
  with the GPL reason.
- **Finding M1, sherpa's onnxruntime.dll:** `diarization` binds `onnxruntime.dll` to the
  base (item 16). `packs-spike.yml` probe (d) now proves or refutes the binding: with the
  base's copy preloaded by full path, `import sherpa_onnx` must leave exactly one
  `onnxruntime.dll` loaded, from the base; `onnxruntime.__version__` must equal the
  version the build venv froze (from the build report, 1.28.0 today); and both an
  onnxruntime session and sherpa-onnx's own silero VAD session must build and run on a
  pinned `silero_vad.onnx` (SHA-256 checked in the workflow). It prints one `PASS:` or
  `FAIL:` line carrying the loaded path and the version. If it fails, `diarization` takes
  ADR-028 §1's out-of-process route.
- Q3–Q6 and Q8 are runtime, installer or account matters; the build side does not change
  for them.

**Not verified.** None of the above has run on Windows: not the frozen bundle with
onnx-asr and opencc inside it, not its size, and not the bind probe. The +~4.5 MB
installer figure is ADR-028's wheel measurement, not a built installer.

**Spike limits.** The spike's runtime hook imports `json`, `pkgutil`, `ctypes` and
`traceback`, so PyInstaller collects those four into the spike base, and risk (a) cannot
report them as missing. The spike builds with `--skip-probe`, which embeds and publishes
nothing. The shipped spec never contains the spike hook, and a test enforces that.

## Implementation status (runtime side)

### Runtime side, phase 1 (2026-10-21, branch `feat/addon-packs-runtime`)

**Landed.** The pure core `packs/manifest.py`, `abi.py`, `layout.py`, `archive.py`,
`catalog.py`, `state.py` and `policy.py`; the I/O halves `packs/context.py` (reads only),
`fetch.py` (the one egress module), `install.py` (the transaction), `mount.py` and
`probe.py`, plus `packs/manage.py` behind the CLI. `PackRuntime` in `platform/base.py`,
`platform/windows/packs.py`, `supported() -> False` backends for Linux/BSD and macOS, and
`platform.factory.get_pack_runtime()` / `get_pack_paths()`, which build no `Platform` so the
hook stays light. `packaging/windows/rthook_yazses_packs.py`, registered in
`packaging/windows/yazses.spec` (`runtime_hooks`; the build branch left that line
untouched). `PackageProfile.can_add_packs` (true for `windows-exe` only) and
`policy.PACK_INSTALL_METHODS = {"windows-installer"}`. CLI: `features enable --yes`, and
`yazses packs [list] / install / verify / remove / clean / path / probe`. ADR-019 row, the
fourth scan `FETCH_VIA`, the closure test, the computed Class A count and the captured
`Request` test. `ReleaseAsset` is an additive alias in `installer_update.py`; nothing else
there changed.

**Formats: aligned with the build side's items 1–15.** Checked on 2026-10-21 by building a
pack with `scripts/build-packs.py`'s own `record_json`, `pack_json`, `pack_fields`,
`write_deterministic_zip`, `build_index` and `index_bytes` (from `feat/addon-packs-build`)
and feeding it to `parse_index`, `extract_archive` and `abi.match`: accepted, `ok`.
`catalog.catalogue_problems` reports nothing for the build branch's `packs.toml`.

- Counts include `pack.json` and `RECORD.json` (item 1); `RECORD.json` lists the rest (2).
- The per-member ratio cap is 200:1, above the build's 100:1 STORE threshold (3).
- `path_entries` is optional; mount and probe append `site/`, then `path_entries`, then
  `stdlib/` (4). `native_dirs` must sit under `site/` or `stdlib/` (5).
- The probe is `--cli packs probe <name> --staged <pack root>`; exit codes: 0 ok, 3
  refused tree, 4 stdlib gap, 5 missing metadata, 6 pruned base submodule, 7 native load
  failure (the `onnxruntime.dll` collision case), 8 other import error, 9 anything else.
  The last stdout line is `YAZSES-PROBE <kind> <module>: <sentence>` (10).
- **The probe does not refuse an elevated process**, unlike the mount and the install. It
  loads only the directory it is given; the install starts it from the user's unelevated
  process, and the Windows CI runner's account is an administrator.

**Two limits stricter than the build's.**

- Pack names: at most **16** characters (build: 40), so the quarantine path fits
  `MAX_PATH` with a 66-character `data_dir` (`layout.budget_problems`). A longer name makes
  `parse_index` refuse the **whole** index. Both phase 1 names fit; the build should cap at
  16 as well.
- `data_dir` budget: 66 characters (`C:\Users\<20>.<15-char domain>\AppData\Local\yazses`).

**Conservative choices where an owner question is open.** Q3: the re-download after an
update waits for the user (`yazses packs install`, or `features enable` again); nothing
fetches on its own. Q4: `yazses packs remove --all` exists; no per-user cleanup at login.
Q5: no `--from <file>`; the failure messages name the asset and its URL, not a command that
does not exist. Q6: the MSIX profile has `can_add_packs = False`. Chocolatey and Scoop are
outside `PACK_INSTALL_METHODS`, so they keep the "install from PyPI" answer. Choosing
differently means changing one constant or one profile field.

**Not landed.**

- `deps.fixed_payload_reason` is **unchanged**. Returning `None` there for a pack-capable
  profile, as the module list says, would let the Settings, hands-free and language paths,
  which call `install_blocked_reason` and then pip, try to run pip inside the frozen app.
  The pack branch is in `cli.py` before that check, so only `features enable` routes to
  packs. The tray and Settings surfaces, and rewording the message for `no-windows-wheel` /
  `deferred` (the embedded index carries no reasons), are follow-ups.
- The tray's `started-ok` marker (`state.mark_started_ok` exists, nothing calls it). Until
  it does, `clean` and the post-install GC always keep the newest previous build.
  *Landed with Q3 below (`packs.refetch.mark_first_start`).*
- A full `RECORD.json` check triggered by an `ImportError` at a lazy import site. Today
  `yazses packs verify` runs it and quarantines a damaged tree.
- `[UninstallDelete]` in `installer.iss`, `docs/addons.md`, `docs/install-cost.md` rows.

**Untested without Windows.** `os.add_dll_directory` handles and DLL resolution; the token
elevation probe; `sys._MEIPASS` and the `yazses-cli.exe` sibling path; that PyInstaller
collects `yazses.packs.*` through the hook's import; `CREATE_NO_WINDOW` for the probe child;
`os.replace` of a tree across `%LOCALAPPDATA%`; Defender or Smart App Control; and every
item in the manual checklist above.

### Uninstall and offline install, owner questions 4 and 5 (2026-10-21, branch `feat/packs-uninstall-from`)

This supersedes the Q4 and Q5 sentences under *Conservative choices* above, and the
`[UninstallDelete]` part of *Not landed*.

**Q4, landed.**

- `installer.iss` has `[UninstallDelete] Type: filesandordirs; Name:
  "{localappdata}\yazses\packs"; Check: IsPerUserInstall`, where `IsPerUserInstall` is
  `not IsAdminInstallMode`. Only the packs folder: config, logs and models beside it keep
  their policy.
- **Per-user installs only.** In an all-users uninstall `{localappdata}` is the elevated
  administrator's profile, so that uninstall deletes nothing there. ADR-028's answer says
  "the uninstaller removes the elevating user's `packs\`"; this deliberately does less,
  because the administrator who elevates is usually not a user who installed packs, and
  the one who is gets the doctor row instead. Changing it means dropping the `Check`.
- The `Check` is right whichever moment Inno evaluates it (when it writes the uninstall
  log or when it uninstalls), because one registration has one install mode. Inno's
  documentation pages checked on 2026-10-21 do not say which moment it is.
- **Never on an upgrade.** `[UninstallDelete]` runs only from the uninstaller, and an
  in-place upgrade (ADR-027's one-click update included) never starts it.
  `tests/test_packaging_windows.py` fails if `[InstallDelete]`, `[Run]`, `[Files]` or
  `[Registry]` names the packs folder, or if `[Code]` deletes a tree, names the folder or
  starts the uninstaller, and if any `[UninstallDelete]` entry naming a per-user folder
  lacks the `Check`.
- `yazses doctor` has an **Add-ons** row (`doctor.packs_row`, facts from
  `packs.manage.disk_use`). WARN when the pack folder holds bytes this copy never loads
  (another build's packs, or `staging`/`downloads`/`quarantine` leftovers). OK, as a
  statement, when the install is all-users (`UpdateLauncher.install_scope() ==
  "machine"`) and this user has packs. Both name `yazses packs remove --all` and what it
  frees. No row without a pack folder, and nothing is called unused when the process
  cannot tell its own build (a source checkout sharing the data folder).
- `docs/windows-install.md` *Uninstall* says the same.

**Q5, landed.** `yazses packs install --from <file>` (`packs.manage.install_from_file`,
additive; the name argument becomes optional when `--from` is given).

- The file name must equal one of this build's asset names exactly
  (`manage.entry_for_file`); a wrong name is refused before the file is read, naming the
  accepted files, and the YazSes version when the name says another one.
- `manage.file_fetcher` stands in for the network fetch inside the unchanged
  `install_pack` transaction. It refuses a size mismatch from `stat`, copies the file into
  `downloads\<asset>.part`, and hashes **the copy** against the embedded index entry, so a
  file changed after a check cannot be the one extracted. On a mismatch it reads only
  `pack.json` to say "made for a different build" when that is the reason. The user's own
  file is never deleted.
- After the hash: member validation, `RECORD.json`, the ABI match, the child-process probe
  and the atomic place, exactly as for a download.
- No `SHA256SUMS.txt` and no request of any kind.
  `tests/test_packs_egress.py::test_an_offline_install_from_a_file_makes_no_request`
  runs a whole `--from` install through the captured opener and asserts zero requests;
  `tests/test_packs_install_from_file.py` replaces every network primitive with a failing
  one.
- `fetch.manual_steps`, which every failed download prints, now adds the `--from` route
  after the asset name and URL.

**Not verified.** `installer.iss` was not compiled (no ISCC on Linux); the uninstall on a
real per-user and all-users install is manual checklist item 12, still open, plus the
all-users case. `install_scope()` on a real all-users install is unit-tested only.

### Runtime side: binding to the base's ONNX Runtime (ADR-028 M1, 2026-10-21, branch `feat/packs-runtime-ort`)

**Why.** `sherpa-onnx-core` 1.13.8's Windows wheel carries its own `onnxruntime.dll` (an
unsigned 1.28.2 build) while the base carries Microsoft's signed 1.28.0 (measured fact M1 in
ADR-028's answered questions). The build drops the pack's copy; the runtime must make
`sherpa_onnx` use the base's copy, deterministically, and refuse otherwise.

**The contract with the build side** (`pack.json`, both optional, absent = empty):

- `bind_to_base`: a list of bare DLL file names (no directory, no drive; compared
  case-insensitively; duplicates refused) the build dropped because the pack must use the
  base's own file of that name. Agreed with the build side, which writes the names in lower
  case (today `["onnxruntime.dll"]`) and ships no copy of a listed DLL.
- `bind_min_versions`: an object mapping some of those names to the lowest version of the
  base's copy the pack accepts, e.g. `{"onnxruntime.dll": "1.28"}`. A key not listed in
  `bind_to_base` refuses the manifest. **This field is the runtime side's proposal; the build
  side does not write it yet.** Without it, any version of the base's copy binds and the
  version is only reported. That is safe today because a pack loads only into the one base
  build it names (`base_build_id`), and the build's frozen probe already checks that the
  base's copy is the version the base froze.

**Landed.**

- `packs/bind.py`: the pure decisions and the binding. The base's copy is found by walking
  the frozen app's `_internal` folder (`sys._MEIPASS`) and nowhere else. One copy is taken.
  Of several, the only one inside a package folder named after the DLL
  (`onnxruntime/capi/onnxruntime.dll`) is taken: it is the file the base's own
  `import onnxruntime` loads, and the build's spike (`spike_bind_request`) preloads the same
  file. Any other set of copies is refused, not ranked. It is loaded by absolute path
  (`ctypes.WinDLL`, which passes `LOAD_LIBRARY_SEARCH_DEFAULT_DIRS |
  LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR` for a path), so the loader never searches for the name,
  and its module name is then in the loaded-module list that answers sherpa's import
  ([DLL search order](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order)).
  The version comes from ONNX Runtime's own C entry point,
  `OrtGetApiBase()->GetVersionString()`. Afterwards every loaded module of that name
  (`K32EnumProcessModules`, as the spike's check (d) does) must be the base's file.
- **Lazy.** `mount.apply` puts a `FirstUseBinder` on `sys.meta_path` for each mounted pack
  that lists `bind_to_base`. Start-up loads nothing and walks nothing (one `scandir` of the
  pack's `site/` to learn its top-level names). The first import of one of the pack's
  modules binds, before the pack's own code runs; on success the finder removes itself.
  A binding pack in whose `site/` no module name is found is not mounted (fail closed).
  The start-up path imports `packs/bind.py` only when such a pack is mounted.
- **Refusal** has a named reason: the base does not contain the DLL; it contains several
  copies and not exactly one inside a package folder of that name; it does not load; its version is below `bind_min_versions`; its version cannot be
  read while a minimum is stated; another file of that name is already loaded; the loaded
  list cannot be read. At first use it is an `ImportError` naming the reason for every
  import of that pack, and an entry in `mount.LAST.failed`. The pack is not quarantined:
  the fault is the base's, not the pack's.
- **Probe.** `yazses packs probe` binds before importing `entry_modules` and re-checks the
  loaded modules after. A refusal or a second `onnxruntime.dll` appearing during the import
  is `native-load` (exit 7). Success ends the `YAZSES-PROBE ok` line with
  `bound onnxruntime.dll -> <path> (version <v>), YazSes's own copy`, so the install
  transaction and the release job record which ONNX Runtime the pack runs on. No exit code
  was added.
- **Verify.** `yazses packs verify` prints one line per bound DLL (path and version, or the
  refusal) and exits 1 on a refusal without setting the pack aside.
- `PackRuntime` gained `base_native_candidates`, `load_base_native` and
  `loaded_native_paths`; the Linux/BSD and macOS backends answer "none" / "cannot tell", so a
  binding pack is refused there.
- **Out-of-process fallback (ADR-028 §1): not built.** `bind.bind_mode()` always returns
  `"in-process"`; `bind.OutOfProcessHost` is the typed seam, with a TODO naming what would
  trigger it: the spike's check (d) showing `sherpa_onnx` failing to import against the
  base's 1.28.0, or any `onnxruntime.dll` loaded from a path other than the base's. Until
  then, a pack whose mode is not in-process is skipped at mount and refused by the probe.

**Tests.** `tests/test_packs_bind.py` (64 cases, through a fake runtime): field parsing,
every refusal reason, the import ordering through the real import system, nothing loaded
or walked at mount, the probe and `verify` output, the Windows folder walk and the
`OrtGetApiBase` read through a ctypes stand-in. Each guard was mutated out and the suite
went red.

**Not verified (needs a Windows run).** That `sherpa_onnx`'s extension actually resolves to
the base's preloaded `onnxruntime.dll` and works against 1.28.0; `ctypes.WinDLL` on the real
`_internal\onnxruntime\capi\onnxruntime.dll` path; `K32EnumProcessModules` paths matching the
walked path; `OrtGetApiBase` on Microsoft's build; how many `onnxruntime.dll` files the
frozen base contains, and where. The spike's check (d) and the release job's frozen probe
answer these.

### Q3: add-ons across an update (2026-10-21, branch `feat/packs-update-consent`)

**Landed**, as the owner answered Q3 (ADR-028, *Owner questions: answered 2026-10-21*):

- **Consent at the update question.** `installer_update.confirmation_prompt(..., addons=)`
  appends one sentence from `installer_update.addons_note`, e.g. *"Your add-on
  (Diarization, 15 MB) will be downloaded again for the new version. If that download
  fails, Settings offers Install now."* The names and sizes come from the **running (old)**
  build's embedded index and the trees intact under it (`packs.refetch.addons_for_update`).
  Dialog text only: `Offer.reason`, which rides a tray balloon, is unchanged, and so are
  the `all_users` keyword and `ALL_USERS_NOTE`. The Windows tray and the Settings window
  pass it; `yazses update` in a terminal does not, and so records no consent.
- **The consent record.** Once the hand-off has started (`HandoffResult.ok`), the surface
  that asked writes `packs/update-consent.json` (`format`, old `build_id`, `from`, `to`,
  `packs`, `at`) through `tray.updates.record_update_consent`.
- **First start of the new version.** The tray's entry point (`tray.app.run`) starts
  `start_addon_refetch`, a worker thread that waits 5 s (the daemon and the icon come
  first) and calls `tray.updates.refetch_after_update`. Without a consent file it returns
  after one `stat`. Otherwise `packs.refetch.run_refetch`
  **erases the consent first** (if it cannot, nothing is downloaded), then
  `plan_refetch` (pure) picks the packs that are consented, recorded in `state.json` for
  the old build, listed in the **new** build's own index and not already installed. A
  stale consent (over 7 days), an incapable or elevated process, or an unchanged build id
  (a failed update relaunched the old version) downloads nothing. Each pack goes through
  `packs.manage.install` (the existing verified transaction: no second downloader, no new
  ADR-019 row) with a freshly read `state.json`, then `packs.manage.verify`.
- **Where the downloader is bound.** `tray.updates` is in the daemon's *static* import
  closure (`handsfree.probe` → `platform.factory` → the platform trays), so neither it nor
  `packs.refetch` imports `packs.manage`: `run_refetch` takes `install` and `verify` with no
  default, and only `tray.app` (the tray process's entry point, outside the daemon's
  closure) binds them. The first version of this branch bound them inside `packs.refetch`,
  and `test_pack_downloads_are_user_initiated_only` failed on it, which is the guard doing
  its job. ADR-028 §4's "never at startup" still holds for the daemon, the watcher and the
  hook; this one start-time download runs in the tray process and only on the consent
  given in the update question.
- **Old build retired only after everything verified.** On full success the new build is
  marked `started_ok` and `policy.gc_plan(..., started_ok=True)` deletes the other builds'
  trees. On a partial or failed run nothing of the old build is touched, the features read
  *waiting for add-on*, and the existing **Install now** (Settings) or
  `yazses packs install` is the one-click retry. The result is shown once, in a balloon
  under 255 characters (`refetch.describe`).
- **The `started_ok` marker is now written.** Nothing called `state.mark_started_ok`
  before, so every previous build's packs stayed on disk until `yazses packs remove
  --all`. The tray job now runs on every start of a frozen build that has a
  `state.json` (one `stat` otherwise), and a start with **nothing to download** -- no
  consent, a consent with nothing left to fetch, or a failed update that relaunched the
  old build -- is this build's first good start: `refetch.mark_first_start` marks it
  and retires the other builds through the same `retire_old_builds` (`mark_started_ok` +
  `policy.gc_plan(started_ok=True)` + `state.remove_build`). It does nothing in an
  incapable or elevated process, writes no `state.json` for someone who never had an
  add-on, and runs once per build. A start that downloaded and failed retires nothing;
  the next start, with nothing left to download, does. That old tree is not loadable by
  the new build, so only the rollback reason kept it, and a second start of the new
  build settles that.

**Tests.** `tests/test_packs_refetch.py` (prompt with and without packs, `all_users`
unchanged; consent parse; the plan; consented / not consented / failed / partial / verify
failure / raised install; at most once; an un-erasable consent; the old build kept until
every tree verified; the tray question and consent wiring; the entry point binding the
downloader and notifying once) and three cases in
`tests/test_settingsui_maintenance_panel.py`. Each guard was shown red by a mutation that
removes it.

**Not verified.** No run on Windows with a published pack: the balloon text on a real
tray, the download after a real relaunch, and the timing of the tray's startup thread
against a daemon that has not finished starting are untested. A balloon raised before
pystray has shown the icon is dropped (the 5 s delay makes that unlikely, not
impossible). A restart is still needed to load the new
packs into the daemon that started before they arrived; the message says so.
