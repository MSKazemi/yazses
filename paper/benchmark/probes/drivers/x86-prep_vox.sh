set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/vox
if [ ! -d audio ]; then
  echo "[vox] unzipping dev_wav.zip"
  python3 -c "import zipfile,sys; zipfile.ZipFile('dev_wav.zip').extractall('.')" || { echo "[vox] unzip FAILED"; exit 1; }
fi
ls -d ~/vox/*/ | head
mkdir -p ~/vox/rttm
if [ ! -s ~/vox/rttm/.fetched ]; then
  echo "[vox] fetching dev RTTMs"
  curl -fsSL -o /tmp/vox_master.zip \
    https://github.com/joonson/voxconverse/archive/refs/heads/master.zip \
    || { echo "[vox] rttm download FAILED"; exit 1; }
  rm -rf /tmp/voxrepo && mkdir -p /tmp/voxrepo && python3 -c "import zipfile; zipfile.ZipFile('/tmp/vox_master.zip').extractall('/tmp/voxrepo')"
  find /tmp/voxrepo -path "*/dev/*.rttm" -exec cp {} ~/vox/rttm/ \;
  touch ~/vox/rttm/.fetched
fi
echo "[vox] rttm count: $(ls ~/vox/rttm/*.rttm 2>/dev/null | wc -l)"
echo "[vox] wav count:  $(find ~/vox -name '*.wav' | wc -l)"
find ~/vox -name '*.wav' | head -3
echo "PREP_VOX_DONE"
