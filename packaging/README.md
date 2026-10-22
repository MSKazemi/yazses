# YazSes packaging

Per-channel packaging artefacts. **Read this when you want to publish to a
new distribution channel** — the build scripts in `../scripts/` use the
files here as inputs.

## ⚠ Channel status — read this first (audited 2026-08-11; live re-check of every channel 2026-09-25)

**A manifest living in this directory installs nobody.** It has to be published to the
registry.

Every channel below was re-checked against its own API on **2026-09-25, after v2.40.0**,
with `scripts/check-release-channels.py --version 2.40.0`. Do not trust a row without doing
that — this pass found the **Chocolatey row claiming the package had never published while
two versions were already approved and serving**, the Docker row denying a `latest` tag that
exists, and four rows quoting versions several releases old. What held up: PyPI, the APT repo,
Snap, the Homebrew tap, the Scoop bucket and GHCR all serve **2.40.0**.

⚠ **A version in this directory is not a version in the registry.** Six channels publish on
their own clock, and three of them (winget, Chocolatey, AUR) are gated on a human — so the
in-repo manifests being at 2.40.0 says nothing about what a user gets today.

| Channel | Published? | In-repo artefact | State |
|---|---|---|---|
| PyPI | ✅ live | — | `pipx install yazses` |
| Snap Store | ✅ live on amd64 + arm64 | `../snap/` | stable **2.40.0** on both architectures (rev 431 amd64 / 430 arm64, checked 2026-09-25); dictation works on X11 **and on GNOME/KDE Wayland** via the RemoteDesktop portal since v2.37.0 — see below |
| APT repo | ✅ live | `../scripts/update-apt-repo.sh` | signed |
| GitHub Releases | ✅ live | — | `.dmg`, `.exe`, `.deb` |
| **Homebrew** | ✅ live | `homebrew/yazses.rb` | tap at [MSKazemi/homebrew-yazses](https://github.com/MSKazemi/homebrew-yazses), cask serves **2.40.0** (checked 2026-09-25), still **arm64 only** (`depends_on arch: :arm64`; Intel Macs take the `.dmg` or PyPI) — see the macOS section ([#6](https://github.com/MSKazemi/yazses/issues/6)) |
| **winget** | ✅ live, but **serving 2.36.0 — 7 releases behind** | `winget/…/2.40.0/` | `winget install MSKazemi.YazSes` resolves — [#416963](https://github.com/microsoft/winget-pkgs/pull/416963) was merged 2026-09-10. ⚠ upstream `manifests/m/MSKazemi/YazSes` holds **only 2.35.0 and 2.36.0** (GitHub contents API, 2026-09-25), so a user installing today gets **2.36.0** (tagged 2026-08-30) while the current release is 2.40.0. `WINGET_TOKEN` is **not set**, so `publish-channels.yml` skips winget on every tag and each bump needs a hand-opened PR. Set the secret and this stops needing a human ([#78](https://github.com/MSKazemi/yazses/issues/78)) |
| **AUR** | ❌ **not published — blocked upstream, not on the recipe** | `arch/PKGBUILD` | `aur.archlinux.org/rpc/v5/info?arg[]=yazses` returns `resultcount: 0` (checked 2026-09-25). The recipe is ready and current (`pkgver=2.40.0`, real `sha256sums` matching `.SRCINFO`; `arch/README.md` records a clean-container verification — `namcap` clean, full `makepkg --nodeps` build, checksum match). ⛔ The old **"nothing remains but `git push`"** framing is misleading and cost time twice: per the maintainer's notes, **AUR account registration itself was paused upstream on 2026-09-19** (anti-automation measures, no ETA) and no account exists yet. This is not a five-minute task — check `aur-general` before retrying ([#67](https://github.com/MSKazemi/yazses/issues/67)) |
| **Fedora / COPR** | ✅ live, but **hand-rebuilt** | `fedora/yazses.spec` | [copr.fedorainfracloud.org/coprs/mskazemi/yazses](https://copr.fedorainfracloud.org/coprs/mskazemi/yazses) serves **2.36.0** (recorded in `../docs/install-linux.md` when the repo was created, 2026-09-13). ⚠ **No workflow touches this channel** — `grep -i copr .github/workflows/` finds nothing — so a tag does not rebuild it and the spec being current does not move what `dnf` installs; that needs `copr-cli build yazses <srpm>` by hand. The spec's `Version:` is no longer the thing that lags: `../scripts/refresh-package-manifests.py` rewrites it at release time and `tests/test_packaging_manifest_versions.py` compares it with every other manifest. It had been pinned at 2.18.2 for seventeen releases, was fixed by hand at 2.36.0 ([#370](https://github.com/MSKazemi/yazses/pull/370)), and had drifted four releases again before either of those existed. ⚠ COPR needs `--enable-net on` for this package |
| **Flathub** | ❌ not published | `../packaging/flatpak/` | manifest **builds green**; the submission ([flathub#9765](https://github.com/flathub/flathub/pull/9765)) was auto-closed for an incomplete checklist and a maintainer declined to reopen. The one unchecked item is **a video of the app running from the Flatpak** — that is the whole remaining blocker ([#45](https://github.com/MSKazemi/yazses/issues/45)) |
| **Nix** | ❌ 0 hits | `../flake.nix` | authored; **every nixpkgs attribute verified to exist**, but ⚠ **never evaluated** (no Nix here) ([#68](https://github.com/MSKazemi/yazses/issues/68)) |
| **Docker/GHCR** | ✅ **live, `latest` included** | `docker/Dockerfile` | `ghcr.io/mskazemi/yazses` serves **2.40.0**, `2.40` and **`latest`** among 73 tags (verified 2026-09-25 with an anonymous pull token), so a bare `docker pull ghcr.io/mskazemi/yazses` now works. ⛔ This row read **"one tag only, no `latest`"** until 2026-09-25 — that was true when `docker.yml` carried a `paths:` filter alongside `tags: ["v*"]` (a push filter set applies to tag pushes too, and a tag push changes no files, so every tag build was silently suppressed). The trigger was fixed and `latest` has published since. ⚠ GHCR rejects unauthenticated reads, so a bare `curl` returning 401/404 is **not** evidence of absence — get a pull token first, see below ([#76](https://github.com/MSKazemi/yazses/issues/76)) |
| **Scoop** | ✅ live **and current** | `../bucket/yazses.json` | bucket served from this repo — `scoop bucket add yazses https://github.com/MSKazemi/yazses`; manifest at **2.40.0**, verified 2026-09-25, raw URL 200. Because the bucket *is* this repo, Scoop is the one Windows channel with no third-party gate — it is current the moment a release lands ([#79](https://github.com/MSKazemi/yazses/issues/79)) |
| **Chocolatey** | ✅ **live, serving 2.39.0** | `chocolatey/` | ⛔ This row read **"never published, 19 releases running, `CHOCO_API_KEY` never set"** until 2026-09-25 — **false**. The community feed lists **2.37.1** (approved 2026-09-21) and **2.39.0** (approved 2026-09-24), so `choco install yazses` works. ⚠ **2.39.1 and 2.40.0 sit at `PackageStatus: Submitted`, not approved** — Chocolatey moderates every version, so the feed trails the newest tag by however long review takes. Query it with `Packages()?$filter=Id eq 'yazses'`, which returns **only approved** versions; the per-version endpoint answers 200 for a submitted one, so a bare status code reads as published when it is not. `.ps1` scripts **parse cleanly** (checked in `mcr.microsoft.com/powershell`), and the publish job re-parses them on a Windows runner before every push |

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

### Snap: both architectures are live, and dictation is no longer X11-only

Measured 2026-09-25 from `api.snapcraft.io`:

| Track/risk | Arch | Revision | Version |
|---|---|---|---|
| `latest/stable` | amd64 | 431 | 2.40.0 |
| `latest/stable` | arm64 | 430 | 2.40.0 |
| `latest/edge` | amd64 | 431 | 2.40.0 |
| `latest/edge` | arm64 | 430 | 2.40.0 |

Architecture availability does not mean full desktop compatibility. The package uses
strict confinement: with `audio-record` and `raw-input` connected manually, hold-to-talk
dictation works on **X11** — and, since **v2.37.0**, on **GNOME/KDE Wayland** as well.

⚠ The paragraph that stood here said Wayland injection "requires host access that the snap
does not have" and told Wayland users to install something else. That was true of the two
mechanisms it had in mind — `ydotool` needs a udev rule a strict snap cannot install, and
`wtype` needs a protocol neither GNOME nor KDE implements — and it was wrong about the
conclusion. `src/yazses/inject/portal.py` types through
`org.freedesktop.portal.RemoteDesktop`, which rides on the `desktop` plug the snap already
has, and `src/yazses/inject/registry.py` marks the portal
`consent_implied_by_confinement=("strict",)` precisely because it is a strict snap's only
route. The user approves one desktop permission prompt at first dictation; a restore token
makes later runs silent. Store metrics are why this mattered: of 59 installs on 2026-09-10,
at least 39 were on a Wayland-by-default desktop, i.e. the install instructions were
sending most of the user base away.

`yazses setup` still cannot provision the host from inside confinement, and must never be
presented as a step for Snap users.

Query the live channel map without a browser:

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

What the offline suite does hold every checksummed manifest to is **the tree's own record
of the last release**, `released-assets.json` (written by the same refresh run), and that
record may trail `pyproject.toml` by at most one release (`tests/release_window.py`). It is
deliberately **not** compared with the newest git tag: a tag is pushed before its assets
can be refreshed in, so a tag-based check turned every open PR red for each release window
([#602](https://github.com/MSKazemi/yazses/issues/602)). A skipped refresh still fails —
at the next release commit, which `release.yml` tests before publishing — and a late one is
reported daily by `channel-drift.yml` after its 24-hour grace.

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

### macOS: the .dmg was Apple Silicon only (fixed in v2.22.0)

Audited 2026-08-13, and this was the single most important fact about the macOS
channel because the docs promised the opposite.

⚠ **Superseded for the release assets, not for the cask.** Since **v2.22.0**
(2026-08-16) every release has carried `YazSes-<version>-macos-x86_64.dmg` alongside the
arm64 one, built on a `macos-15-intel` runner (ADR-017); `packaging/released-assets.json`
records what the last release actually attached. What remains true is the **cask**:
`refresh-package-manifests.py` hashes the arm64 `.dmg` only, so `homebrew/yazses.rb`
still keeps `depends_on arch: :arm64`. Everything below is the record of how the
arm64-only gap was found, and the `inspect-dmg.py` recipe still applies to either
artefact.

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

Intel coverage therefore needs a **second CI job on an Intel runner**, and since
v2.22.0 it has one: `macos-15-intel` in the `build-macos.yml` matrix, producing a
second `…-macos-x86_64.dmg` per release. It is `continue-on-error`, so a release can
still ship without it. `macos-15-intel` is the **last** x86_64 image GitHub Actions
will offer, available until **August 2027** (ADR-017); `macos-13` was retired on
2025-12-04. When it goes, pipx is the only Intel path left.

Alongside that:

- the cask declares `depends_on arch: :arm64`, so Homebrew refuses cleanly on Intel
  instead of installing an app that cannot start;
- `docs/macos-install.md` routes Intel users to `pipx install yazses`.

⚠ **That pipx route is no longer architecture independent, which this file used to
claim.** Measured against the live index: on Intel macOS the base install resolves
only on **Python 3.11–3.13** (`onnxruntime` shipped no x86_64 macOS wheel after
1.23.2, which has no cp314 build, and `faster-whisper` requires it), and `[all]`
only on **3.11–3.12** (`torch` shipped none after 2.4.1/cp312). So the fallback for
a missing Intel `.dmg` has an expiry date of its own, arriving from upstream rather
than from Apple or from GitHub. `src/yazses/system/intel_macos.py` turns this into a
`yazses doctor` row, and `tests/test_intel_macos_ceiling.py` ties the numbers to the
markers in `pyproject.toml` so they cannot drift apart. Context: #264.

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

### Windows add-on packs: the licence gate (ADR-028 Q7)

`scripts/build-packs.py` runs `scripts/pack_licences.py` on every pack after its wheels are
installed. Each distribution is classed `permissive`, `LGPL` (LGPL and MPL-2.0), `GPL`
(GPL and AGPL) or `UNKNOWN`, from its `License-Expression` (SPDX: `OR` takes the most
permissive branch, `AND` the strictest, `WITH` only a known exception), otherwise from
its `License` field and `License ::` classifiers (the stricter wins). The pack is
**withheld**, like any other failed check, when a distribution is `UNKNOWN`, has no
licence file in its dist-info, is `LGPL`/`GPL` with no upstream URL in METADATA, or is
`GPL` with no matching entry in `packs/licence-approvals.toml`. A copyleft distribution
puts `LICENSES/SOURCE.md` (name, version, licence, upstream and PyPI source) in the pack.
The classification goes into `build-report.json` (`licence_gate`) and `pack.json`
(`licences`).

Recording a decision, in `packs/licence-approvals.toml`:

- `[[approval]]`: **owner only.** One pack, one distribution, one exact version and the
  licence exactly as the build report prints it, plus `approved_by`, `date`, `reason`.
- `[[clarification]]`: a person read the licence file of a distribution whose metadata is
  free text, and records the SPDX expression it really is. A clarification to GPL still
  needs an approval, and no clarification excuses a missing licence file.

- `[[licence_text]]`: a distribution declares a licence but ships no licence file. Commit
  the upstream text under `packs/licence-texts/<dist>/<version>/`, and record `pack`,
  `dist`, `version`, `spdx`, `source_url` (a permalink at the release's commit), `file`
  (relative to `packs/`), `sha256` (`sha256sum` of the committed file), `reviewed_by`,
  `date`. The build copies it to `LICENSES/<dist>/` in the pack only when the version,
  the declared licence and the hash all match and `reviewed_by` is filled in. It never
  replaces a licence file the distribution ships (that entry is reported as redundant).
  `.gitattributes` keeps these files byte-exact on every checkout; do not edit them.

An entry whose distribution, version, licence, file or hash no longer matches is printed
as stale in the build report and approves nothing.

**Prepared, unsigned entries.** A `[[clarification]]` or `[[licence_text]]` may be
committed with `reviewed_by = ""` and `date = ""`. It is listed under `awaiting_review`
in the build report and honours nothing. That is how an agent or a contributor stages an
entry: only a person who has read the licence fills those two fields in. An
`[[approval]]` can never be unsigned.

**Releasing `diarization` (licence side).** The first real build would withhold it:
from the metadata of the Linux 1.13.8 wheels in a local uv cache (the Windows wheels'
METADATA has not been read), `sherpa-onnx-core` has no licence file and `sherpa-onnx`
declares `License: Apache licensed, as found in the LICENSE file`, which is not an SPDX
expression. Both entries that fix this are committed, unsigned.

**Do not sign these as Apache-2.0 (finding, 2026-10-21).** The sherpa-onnx 1.13.8 binaries embed espeak-ng, which is GPL-3.0-or-later: `strings` on the Linux wheels finds 137 `espeak` symbols in `libsherpa-onnx-c-api.so` and 98 in `_sherpa_onnx…so` (`espeak_Initialize`, `espeak_TextToPhonemesWithTerminator`, `espeak_CompileDictionary`; `.constprop`/`.isra` suffixes mean statically compiled in, not loaded). sherpa-onnx builds TTS in by default, so the Windows wheels very likely do too (not checked). The declared licence is therefore incomplete, and the gate cannot see it because it reads declared metadata only. Redistributing these binaries in a Windows add-on means GPL-3.0 obligations: an `[[approval]]` for GPL-3.0-or-later plus a source offer in `SOURCE.md`, or a sherpa-onnx build without TTS. Owner decision 2026-10-21: leave both entries unsigned; `diarization` stays PyPI-only (pip/uv), which is not redistribution by YazSes. This is a technical finding, not legal advice.

Only if that is resolved, the steps to release it are:

1. Read `packs/licence-texts/sherpa-onnx-core/1.13.8/LICENSE` and compare it with its
   `source_url` (the repository's `LICENSE` at tag `v1.13.8`, commit `11afbd0`; it is
   byte-identical to apache.org's `LICENSE-2.0.txt`). Read the `LICENSE` in the
   `sherpa-onnx` 1.13.8 wheel's `.dist-info/licenses/`.
2. In `packs/licence-approvals.toml`, put your full name in `reviewed_by` and the day in
   `date` (YYYY-MM-DD) of both diarization entries.
3. In the same commit, set `DIARIZATION_LICENCES_SIGNED = True` in
   `tests/test_pack_licences.py`, then run
   `uv run python -m pytest tests/test_pack_licences.py`.

The pack still has to pass the bind probe and a real Windows build. ADR-028 names
`espeakng-loader` (`tts`, deferred) for the missing-licence reason too. The gate reads
declared metadata only; it cannot see a GPL binary vendored in a wheel that declares MIT.

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

`fedora/yazses.spec` is rewritten by the same run even though it carries no checksum:
its `Version:` is what `%{pypi_source yazses}` expands into a download, so a spec left
behind does not fail — it builds the *previous* release and COPR publishes it as the
current package. The `%changelog` entry comes with it, dated from the release so the
weekday matches (`rpmbuild` warns `bogus date in %changelog`, and a warning is not a
failure, which is why both hand-written entries were wrong).
The same run writes `released-assets.json`: the plain list of files that release
attached to its tag. Nothing installs from it — it exists so an **offline** test can
answer "does this binary exist?" without asking GitHub.
`docs/platform-support.md` marks a desktop bundle ✅ or ⏳ on that basis, and
`tests/test_platform_support_claims.py` fails in both directions. It is generated:
do not hand-edit it, and do not leave it behind at release time, or the page starts
describing the release before last.

```
packaging/
├── homebrew/        Homebrew Cask formula (macOS)
├── released-assets.json   what the last release published (generated)
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

## MCP bundle and MCP registry — `yazses mcp-server` (ADR-032)

Two ways for an MCP client to find `yazses mcp-server`. Neither ships a second copy of
YazSes, and neither is published yet. The user-facing page is
[`../docs/how-to/connect-mcp-client.md`](../docs/how-to/connect-mcp-client.md).

**The `.mcpb` bundle.** `python3 scripts/build-mcpb.py` writes
`dist/yazses-<version>.mcpb` from `mcpb/manifest.template.json`. The build is
reproducible, so a release job can attach it and add it to `SHA256SUMS.txt`; no
workflow does that yet. Built and unit-tested only, not yet installed in a real client.

**The MCP registry entry.** `python3 scripts/render-mcp-server-json.py` writes
`dist/server.json` from `mcp-registry/server.template.json`. It points at PyPI's
`yazses` at the project version, over stdio, with the argument `mcp-server`. Publishing
is an outward-facing step the owner runs by hand:

1. **Ownership marker.** The registry accepts a PyPI package only if its PyPI
   description (our `README.md`) contains the line `mcp-name: io.github.MSKazemi/yazses`,
   for example as an HTML comment, `<!-- mcp-name: io.github.MSKazemi/yazses -->`. Add
   it, and cut a release so a version on PyPI carries it.
2. **Check out that release tag** and run `python3 scripts/render-mcp-server-json.py`.
   `server.json` takes its version from `pyproject.toml`, and the registry rejects a
   version that is not on PyPI.
3. **Check the fields against the registry's current schema.** Install `mcp-publisher`
   as the [registry's publishing guide](https://github.com/modelcontextprotocol/registry)
   describes, run `mcp-publisher init` in an empty scratch directory, and compare the
   file it writes with `dist/server.json`. Copy its `$schema` line in, and fix any
   field name that has changed in `mcp-registry/server.template.json` too. The template
   has no `$schema` line because the schema version could not be confirmed offline.
4. **Log in** from `dist/` with `mcp-publisher login github`, as the `MSKazemi` account.
   The `io.github.MSKazemi/` namespace is tied to that GitHub account.
5. **Publish** with `mcp-publisher publish`, still in `dist/`.
6. **Verify** by searching for `io.github.MSKazemi/yazses` in the registry. Then update
   the docs page, which still says the entry is not listed.

Each later release needs steps 2, 4 and 5 again with the new version. That can join the
release workflow only after the owner approves it, under `.github/CI_POLICY.md`.
