cask "yazses" do
  version "0.2.0"
  sha256 "c6c967eb80b75f0047008f5f8571994ba9236541b6627a1ffed4b27153eb879d"

  url "https://github.com/MSKazemi/yazses/releases/download/v#{version}/YazSes-#{version}.dmg",
      verified: "github.com/MSKazemi/yazses/"
  name "YazSes"
  desc "Local, offline voice dictation — hold a key, speak, release"
  homepage "https://github.com/MSKazemi/yazses"

  # livecheck do
  #   url :url
  #   strategy :github_latest
  # end

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
