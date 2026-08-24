set -euo pipefail
mkdir -p ~/vox && cd ~/vox
echo "[vox] audio ..."
curl -fL --retry 3 -C - -o dev_wav.zip https://mm.kaist.ac.kr/datasets/voxconverse/data/voxconverse_dev_wav.zip
echo "[vox] rttm ..."
curl -fL --retry 3 -o vox_repo.zip https://codeload.github.com/joonson/voxconverse/zip/refs/heads/master
echo "[vox] unzip ..."
unzip -q -o dev_wav.zip -d wav_root
unzip -q -o vox_repo.zip -d repo_root
echo "[vox] layout:"
find wav_root -name '*.wav' | wc -l
find repo_root -name '*.rttm' | head -3
find repo_root -path '*dev*' -name '*.rttm' | wc -l
du -sh ~/vox
echo "[vox] DONE"
