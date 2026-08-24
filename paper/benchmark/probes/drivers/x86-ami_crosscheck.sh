set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/yazses
while pgrep -f "run_wer_vm|repro_check" >/dev/null 2>&1; do sleep 30; done
REF=~/ami_corpus/IS1009a.rttm
HYP=~/ami_one_hyp/IS1009a.rttm
echo "=== independent scoring of the AMI hypothesis (IS1009a, shipped defaults) ==="
echo "--- NIST md-eval-22.pl, collar 0, overlap scored ---"
perl ~/md-eval-22.pl -c 0 -r "$REF" -s "$HYP" 2>/dev/null | grep -E "OVERALL|SCORED SPEAKER|MISSED SPEAKER|FALARM SPEAKER|SPEAKER ERROR" | head -20
echo "--- NIST md-eval-22.pl, collar 0.25 ---"
perl ~/md-eval-22.pl -c 0.25 -r "$REF" -s "$HYP" 2>/dev/null | grep -E "OVERALL SPEAKER DIARIZATION ERROR" | head -5
echo "--- pyannote.metrics 4.1 ---"
~/pmetrics/bin/python - "$REF" "$HYP" <<'PY'
import sys
from pyannote.database.util import load_rttm
from pyannote.metrics.diarization import DiarizationErrorRate
ref = list(load_rttm(sys.argv[1]).values())[0]
hyp = list(load_rttm(sys.argv[2]).values())[0]
for collar in (0.0, 0.25):
    m = DiarizationErrorRate(collar=collar, skip_overlap=False)
    v = m(ref, hyp, detailed=True)
    print(f"collar={collar}  DER={100*v['diarization error rate']:.2f}%  "
          f"miss={100*v['missed detection']/v['total']:.2f}%  "
          f"fa={100*v['false alarm']/v['total']:.2f}%  "
          f"conf={100*v['confusion']/v['total']:.2f}%")
print("ref speakers:", len(ref.labels()), " hyp speakers:", len(hyp.labels()))
PY
echo "=== done ==="
