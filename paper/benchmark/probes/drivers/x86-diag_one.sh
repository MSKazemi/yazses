set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~
# One meeting only: the shortest AMI test recording, so the diagnostic is cheap.
rm -rf ~/ami_one && mkdir -p ~/ami_one
cp ~/ami_corpus/IS1009a.wav ~/ami_corpus/IS1009a.rttm ~/ami_one/
python3 - <<'PY'
import json, pathlib
src = json.loads(pathlib.Path.home().joinpath("ami_corpus/manifest.json").read_text())
one = dict(src)
one["meetings"] = [m for m in src["meetings"] if m["id"] == "IS1009a"]
pathlib.Path.home().joinpath("ami_one/manifest.json").write_text(json.dumps(one, indent=2))
print("one-meeting corpus:", one["meetings"])
PY
cd ~/yazses
uv run python paper/benchmark/bench_diarization.py ~/ami_one ~/ami_one_der.json --dump-rttm ~/ami_one_hyp
echo "=== cluster anatomy ==="
python3 - <<'PY'
import collections, pathlib
hyp = pathlib.Path.home() / "ami_one_hyp" / "IS1009a.rttm"
ref = pathlib.Path.home() / "ami_one" / "IS1009a.rttm"
def load(p):
    out=[]
    for line in p.read_text().splitlines():
        f=line.split()
        if len(f)>=8 and f[0]=="SPEAKER": out.append((float(f[3]), float(f[4]), f[7]))
    return out
h, r = load(hyp), load(ref)
print(f"reference : {len(r)} turns, {len({s for _,_,s in r})} speakers, "
      f"{sum(d for _,d,_ in r):.0f}s speech")
print(f"hypothesis: {len(h)} turns, {len({s for _,_,s in h})} speakers, "
      f"{sum(d for _,d,_ in h):.0f}s speech")
tot = collections.Counter()
for _, d, s in h: tot[s] += d
durs = sorted(d for _, d, _ in h)
import statistics
print(f"turn duration: min={durs[0]:.2f}s median={statistics.median(durs):.2f}s max={durs[-1]:.2f}s")
for cut in (0.5, 1.0, 2.0):
    n = sum(1 for d in durs if d < cut)
    print(f"  turns shorter than {cut}s: {n}/{len(durs)} ({n/len(durs)*100:.0f}%)")
for cut in (1.0, 3.0, 5.0):
    n = sum(1 for v in tot.values() if v < cut)
    print(f"  clusters with < {cut}s TOTAL speech: {n}/{len(tot)} ({n/len(tot)*100:.0f}%)")
print("  top 6 clusters by total speech:",
      [f"{s}={v:.0f}s" for s, v in tot.most_common(6)])
print(f"  speech in the 4 largest clusters: "
      f"{sum(v for _,v in tot.most_common(4))/sum(tot.values())*100:.0f}% of hypothesis speech")
PY
echo "DIAG_DONE"
