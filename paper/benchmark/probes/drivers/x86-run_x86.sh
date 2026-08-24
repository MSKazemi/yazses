set -x
export PATH="$HOME/.local/bin:$PATH"
export QT_QPA_PLATFORM=offscreen
cd ~/yazses
uname -m
uv sync --all-extras 2>&1 | tail -30
echo "=== ALL_EXTRAS_SYNC_EXIT ${PIPESTATUS[0]} ==="
uv pip list 2>/dev/null | wc -l
du -sh .venv
