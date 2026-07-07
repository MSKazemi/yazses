# YazSes packaging

Per-channel packaging artefacts. **Read this when you want to publish to a
new distribution channel** — the build scripts in `../scripts/` use the
files here as inputs.

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
