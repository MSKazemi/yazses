"""Is the shipped speaker-embedding model the reason clustering fails on English?

`recimport/download.py` fetches `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k`
-- a speaker-verification model trained on Mandarin (3D-Speaker) -- and YazSes is an
English-first product whose Meeting Mode defaults to `language = "en"`. The same
sherpa-onnx release ships an English sibling of the same architecture and size.

This isolates the model: same audio, same segmentation, same clustering threshold,
only the embedding extractor changes. `model_dir` is config-driven and the embedding
filename is fixed, so each candidate goes in its own directory under that name and no
YazSes code changes.
"""
import json, os, pathlib, sys, time
sys.path.insert(0, os.path.expanduser("~/yazses/paper/benchmark"))
import bench_diarization as bd
from yazses.config import RecimportConfig
from yazses.recimport.diarizer import SherpaDiarizer

CORPUS = pathlib.Path(os.path.expanduser("~/ami_one"))
MID = "IS1009a"
BASE = pathlib.Path(os.path.expanduser("~/embtest"))

CANDIDATES = [
    ("shipped: eres2net zh-cn", "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"),
    ("eres2net EN voxceleb",    "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"),
    ("campplus EN voxceleb",    "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"),
    ("campplus zh+en advanced", "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"),
    ("wespeaker EN CAM++",      "wespeaker_en_voxceleb_CAM++.onnx"),
    ("nemo EN titanet_small",   "nemo_en_titanet_small.onnx"),
]

ref = bd.read_rttm(CORPUS / f"{MID}.rttm")
audio = bd._load_wav(CORPUS / f"{MID}.wav")
rows = []
for label, fname in CANDIDATES:
    d = BASE / fname.replace(".onnx", "")
    if not (d / "3dspeaker-eres2net-base.onnx").exists():
        print(f"[skip] {label}: model not staged in {d}", flush=True)
        continue
    row = {"model": label, "file": fname}
    for thr in (1.0, 1.2, 1.4, 1.6):
        cfg = RecimportConfig()
        cfg = type(cfg)(**{**cfg.__dict__, "model_dir": str(d), "cluster_threshold": thr})
        t0 = time.monotonic()
        turns = SherpaDiarizer(cfg).diarize(audio, 16000)
        hyp = [(t.start, t.end, t.speaker) for t in turns]
        got = bd.score(ref, hyp, 0.0)
        row[f"thr{thr}"] = {"der": got["der"], "spk": got["n_hyp_speakers"],
                            "conf": got["confusion_pct"], "s": round(time.monotonic() - t0, 1)}
        print(f"  {label:26s} thr={thr}  DER={got['der']:6.2f}%  "
              f"speakers={got['n_hyp_speakers']:4d}/4  conf={got['confusion_pct']:.1f}%",
              flush=True)
    rows.append(row)

pathlib.Path(os.path.expanduser("~/embmodel_test2.json")).write_text(
    json.dumps({"meeting": MID, "true_speakers": 4, "results": rows}, indent=2))
print("EMB_TEST_DONE")
