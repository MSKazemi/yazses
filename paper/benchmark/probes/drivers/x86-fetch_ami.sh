set -euo pipefail
M="EN2002a EN2002b EN2002c EN2002d ES2004a ES2004b ES2004c ES2004d IS1009a IS1009b IS1009c IS1009d TS3003a TS3003b TS3003c TS3003d"
mkdir -p ~/ami/wav ~/ami/rttm && cd ~/ami
for m in $M; do
  if [ ! -s "wav/$m.wav" ]; then
    curl -fsSL --retry 3 -o "wav/$m.wav" \
      "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/$m/audio/$m.Mix-Headset.wav"
  fi
  curl -fsSL --retry 3 -o "rttm/$m.rttm" \
    "https://raw.githubusercontent.com/pyannote/AMI-diarization-setup/main/only_words/rttms/test/$m.rttm"
  echo "[ami] $m $(stat -c%s wav/$m.wav) bytes"
done
du -sh ~/ami
echo "[ami] DONE"
