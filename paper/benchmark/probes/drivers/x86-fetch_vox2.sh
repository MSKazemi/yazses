set -uo pipefail
cd ~/vox
echo "[vox] resuming from $(stat -c%s dev_wav.zip) bytes"
curl -fL --retry 5 --retry-delay 10 -C - -o dev_wav.zip \
  https://mm.kaist.ac.kr/datasets/voxconverse/data/voxconverse_dev_wav.zip 2>/dev/null
echo "[vox] final size $(stat -c%s dev_wav.zip)"
python3 -c "
import zipfile
z = zipfile.ZipFile('dev_wav.zip')
print('[vox] zip ok, members:', len(z.namelist()))
" || { echo "[vox] STILL TRUNCATED"; exit 1; }
echo "FETCH_VOX_DONE"
