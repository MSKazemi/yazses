# YazSes packaging

Per-channel packaging artefacts. **Read this when you want to publish to a
new distribution channel** — the build scripts in `../scripts/` use the
files here as inputs.

## ⚠ Channel status — read this first (audited 2026-08-11; live re-check of every channel 2026-08-13)

**A manifest living in this directory installs nobody.** It has to be published to the
registry.

Every channel below was re-checked against its own API on **2026-08-13, after v2.18.2**.
Do not trust a row without doing that — this pass found the Snap row overclaiming, and
three rows describing a world two releases old. What held up: PyPI serves **2.18.2**, and
the APT repo serves **2.18.2**, signed, `InRelease` 200.

| Channel | Published? | In-repo artefact | State |
|---|---|---|---|
| PyPI | ✅ live | — | `pipx install yazses` |
| Snap Store | ⚠ amd64 only on stable | `../snap/` | amd64 stable **2.18.2**; arm64 is **edge-only and three releases behind (2.17.0)** — see below |
| APT repo | ✅ live | `../scripts/update-apt-repo.sh` | signed |
| GitHub Releases | ✅ live | — | `.dmg`, `.exe`, `.deb` |
| **Homebrew** | ✅ live | `homebrew/yazses.rb` | tap at [MSKazemi/homebrew-yazses](https://github.com/MSKazemi/homebrew-yazses), synced to **2.18.2 (real sha)**, **arm64 only** — see the macOS section ([#6](https://github.com/MSKazemi/yazses/issues/6)) |
| **winget** | ❌ **404** | `winget/…/2.18.2/` | manifests **current (2.18.2, real sha)**; `microsoft/winget-pkgs` still has no `manifests/m/MSKazemi/YazSes` (404, re-checked) ([#78](https://github.com/MSKazemi/yazses/issues/78)) |
| **AUR** | ❌ **404 — but the recipe is READY** | `arch/PKGBUILD` | ⭐ This row was itself stale until 2026-08-14: the PKGBUILD is **not** at `0.4.0`/`SKIP`, it is at **`pkgver=2.18.2` with a real `sha256sums`** matching `.SRCINFO`, and `arch/README.md` records a 2026-08-13 clean-container verification (`namcap` clean, full `makepkg --nodeps` build, checksum match). **Nothing remains but `git push` to `ssh://aur@aur.archlinux.org/yazses.git`**, which needs the maintainer's AUR SSH key. Highest value-per-minute item in `packaging/` ([#67](https://github.com/MSKazemi/yazses/issues/67)) |
| **Flathub** | ❌ not published | `../packaging/flatpak/` | manifest **builds green**; the submission ([flathub#9765](https://github.com/flathub/flathub/pull/9765)) was auto-closed for an incomplete checklist and a maintainer declined to reopen. The one unchecked item is **a video of the app running from the Flatpak** — that is the whole remaining blocker ([#45](https://github.com/MSKazemi/yazses/issues/45)) |
| **Nix** | ❌ 0 hits | `../flake.nix` | authored; **every nixpkgs attribute verified to exist**, but ⚠ **never evaluated** (no Nix here) ([#68](https://github.com/MSKazemi/yazses/issues/68)) |
| **Docker/GHCR** | ⚠ **one tag only, no `latest`** | `docker/Dockerfile` | `ghcr.io/mskazemi/yazses:2.18.2` is public and pullable, but **`:latest` 404s**, so a bare `docker pull ghcr.io/mskazemi/yazses` fails. ⛔ The claim "now published on every tag" was **false** — corrected 2026-08-14. `docker.yml` carried a `paths:` filter alongside `tags: ["v*"]`; a push filter set applies to tag pushes too, a tag push changes no files, so **every tag build was silently suppressed** — 7 runs ever, all on `main`, zero on a tag, across five releases (v2.16.0→v2.18.2). Trigger fixed; `latest` and `2.18` will appear on the next release. ⚠ the earlier "404" scare was a separate **measurement error**: GHCR rejects unauthenticated reads, so a bare `curl` returns 401/404 for images that exist — verify with a pull token, see below ([#76](https://github.com/MSKazemi/yazses/issues/76)) |
| **Scoop** | ✅ live | `../bucket/yazses.json` | bucket served from this repo — `scoop bucket add yazses https://github.com/MSKazemi/yazses`; manifest at **2.18.2**, raw URL 200 ([#79](https://github.com/MSKazemi/yazses/issues/79)) |
| **Chocolatey** | ❌ 404 | `chocolatey/` | nuspec + checksum verified; `.ps1` scripts **parse cleanly** (checked in `mcr.microsoft.com/powershell`), and the publish job re-parses them on a Windows runner before every push |

> **Verification gotcha:** `curl -o /dev/null -w '%{http_code}'` **lies** about Flathub,
> `search.nixos.org` and AlternativeTo — they are single-page apps that return **HTTP 200
> for pages that do not exist**. Use an API instead:
> `https://flathub.org/api/v2/appstream/<app-id>` correctly answers `App not found`.
>
> **And it lies the other way about GHCR.** A registry read without a token is rejected
> whether or not the image exists, so `401`/`404` there is not evidence of absence — this
> table carried "Docker ❌ 404" while `ghcr.io/mskazemi/yazses:2.18.2` was public and
> pullable. Get an anonymous pull token first:
>
> ```bash
> TOK=$(curl -s "https://ghcr.io/token?scope=repository:mskazemi/yazses:pull&service=ghcr.io" | jq -r .token)
> curl -s -H "Authorization: Bearer $TOK" https://ghcr.io/v2/mskazemi/yazses/tags/list
> ```
>
> **Do not hand-check any of this.** `scripts/check-release-channels.py --version <v>`
> queries every channel in this table the correct way and prints it as a table;
> `release-complete.yml` runs it on every tag.

### Two dead files kept only as history

`homebrew/yazses-formula.rb` and `homebrew/yazses-v1.rb` describe the abandoned **v1.0
Rust binary** distribution. The releases they point at (`v1.0.0`, `v1.0.0-dev.1`) were
**never published** — `gh release view v1.0.0` returns *release not found* — and their
checksums are still `PLACEHOLDER_…`. They are marked at the top of each file. **The
canonical cask is `homebrew/yazses.rb`.**

### Snap: `snap install yazses` does not work on arm64

The table used to say "incl. arm64", which reads as *arm64 users are covered*. They are
not. Measured 2026-08-13 from `api.snapcraft.io`:

| Track/risk | Arch | Revision | Version |
|---|---|---|---|
| `latest/stable` | amd64 | 118 | 2.18.2 |
| `latest/edge` | amd64 | 118 | 2.18.2 |
| `latest/edge` | **arm64** | 116 | **2.17.0** |

There is **no arm64 revision on `stable`**. `snap install yazses` resolves stable, so on
a Raspberry Pi or an arm64 VM it fails to find a revision at all — the arm64 build exists
only on `edge`.

Note the second problem in that table: amd64 moved 2.18.0 → 2.18.2 while arm64 stayed at
**2.17.0**. The gap is not static, it widens with every release, because whatever promotes
amd64 is not promoting arm64.

Two consequences worth stating plainly:

- Anyone writing "works on arm64" in launch copy would be wrong. The honest line is
  *"amd64 on stable; arm64 on `--edge` only"*.
- The contributor task for verifying the Snap arm64 install (`campaign/tasks.json`) asked
  someone to verify a path that cannot succeed with the documented command. Reworded to
  name `--edge` — the same defect #216 had for Intel macOS.

To fix properly, promote an arm64 build to stable in the Snap Store release channels, then
change this row. Query it without a browser:

```sh
curl -H 'Snap-Device-Series: 16' \
  'https://api.snapcraft.io/v2/snaps/info/yazses?fields=version,revision'
```

⚠ That header is **required** — without `Snap-Device-Series: 16` the API returns an error
rather than the channel map, which makes it easy to conclude "no data" and move on.

### Homebrew tap

Published 2026-08-13 at **[MSKazemi/homebrew-yazses](https://github.com/MSKazemi/homebrew-yazses)**,
which is what makes `brew tap MSKazemi/yazses && brew install --cask yazses` resolve. The
repository name must stay `homebrew-yazses` — Homebrew derives the tap name from it.

`Casks/yazses.rb` there is **byte-identical** to `homebrew/yazses.rb` here, which stays the
source of truth. After each release, refresh the checksum and copy it across:

```sh
python scripts/refresh-package-manifests.py --version <x.y.z>
cp packaging/homebrew/yazses.rb <tap>/Casks/yazses.rb   # then commit + push the tap
```

⚠ **This is owed the moment a release is tagged, and it has already been missed once.** The
tap was published against 2.18.0, then v2.18.1 and v2.18.2 shipped and the tap kept serving
**2.18.0**. Nobody was broken (the 2.18.0 asset still exists and its digest still matched),
which is precisely why it went unnoticed: every `brew install` in that window quietly
delivered a build two releases old. Re-synced to 2.18.2 on 2026-08-13 after checking the
cask's sha256 against the digest GitHub reports for the real `YazSes-2.18.2.dmg`.

✅ **You should not have to do this by hand — the automation already exists.**
`.github/workflows/publish-channels.yml` has a `homebrew` job that regenerates the cask and
pushes it to the tap on its own. It is gated on one secret:

> `TAP_TOKEN` — a **fine-grained** PAT, resource owner `MSKazemi`, scoped to the single
> repository `MSKazemi/homebrew-yazses`.

Until that secret is set the job does not fail — it logs
`::warning::TAP_TOKEN is not set -- skipping Homebrew` and **reports success**. So a green
"Publish to package channels" run is *not* evidence the tap was updated. Check the tap's own
last commit, or `gh api repos/MSKazemi/homebrew-yazses/contents/Casks/yazses.rb`.

That skip-and-pass behaviour is the right call for a workflow that publishes to several
registries — one missing credential should not block the others — but it does mean the
manual step above stays owed until the secret exists, and nothing will remind you.

Note the asymmetry, because it decides how this fails. The cask must track the **latest
published release**, not `pyproject.toml`:

- cask **behind** the newest release → users silently get an old build, forever, quietly;
- cask **ahead** of it → Homebrew verifies the digest, finds nothing at that URL, and
  refuses the download outright.

There is deliberately **no test** asserting cask version == `pyproject` version: between a
release-prep bump and the assets being published those two legitimately differ, so such a
test would fail on every release commit and get disabled. The guard is this checklist plus
`refresh-package-manifests.py --check`, which compares against the assets really attached
to a tag.

Verified at each sync: the tap is public, `Casks/yazses.rb` matches the source byte for
byte, and the `.dmg` URL the cask points at resolves on the corresponding release.

⚠ `raw.githubusercontent.com` caches for a few minutes, so it will serve the **old** cask
right after a push and make a correct sync look like it failed. Check
`gh api repos/MSKazemi/homebrew-yazses/contents/Casks/yazses.rb` instead — and note
Homebrew itself clones the tap over git, so the CDN lag never affects real users.

⚠ **Not verified: that `brew install --cask yazses` actually completes.** Casks only
install on macOS and the authoring machine is Linux, so the end-to-end run is owed by
whoever first has a Mac in hand. What is proven is that every input Homebrew reads is
present, well-formed and correctly hashed.

### macOS: the .dmg is Apple Silicon only

Audited 2026-08-13, and this is the single most important fact about the macOS
channel because the docs previously promised the opposite.

`build-macos.yml` runs on `macos-latest`. That label is an **arm64** image — the
v2.18.0 build resolved its Python to `aarch64-apple-darwin`, confirmed from the job
log. `packaging/macos/yazses.spec` passes `target_arch=None`, which PyInstaller reads
as *host architecture*, not `universal2` despite what the comment there used to say.
So the `.dmg` contains **no x86_64 slice and cannot launch on an Intel Mac.**

Reproduce any of this yourself, on Linux, with no Mac and no `hdiutil`:

```sh
uv run python scripts/inspect-dmg.py YazSes-<version>.dmg \
    --expect-version <version> --expect-arch arm64
```

It decodes the UDIF container `create-dmg` produces and reads the bundle's
`Info.plist` and every Mach-O header out of the raw image. Both flags exit non-zero on
a mismatch, so a release job can assert them — which is what would have caught the
`0.1.2` version and the missing Intel slice years earlier. ⚠ It answers *"is the right
thing inside the artefact"*, never *"does it launch"*; the second still needs a Mac.

This was **verified against the artefact**, not only inferred from the runner. The
`.dmg` that CI built for PR #263 was decompressed on Linux (UDIF/`koly` trailer → blkx
block table → zlib chunks; no macOS tooling involved) and every Mach-O header in the
image inspected:

```
Mach-O slices found, by CPU type: {'arm64': 122}
MH_EXECUTE (main binaries):      1, arm64
universal/fat headers (0xCAFEBABE): 0
```

122 arm64 slices, **zero x86_64, zero universal headers**. The same pass read the
bundle's `Info.plist` straight out of the image and confirmed the version fix landed:
`CFBundleShortVersionString` and `CFBundleVersion` both `2.18.0` (they were the literal
`0.1.2` before), and `LSMinimumSystemVersion` `11.0`, matching the cask's
`depends_on macos: ">= :big_sur"`.

`universal2` is not reachable by changing that one value. PyInstaller can only emit a
universal binary when every bundled native dependency is itself universal, and
`ctranslate2` (via `faster-whisper`) publishes separate arm64 and x86_64 macOS wheels.

Intel coverage therefore needs a **second CI job on an Intel runner**. GitHub retired
the free Intel image; Intel is now only `-large`/`-intel` labels, which are billed
**even for public repositories**. That is a spend decision, so it is documented rather
than assumed. Until it is made:

- the cask declares `depends_on arch: :arm64`, so Homebrew refuses cleanly on Intel
  instead of installing an app that cannot start;
- `docs/macos-install.md` routes Intel users to `pipx install yazses`, which is
  architecture independent.

⚠ **Three open issues invite contributors to test on hardware that cannot work.**
[#216](https://github.com/MSKazemi/yazses/issues/216) ("Test YazSes on macOS (Intel)")
in particular asks someone to test a `.dmg` now known to be arm64-only;
[#24](https://github.com/MSKazemi/yazses/issues/24) and
[#182](https://github.com/MSKazemi/yazses/issues/182) should say which chip they mean.
They need rewording before anyone spends an evening on them.

⚠ **No human has confirmed the `.dmg` launches at all**, on either architecture. A
71 MB artefact existing is not evidence that it runs — this repo has already shipped a
Windows `.exe` across several releases that never started a daemon.

### Windows: Scoop and Chocolatey

Both were authored from the **verified** SHA256 of the released
`YazSes-2.17.0-windows-x64.exe` (`ece0830…1bdf`), computed from the asset itself and
size-checked against the release metadata.

What is and is not proven, stated exactly:

| Artefact | Verified how | Not verified |
|---|---|---|
| `scoop/yazses.json` | validates against Scoop's **official `schema.json`** | never installed on Windows |
| `chocolatey/yazses.nuspec` | well-formed XML, required nuspec fields present | not packed with `choco pack` |
| `chocolatey/tools/*.ps1` | — | **PowerShell syntax unchecked** — no `pwsh` here |

**Before submitting either**, run them once on a real Windows machine:
`scoop install ./yazses.json`, and `choco pack` + `choco install yazses -s .`.
They are deliberately committed as *unshipped* rather than published blind — the whole
reason this file has a status table is that this repo already had three manifests that
looked finished and installed nobody.

⚠️ `scoop/yazses.json` deliberately has **no `autoupdate.hash`**. When it was written,
releases published no `SHA256SUMS` asset, so pointing at one would 404 and silently break
every future update; with the key absent, Scoop downloads the new installer and computes
the digest itself.

**That premise changed on 2026-08-13.** PR #262 added `.github/workflows/checksums.yml`,
which attaches a `SHA256SUMS.txt` to every release. So `autoupdate.hash` *could* now point
at it — but the manifest has not been changed, deliberately: the first release carrying
that asset should be observed before a future auto-update is made to depend on it, and
nothing here has been installed on a real Windows machine yet. Revisit alongside
[#79](https://github.com/MSKazemi/yazses/issues/79).

### Nix

`../flake.nix` provides `nix run github:MSKazemi/yazses` plus a `yazses-desktop` variant
that adds Qt, and a dev shell.

**Every nixpkgs attribute it references was verified to exist** on `nixos-unstable`
(2026-08-11) by fetching the definitions directly — including the two that block a
conda-forge recipe outright: `faster-whisper` (**1.2.1**, matching this project's floor)
and `ctranslate2`. Braces balance. That is the whole of what is proven.

⚠️ **It has never been evaluated.** There is no Nix on the authoring machine, and
fetching a Nix binary purely to get one was not an acceptable trade. Before advertising
it anywhere:

```sh
nix flake check
nix build .#yazses && ./result/bin/yazses --help
nix run . -- transcribe data/librispeech-sample/jfk.wav   # compare with jfk.txt
```

⚠️ **Verification gotcha, again.** `search.nixos.org`'s backend query returned *zero
hits for every package*, including ones that certainly exist, and GitHub code search
reported `numpy` as absent from nixpkgs. Both are wrong. The only check that held up was
fetching `pkgs/development/python-modules/<name>/default.nix` directly and reading
`pkgs/top-level/python-packages.nix`. **Do not conclude a package is missing from a
search API.**

### Keeping checksums honest

`../scripts/refresh-package-manifests.py` recomputes every checksum from the actual
released assets and rewrites the manifests. Run it after each release rather than
hand-editing a hash:

```sh
uv run python scripts/refresh-package-manifests.py --version 2.17.0 --check   # verify only
uv run python scripts/refresh-package-manifests.py --version 2.18.0           # write
```

```
packaging/
├── homebrew/        Homebrew Cask formula (macOS)
├── macos/           PyInstaller spec + entitlements (macOS .dmg build)
├── windows/         PyInstaller spec + Inno Setup script (Windows .exe build)
└── winget/          winget-pkgs manifests (Windows)
```

## Homebrew (macOS) — `brew install --cask yazses`

`homebrew/yazses.rb` is the Cask formula. Two ways to publish it:

### Option A — personal tap (fastest, no review)

1. Create a public repo named `homebrew-yazses` under your GitHub user/org.
2. Copy `homebrew/yazses.rb` into the new repo's root as `Casks/yazses.rb`.
3. Bump the `version` and (after signing) the `sha256` on each release.
4. Users install with:

   ```sh
   brew tap MSKazemi/yazses
   brew install --cask yazses
   ```

### Option B — submit to homebrew/cask (broader reach, ~1 week review)

Homebrew's main `cask` repo accepts user submissions but requires a real SHA
(no `:no_check`). That means signed builds first. Defer until after we sign
and notarise.

## winget (Windows) — `winget install MSKazemi.YazSes`

`winget/manifests/m/MSKazemi/YazSes/0.4.0/` contains the three manifest
files (version, installer, locale) per the v1.6 schema. To publish:

1. Build and tag a release so `YazSes-0.4.0-windows-x64.exe` is downloadable
   from `https://github.com/.../releases/download/v0.4.0/...`.
2. Compute the SHA-256 of the released `.exe`:

   ```powershell
   (Get-FileHash YazSes-0.4.0-windows-x64.exe -Algorithm SHA256).Hash
   ```

3. Replace `REPLACE_WITH_SHA256_OF_RELEASED_EXE` in
   `installer.yaml` with that hash.
4. Fork [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs).
5. Copy the three manifest files into the fork at the same path:
   `manifests/m/MSKazemi/YazSes/0.4.0/`.
6. Open a PR. The validation pipeline runs automated checks; expect ~1–3
   days to merge.
7. Once merged, users install with:

   ```powershell
   winget install MSKazemi.YazSes
   ```

   (or `winget install yazses` thanks to the `Moniker` field).

## AUR (Arch Linux) — `yay -S yazses`

`arch/PKGBUILD` is the AUR recipe. Publishing requires an AUR account at
https://aur.archlinux.org and pushing the PKGBUILD to
`ssh://aur@aur.archlinux.org/yazses.git`. Full steps in
`arch/README.md`.

## .deb / apt / snap / PPA (Linux)

Already shipping — see `../scripts/build-deb.sh`,
`../scripts/update-apt-repo.sh`, the `Snap` workflow, and the `Launchpad PPA`
workflow.
