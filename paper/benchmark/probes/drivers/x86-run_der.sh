set -x
export PATH="$HOME/.local/bin:$PATH"
cd ~/yazses
uv run yazses transcribe --download-models 2>&1 | tail -6
uv run python paper/benchmark/bench_diarization.py ~/meeting_corpus ~/der.json
