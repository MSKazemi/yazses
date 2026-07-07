class YazsesV1 < Formula
  desc "Local, offline voice dictation daemon — v1.0 Rust core"
  homepage "https://github.com/MSKazemi/yazses"
  license "MIT"
  version "1.0.0"

  # Replace after CI build — run scripts/patch-release-shas.sh v1.0.0
  on_macos do
    on_arm do
      url "https://github.com/MSKazemi/yazses/releases/download/v#{version}/yazses-v#{version}-aarch64-apple-darwin.tar.gz"
      sha256 "PLACEHOLDER_MACOS_ARM64_SHA256"
    end
    on_intel do
      url "https://github.com/MSKazemi/yazses/releases/download/v#{version}/yazses-v#{version}-x86_64-apple-darwin.tar.gz"
      sha256 "PLACEHOLDER_MACOS_X86_64_SHA256"
    end
  end

  def install
    bin.install "yazses"
    bin.install "yazses-daemon"
  end

  service do
    run          [opt_bin/"yazses-daemon"]
    keep_alive   true
    log_path     var/"log/yazses.log"
    error_log_path var/"log/yazses.log"
  end

  caveats <<~EOS
    YazSes uses macOS's Accessibility API to read hotkeys. After install:

        System Settings → Privacy & Security → Accessibility → YazSes

    On first dictation, macOS will also prompt for Microphone access.

    Default hotkey: Right Option. Config:
        ~/Library/Application Support/yazses/config.toml

    Start the daemon manually or via brew services:
        brew services start yazses-v1

    This is an unsigned build. If macOS blocks launch, open System Settings →
    Privacy & Security → scroll down → "Open Anyway".
  EOS

  test do
    assert_match version.to_s, shell_output("#{bin}/yazses --version")
  end
end
