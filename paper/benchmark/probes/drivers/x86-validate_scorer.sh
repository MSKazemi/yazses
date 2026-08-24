set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~
echo "=== fetch NIST md-eval ==="
curl -fsSL -o md-eval-22.pl https://raw.githubusercontent.com/nryant/dscore/master/scorelib/md-eval-22.pl && echo "md-eval fetched"
perl -c md-eval-22.pl 2>&1 | tail -1
echo "=== isolated pyannote.metrics venv (no torch) ==="
uv venv ~/pmetrics -q 2>&1 | tail -1
uv pip install -q --python ~/pmetrics/bin/python "pyannote.metrics>=4.1" 2>&1 | tail -2
~/pmetrics/bin/python -c "import pyannote.metrics as m; print('pyannote.metrics', m.__version__)"
echo "=== re-score synthetic corpus, dumping hypothesis RTTMs ==="
cd ~/yazses
uv run python paper/benchmark/bench_diarization.py ~/meeting_corpus ~/synth_der2.json --dump-rttm ~/synth_hyp 2>&1 | tail -12
cd ~
cat ~/meeting_corpus/*.rttm > ~/synth_ref_all.rttm
cat ~/synth_hyp/*.rttm     > ~/synth_hyp_all.rttm
echo "ref turns: $(wc -l < ~/synth_ref_all.rttm)  hyp turns: $(wc -l < ~/synth_hyp_all.rttm)"
echo "=== NIST md-eval-22.pl, collar 0 ==="
perl md-eval-22.pl -r ~/synth_ref_all.rttm -s ~/synth_hyp_all.rttm -c 0 2>/dev/null | grep -E "OVERALL SPEAKER DIARIZATION|SCORED SPEAKER TIME|MISSED SPEAKER TIME|FALARM SPEAKER TIME|SPEAKER ERROR TIME|DIARIZATION ERROR" | head -12
echo "=== NIST md-eval-22.pl, collar 0.25 ==="
perl md-eval-22.pl -r ~/synth_ref_all.rttm -s ~/synth_hyp_all.rttm -c 0.25 2>/dev/null | grep -E "DIARIZATION ERROR" | head -3
echo "=== pyannote.metrics, collar 0 ==="
~/pmetrics/bin/python - <<'PY'
from pyannote.metrics.diarization import DiarizationErrorRate
from pyannote.core import Annotation, Segment
import pathlib
def load(p):
    a = Annotation()
    for line in pathlib.Path(p).read_text().splitlines():
        f = line.split()
        if len(f) >= 8 and f[0] == "SPEAKER":
            s = float(f[3]); a[Segment(s, s + float(f[4]))] = f[7]
    return a
metric = DiarizationErrorRate(collar=0.0, skip_overlap=False)
tot = 0.0
import glob, os
for ref in sorted(glob.glob(os.path.expanduser("~/meeting_corpus/*.rttm"))):
    mid = os.path.basename(ref)[:-5]
    hyp = os.path.expanduser(f"~/synth_hyp/{mid}.rttm")
    v = metric(load(ref), load(hyp))
    print(f"  {mid}: DER={v*100:.2f}%")
    tot += v
print(f"pyannote.metrics mean per-file DER = {tot/8*100:.2f}%")
print(f"pyannote.metrics corpus-aggregated DER = {abs(metric)*100:.2f}%")
PY
echo "VALIDATE_DONE"
