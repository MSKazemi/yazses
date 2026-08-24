#!/bin/bash
# Fetch the FULL AMI test split (16 meetings). The 4-meeting result is one meeting
# per room; this is the split published numbers are quoted on.
set -uo pipefail
mkdir -p ~/ami16/wav ~/ami16/rttm
ALL="EN2002a EN2002b EN2002c EN2002d ES2004a ES2004b ES2004c ES2004d IS1009a IS1009b IS1009c IS1009d TS3003a TS3003b TS3003c TS3003d"
for m in $ALL; do
  if [ ! -s ~/ami16/rttm/$m.rttm ]; then
    curl -fsSL --retry 5 -o ~/ami16/rttm/$m.rttm \
      "https://raw.githubusercontent.com/pyannote/AMI-diarization-setup/main/only_words/rttms/test/$m.rttm" \
      || { echo "RTTM FAILED $m"; continue; }
  fi
  if [ ! -s ~/ami16/wav/$m.wav ]; then
    curl -fL --retry 5 -C - -o ~/ami16/wav/$m.wav \
      "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/$m/audio/$m.Mix-Headset.wav" \
      || { echo "WAV FAILED $m"; continue; }
  fi
  echo "[ami16] $m $(du -h ~/ami16/wav/$m.wav | cut -f1)"
done
echo "[ami16] rttm=$(ls ~/ami16/rttm | wc -l) wav=$(ls ~/ami16/wav | wc -l)"
du -sh ~/ami16
echo "AMI16_FETCH_DONE"
