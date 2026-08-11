# YazSes packaging

Per-channel packaging artefacts. **Read this when you want to publish to a
new distribution channel** — the build scripts in `../scripts/` use the
files here as inputs.

## ⚠ Channel status — read this first (audited 2026-08-11)

**A manifest living in this directory installs nobody.** It has to be published to the
registry. Every channel below was checked live on 2026-08-11:

| Channel | Published? | In-repo artefact | State |
|---|---|---|---|
| PyPI | ✅ live | — | `pipx install yazses` |
| Snap Store | ✅ live | `../snap/` | incl. arm64 |
| APT repo | ✅ live | `../scripts/update-apt-repo.sh` | signed |
| GitHub Releases | ✅ live | — | `.dmg`, `.exe`, `.deb` |
| **Homebrew** | ❌ **404** | `homebrew/yazses.rb` | cask is **current (2.17.0, real sha)** — needs a tap repo ([#6](https://github.com/MSKazemi/yazses/issues/6)) |
| **winget** | ❌ **404** | `winget/…/2.17.0/` | manifests are **current (real sha)** — needs a PR to `microsoft/winget-pkgs` ([#78](https://github.com/MSKazemi/yazses/issues/78)) |
| **AUR** | ❌ **404** | `arch/PKGBUILD` | ⚠ stale at `pkgver=0.4.0`, `sha256sums=SKIP` ([#67](https://github.com/MSKazemi/yazses/issues/67)) |
| **Flathub** | ❌ not found | — | nothing built yet ([#45](https://github.com/MSKazemi/yazses/issues/45)) |
| **Nix** | ❌ 0 hits | — | ([#68](https://github.com/MSKazemi/yazses/issues/68)) |
| **Docker/GHCR** | ❌ 404 | `docker/Dockerfile` | image **builds and runs** — needs publishing ([#76](https://github.com/MSKazemi/yazses/issues/76)) |
| **Scoop** | ❌ 404 | — | ([#79](https://github.com/MSKazemi/yazses/issues/79)) |

> **Verification gotcha:** `curl -o /dev/null -w '%{http_code}'` **lies** about Flathub,
> `search.nixos.org` and AlternativeTo — they are single-page apps that return **HTTP 200
> for pages that do not exist**. Use an API instead:
> `https://flathub.org/api/v2/appstream/<app-id>` correctly answers `App not found`.

### Two dead files kept only as history

`homebrew/yazses-formula.rb` and `homebrew/yazses-v1.rb` describe the abandoned **v1.0
Rust binary** distribution. The releases they point at (`v1.0.0`, `v1.0.0-dev.1`) were
**never published** — `gh release view v1.0.0` returns *release not found* — and their
checksums are still `PLACEHOLDER_…`. They are marked at the top of each file. **The
canonical cask is `homebrew/yazses.rb`.**

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
