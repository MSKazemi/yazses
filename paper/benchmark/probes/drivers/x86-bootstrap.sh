#!/usr/bin/env bash
# Prepare an Azure VM to run the YazSes suite. Mirrors the apt list in
# .github/workflows/test.yml so a difference in results is the architecture,
# not the box.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq \
  build-essential cmake pkg-config git curl \
  libportaudio2 portaudio19-dev \
  desktop-file-utils xdotool xvfb \
  ffmpeg libsndfile1 \
  libegl1 libgl1 libxkbcommon-x11-0 libdbus-1-3 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-cursor0 \
  >/dev/null
curl -LsSf https://astral.sh/uv/install.sh | sh
echo "=== bootstrap done: $(uname -m) ==="
