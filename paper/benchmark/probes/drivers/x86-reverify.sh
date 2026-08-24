set -x
export PATH="$HOME/.local/bin:$PATH"
export QT_QPA_PLATFORM=offscreen
cd ~/yazses
rm -rf .venv
uv sync --all-extras 2>&1 | tail -4
echo "=== SYNC_EXIT ${PIPESTATUS[0]} ==="
uv run python -c "import setuptools;print(\"setuptools\",setuptools.__version__)"
uv run python -c "import pkg_resources;print(\"pkg_resources present\")"
uv run python -c "from resemblyzer import VoiceEncoder; print(\"RESEMBLYZER IMPORTS OK\")"
uv run pytest tests/ -q -rs > ~/x86_reverify.log 2>&1
echo "REVERIFY_EXIT=$?" | tee -a ~/x86_reverify.log
