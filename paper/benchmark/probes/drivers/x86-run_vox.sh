set -uo pipefail
PY=~/yazses/.venv/bin/python
cd ~/yazses
# wait for the audio to finish downloading and unpack it
while pgrep -f "fetch_vox2" >/dev/null 2>&1; do sleep 30; done
cd ~/vox
if ! $PY -c "import zipfile; zipfile.ZipFile('dev_wav.zip')" 2>/dev/null; then
  echo "[vox] dev_wav.zip is still not a complete zip -- aborting"; exit 1
fi
if [ -z "$(find ~/vox -name '*.wav' -print -quit)" ]; then
  echo "[vox] extracting"
  $PY -c "import zipfile; zipfile.ZipFile('dev_wav.zip').extractall('.')"
fi
WAVROOT=$(find ~/vox -name '*.wav' -printf '%h\n' | sort -u | head -1)
echo "[vox] wav dir: $WAVROOT ($(ls "$WAVROOT"/*.wav | wc -l) files)"
echo "[vox] rttm dir: ~/vox/rttm ($(ls ~/vox/rttm/*.rttm | wc -l) files)"
cd ~/yazses
$PY paper/benchmark/make_corpus.py voxconverse "$WAVROOT" ~/vox/rttm ~/vox_corpus 45 || exit 1
echo "=== VoxConverse: does 1.2 generalise off AMI? ==="
$PY paper/benchmark/bench_diarization.py ~/vox_corpus ~/vox_sweep.json \
  --sweep --thresholds 0.5,0.7,0.9,1.0,1.1,1.2,1.3,1.4,1.6
echo "VOX_DONE"
