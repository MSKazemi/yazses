# The canonical Homebrew cask for YazSes.
#
# Source of truth: packaging/homebrew/yazses.rb in MSKazemi/yazses.
# Published copy:  Casks/yazses.rb in MSKazemi/homebrew-yazses (the tap users
# actually tap). The two are byte-identical; edit the source and copy it over,
# never the other way round.
#
# Two sibling files in packaging/homebrew/ -- `yazses-formula.rb` and
# `yazses-v1.rb` -- describe an abandoned v1.0 Rust binary distribution whose
# releases were never published, and still carry PLACEHOLDER checksums. They are
# kept only as history. Do not publish them.
#
# Do not hand-edit the version or sha256 below. Regenerate them from the assets
# actually attached to the tag:
#   python scripts/refresh-package-manifests.py --version <x.y.z>
#
# This is still a manual post-release step -- no workflow runs it, which is how
# this file sat at v2.17.0 while v2.18.0 was the current release. A wrong hash is
# worse than no cask: Homebrew refuses the download, so the first thing a new
# user sees is a failure that looks like the project is broken.
cask "yazses" do
  version "2.35.0"
  sha256 "e964bcfbef43c5de393526ae31b8b3b9719b29013e448549afbbe0de95e52aa4"

  # arm64 explicitly in the filename since ADR-017: the .dmg used to be named as
  # though it were for everybody, which is a large part of why an Apple-silicon-only
  # bundle went unnoticed. An Intel .dmg is now built too, but this cask will not
  # offer it until that build has been green a few times -- a cask whose hash is a
  # guess is worse than no cask.
  url "https://github.com/MSKazemi/yazses/releases/download/v#{version}/YazSes-#{version}-macos-arm64.dmg",
      verified: "github.com/MSKazemi/yazses/"
  name "YazSes"
  desc "Offline voice dictation — hold a key, speak, release; no cloud, no subscription"
  homepage "https://mskazemi.com/yazses/"

  livecheck do
    url :url
    strategy :github_latest
  end

  # Matches LSMinimumSystemVersion "11.0" declared by the app bundle itself in
  # packaging/macos/yazses.spec — keep the two in step.
  depends_on macos: ">= :big_sur"

  # Apple Silicon only, and this is a statement of fact about the artefact, not
  # a preference. The .dmg is built by .github/workflows/build-macos.yml on
  # macos-latest, which is an arm64 image, and packaging/macos/yazses.spec
  # passes target_arch=None (host arch). So the bundled Mach-O has no x86_64
  # slice and will not launch on an Intel Mac.
  #
  # Without this line Homebrew installs it anyway and the user gets a silent
  # failure to launch. With it they get a clean, accurate refusal and the
  # caveats below point them at the install route that does work on Intel.
  depends_on arch: :arm64

  app "YazSes.app"

  # The daemon is a launchd LaunchAgent under com.yazses.daemon; tear it
  # down on uninstall before files vanish.
  uninstall quit:      "com.yazses.app",
            launchctl: "com.yazses.daemon"

  zap trash: [
    "~/Library/Application Support/yazses",
    "~/Library/Caches/yazses",
    "~/Library/Logs/yazses",
    "~/Library/LaunchAgents/com.yazses.daemon.plist",
  ]

  caveats <<~EOS
    YazSes needs TWO permissions to hear the dictation key, not one. Granting
    only Accessibility leaves the key dead in every application, with the
    Accessibility toggle sitting there enabled — the single most common way a
    working install looks broken.

      1. System Settings → Privacy & Security → Accessibility → enable YazSes
      2. Launch YazSes and hold the dictation key once. macOS then prompts for
         Input Monitoring; enable YazSes there too, and relaunch the app.
      3. Holding the key again prompts for Microphone access. Allow it.

    Not in the Input Monitoring list? An app only appears there once it has
    asked. Hold the key once and look again — the + button cannot add it first.

    No microphone prompt either? That is the same problem upstream: YazSes only
    records while the key is held, so a key dead for want of Input Monitoring
    never records, never prompts, and never reaches the Microphone pane.

    `yazses doctor` reports Accessibility and Input Monitoring as two rows,
    because they are two switches and either one being off kills the key.

    Default hotkey: Right Option. Configurable in:
        ~/Library/Application Support/yazses/config.toml

    This is an unsigned developer preview. If macOS refuses to launch the
    app, right-click YazSes.app and choose Open the first time.

    Because it is unsigned, macOS treats the app as a new identity whenever
    its hash changes, so you may have to re-grant BOTH Accessibility and Input
    Monitoring after an upgrade.

    On an Intel Mac this cask will refuse to install: it tracks the Apple Silicon
    build. An Intel .dmg is now produced as well, and this cask will offer it once
    that build is proven. Until then, install from PyPI, which is architecture
    independent and is also the path that outlives the Intel bundle — GitHub retires
    x86_64 macOS runners in 2027:

        pipx install yazses && yazses quickstart
  EOS
end
