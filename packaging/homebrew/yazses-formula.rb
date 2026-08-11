# ⚠ DEAD — DO NOT PUBLISH THIS FILE.
#
# This describes the abandoned v1.0 "Rust core" binary distribution. Verified
# 2026-08-11: the GitHub releases it points at (v1.0.0 / v1.0.0-dev.1) were
# NEVER PUBLISHED — `gh release view v1.0.0` returns "release not found" — and
# every sha256 below is still a PLACEHOLDER. YazSes today is a Python project
# at v2.17.0 whose macOS artefact is a .dmg, not a tarball of Rust binaries.
#
# The canonical, current, publishable Homebrew artefact is the cask in
# `yazses.rb` beside this file. Kept only as history.
#
# Homebrew formula for the YazSes v1.0 Rust CLI + daemon.
# Lives at https://github.com/MSKazemi/homebrew-tap as Formula/yazses.rb
# The v0.4 macOS .dmg cask is in Casks/yazses.rb (existing).

class Yazses < Formula
  desc "Local, offline hold-to-talk voice dictation — agentic OS layer (v1.0 Rust core)"
  homepage "https://github.com/MSKazemi/yazses"
  version "1.0.0-dev.1"
  license "Apache-2.0"

  on_macos do
    if Hardware::CPU.arm?
      url "https://github.com/MSKazemi/yazses/releases/download/v#{version}/yazses-v#{version}-aarch64-apple-darwin.tar.gz"
      sha256 "PLACEHOLDER_AARCH64_MACOS_SHA256"
    else
      url "https://github.com/MSKazemi/yazses/releases/download/v#{version}/yazses-v#{version}-x86_64-apple-darwin.tar.gz"
      sha256 "PLACEHOLDER_X86_64_MACOS_SHA256"
    end
  end

  on_linux do
    if Hardware::CPU.arm? && Hardware::CPU.is_64_bit?
      url "https://github.com/MSKazemi/yazses/releases/download/v#{version}/yazses-v#{version}-aarch64-unknown-linux-gnu.tar.gz"
      sha256 "PLACEHOLDER_AARCH64_LINUX_SHA256"
    else
      url "https://github.com/MSKazemi/yazses/releases/download/v#{version}/yazses-v#{version}-x86_64-unknown-linux-gnu.tar.gz"
      sha256 "PLACEHOLDER_X86_64_LINUX_SHA256"
    end
  end

  def install
    bin.install "yazses"
    bin.install "yazses-daemon"
  end

  def caveats
    <<~EOS
      YazSes requires microphone and keyboard-capture permissions.

      macOS: grant Accessibility in System Settings → Privacy & Security →
             Accessibility, then start the daemon: yazses start

      Linux: sudo usermod -aG input $USER && log out
             then: yazses start

      Default hold-key: Right Alt (Linux) / Right Option (macOS).
      Config: ~/.config/yazses/config.toml

      Run `yazses doctor` to verify your setup.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/yazses --version")
  end
end
