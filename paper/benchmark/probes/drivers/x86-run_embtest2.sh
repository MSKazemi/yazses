set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/yazses
echo "=== each embedding model at its own plausible threshold range ==="
uv run --group benchmark --extra diarization --extra parakeet --extra moonshine python ~/embmodel_test2.py
