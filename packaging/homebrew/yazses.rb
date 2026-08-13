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
  version "2.18.2"
  sha256 "f3b24712bf7b65f5ad03cbe12c98f3ef713184d9a16c841820814b9e33103858"

  url "https://github.com/MSKazemi/yazses/releases/download/v#{version}/YazSes-#{version}.dmg",
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
    YazSes listens for the dictation hotkey using macOS's Accessibility
    API. After install, grant access in:

        System Settings → Privacy & Security → Accessibility → YazSes

    On first dictation, macOS will also prompt for Microphone access. Allow it.

    Default hotkey: Right Option. Configurable in:
        ~/Library/Application Support/yazses/config.toml

    This is an unsigned developer preview. If macOS refuses to launch the
    app, right-click YazSes.app and choose Open the first time.

    Because it is unsigned, macOS treats the app as a new identity whenever
    its hash changes, so you may have to re-grant Accessibility after an
    upgrade.

    On an Intel Mac this cask will refuse to install: the .dmg is built for
    Apple Silicon only. Install from PyPI instead, which is architecture
    independent:

        pipx install yazses && yazses quickstart
  EOS
end
