set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/yazses
echo "=== the mitigation a user has today: tell it how many people were in the room ==="
echo "max_speakers is an EXACT cluster count on the sherpa backend, so 4 means 4."
uv run --group benchmark --extra diarization --extra parakeet --extra moonshine python paper/benchmark/bench_diarization.py ~/ami_corpus ~/ami_maxspk4.json --max-speakers 4
echo "MAXSPK_DONE"
