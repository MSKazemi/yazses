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

- `packs.toml` adds whichever of `gaze`, `tts`, `prosody`, `denoise`, `moonshine` and
  `chinese` pass, subject to the owner's answer on bundling small extras and the licence
  gate (ADR-028, open questions 1 and 7).
- `PACK_INSTALL_METHODS` adds `choco` and `scoop` once their checklist items pass.
- `yazses packs install --from <file>` (if the owner accepts open question 5): the file
  name must equal the expected asset name and its SHA-256 must equal the embedded index
  entry. No network.
- `cancel` and `ReleaseAsset` from the ADR-028 §4a follow-up refactor, if it has landed.
  Otherwise Phase 1's coarse cancel (raising from `progress`) is documented as a known
  limit.

**Acceptance:**

- Each new pack meets Phase 1 criteria 1–7.
- `gaze`'s pack loads OpenCV and MediaPipe from `native_dirs`, and the camera matrix,
  `doctor` and `features enable` agree on every row (EYE-PERM-001).

### Phase 3: large packs and other channels (each needs an owner decision)

- `voiceprint` (torch), if open question 2 says yes.
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

To be filled in by the Phase 0 spike and the Phase 1 checklist: run ids, Windows build
numbers and measured sizes.

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
- A full `RECORD.json` check triggered by an `ImportError` at a lazy import site. Today
  `yazses packs verify` runs it and quarantines a damaged tree.
- `[UninstallDelete]` in `installer.iss`, `docs/addons.md`, `docs/install-cost.md` rows.

**Untested without Windows.** `os.add_dll_directory` handles and DLL resolution; the token
elevation probe; `sys._MEIPASS` and the `yazses-cli.exe` sibling path; that PyInstaller
collects `yazses.packs.*` through the hook's import; `CREATE_NO_WINDOW` for the probe child;
`os.replace` of a tree across `%LOCALAPPDATA%`; Defender or Smart App Control; and every
item in the manual checklist above.
