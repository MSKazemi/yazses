set -x
export PATH="$HOME/.local/bin:$PATH"
export QT_QPA_PLATFORM=offscreen
cd ~/yazses
uv sync --all-extras 2>&1 | tail -3
uv run pytest tests/ -q -rs > ~/x86_final.log 2>&1
echo "FINAL_EXIT=$?" | tee -a ~/x86_final.log
