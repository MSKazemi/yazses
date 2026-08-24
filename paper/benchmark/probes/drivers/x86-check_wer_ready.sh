export PATH="$HOME/.local/bin:$PATH"; cd ~/yazses
echo "=== librispeech present? ==="; ls paper/data/ 2>/dev/null || echo "(absent)"
echo "=== extras ==="
uv run python - <<'PY'
import importlib.util as u
for m in ("onnx_asr", "moonshine_onnx", "faster_whisper", "jiwer", "whisper_normalizer", "scipy"):
    print(f"  {m}: {'yes' if u.find_spec(m) else 'NO'}")
PY
echo "=== cores/mem/disk ==="; nproc; free -g | sed -n 2p; df -h / | tail -1
