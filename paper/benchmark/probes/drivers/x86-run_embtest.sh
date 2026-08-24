set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
BASE=~/embtest
REL=https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models
SEG=~/.local/share/yazses/diarization/sherpa-onnx-pyannote-segmentation-3-0.onnx
for f in 3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
         3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx \
         3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx \
         3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx \
         wespeaker_en_voxceleb_CAM++.onnx \
         nemo_en_titanet_small.onnx ; do
  d="$BASE/${f%.onnx}"; mkdir -p "$d"
  cp -n "$SEG" "$d/" 2>/dev/null || true
  if [ ! -s "$d/3dspeaker-eres2net-base.onnx" ]; then
    curl -fsSL -o "$d/3dspeaker-eres2net-base.onnx" "$REL/$f" && echo "staged $f"
  fi
done
cd ~/yazses && uv run python ~/embmodel_test.py
