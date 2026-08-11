# THIS is the canonical Homebrew artefact for YazSes. The two other .rb files in
# this directory (`yazses-formula.rb`, `yazses-v1.rb`) describe an abandoned v1.0
# Rust binary distribution whose releases were never published — see the header
# comments in those files. Do not publish them.
#
# The sha256 below was computed from the released asset itself:
#   gh release download v2.17.0 -p 'YazSes-2.17.0.dmg' && sha256sum YazSes-2.17.0.dmg
cask "yazses" do
  version "2.17.0"
  sha256 "24d0bc187d669eb0c885b6f4d9ac923a5480a15bd2072ddbe999655aacbaad34"

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
  EOS
end
