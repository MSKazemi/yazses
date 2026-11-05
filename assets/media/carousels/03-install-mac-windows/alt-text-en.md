# 03-install-mac-windows — alt text (paste per slide in Instagram → Advanced settings → Accessibility)

01. Install YazSes on macOS and Windows. Developer preview: the builds are not code-signed yet.
02. macOS Apple Silicon: install with Homebrew. Intel Macs: download the x86_64 dmg from GitHub Releases.
03. First run on macOS: the app is not signed yet. On macOS 15 or later use System Settings, Privacy and Security, Open Anyway; on macOS 14 right-click and Open. Then allow Accessibility, Input Monitoring and Microphone.
04. Windows: install with winget. If SmartScreen warns you, click More info, then Run anyway.
05. Check the install on any OS with yazses doctor. It checks mic, hotkey and typing and ends with a verdict.
06. Fallback for other platforms: pipx install yazses. A platform support matrix lists the tested channel per OS.
07. Install once. Then just talk. Docs at mskazemi.com/yazses, code at github.com/MSKazemi/yazses. Free, Apache-2.0, offline. QR code (macOS guide): https://mskazemi.com/yazses/macos-install.html. QR code (Windows guide): https://mskazemi.com/yazses/windows-install.html.
