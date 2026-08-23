#!/usr/bin/env python3
"""Synthesise a multi-speaker meeting corpus with **exact** diarization ground truth.

Meeting Mode's speaker separation has never been scored (`docs/benchmarks.md` says
so). The reason is not indifference: the two standard corpora cannot be committed
here. AMI is CC-BY but 100+ GB, and VoxConverse's audio is pulled from YouTube under
terms that forbid redistribution. So a maintainer can measure DER once on a laptop
and the project still carries no regression fixture -- the number ages out the moment
someone touches `recimport/diarizer.py`.

A synthesised corpus fixes exactly that, and it is *better* ground truth than either
of them for the thing being measured. In AMI and VoxConverse the turn boundaries are
human annotations, so they carry annotator error and a forgiveness collar is required
to compare against them at all. Here the renderer **places** each turn, so it knows
the boundaries to the sample. The RTTM is not an estimate of the truth; it is the
instruction the mixer was given.

What this does NOT claim: synthetic TTS speech is not a substitute for real meeting
audio. Neural voices are cleaner, better separated, and never talk over each other by
accident, so an absolute DER measured here will be **optimistic** against a real
room. It is a regression fixture and a floor -- if the diarizer cannot separate eight
distinctly-voiced speakers in clean audio, it certainly cannot separate a real
meeting. Read the number as "did this get worse", never as "this is the DER".

Maintainer tooling, and it lives in `scripts/` for a load-bearing reason: it calls
Azure. `tests/test_egress_inventory.py` scans `src/yazses/` and asserts the set of
modules touching the network equals a declared allowlist, so an Azure call under
`src/yazses/` fails three tests whose message says a change to the project's central
privacy claim needs an ADR, not a test edit. Nothing here is imported by the daemon;
the output is inert data. Same exemption `scripts/research-watch.py` runs under.

Usage (credentials come from the environment; nothing is read from a config file):

    export AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=westeurope
    export AZURE_OPENAI_ENDPOINT=https://<name>.openai.azure.com/
    export AZURE_OPENAI_KEY=... AZURE_OPENAI_DEPLOYMENT=gpt-4o
    uv run python scripts/gen-meeting-corpus.py --out tests/fixtures/meeting --meetings 6

Every generated meeting is reviewed before commit. A model-authored corpus nobody
prunes is the failure mode `tests/test_research_digest_is_curated.py` already exists
to prevent.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.error
import urllib.request
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

SAMPLE_RATE = 16000  # what `recimport.audio_io.load_audio` hands the diarizer

# Deliberately distinct accents and both genders. A corpus of eight voices from one
# locale would measure how well the diarizer separates near-identical embeddings,
# which is a harder and *different* question than the one Meeting Mode asks.
VOICES = [
    "en-US-AndrewNeural", "en-GB-SoniaNeural", "en-AU-NatashaNeural",
    "en-US-EmmaNeural", "en-IN-PrabhatNeural", "en-CA-LiamNeural",
    "en-US-BrianNeural", "en-GB-LibbyNeural",
]

_DIALOGUE_PROMPT = """Write a realistic transcript of a short {n_speakers}-person \
work meeting about: {topic}.

Rules:
- {n_turns} turns total, strictly alternating is NOT required -- real meetings have \
one person speaking twice in a row.
- Turn lengths must vary a lot: some one-word ("Right.", "Agreed."), some 3-4 sentences.
- Natural spoken English: contractions, mid-sentence pivots, the occasional filler.
- No stage directions, no speaker descriptions, no markdown.

Return ONLY JSON: {{"speakers": ["Name1", ...], "turns": [{{"speaker": "Name1", \
"text": "..."}}]}}"""

TOPICS = [
    "a slipping release date and who owns the fix",
    "choosing between two database migration strategies",
    "a customer escalation about data privacy",
    "quarterly hiring plan and headcount trade-offs",
    "postmortem of an outage nobody noticed for six hours",
    "whether to open-source an internal tool",
    "budget cuts and which projects get paused",
    "onboarding is taking three weeks and should take three days",
]


@dataclass(frozen=True)
class Turn:
    """One placed turn. Times are seconds into the mixed track, exact by construction."""
    speaker: str
    voice: str
    text: str
    start: float
    end: float


def _post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        # Azure puts the actionable part in the body, not the status line: an F0
        # Speech resource over its monthly character allowance answers 429 with a
        # quota message, which reads nothing like a transient rate limit.
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise SystemExit(f"{url} -> HTTP {exc.code}\n{detail}") from exc


def write_dialogue(topic: str, n_speakers: int, n_turns: int) -> dict:
    """Ask the configured Azure OpenAI deployment for one meeting script."""
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    url = (f"{endpoint}/openai/deployments/{deployment}/chat/completions"
           f"?api-version=2024-10-21")
    payload = {
        "messages": [{
            "role": "user",
            "content": _DIALOGUE_PROMPT.format(
                topic=topic, n_speakers=n_speakers, n_turns=n_turns),
        }],
        "response_format": {"type": "json_object"},
    }
    raw = _post(url, json.dumps(payload).encode(),
                {"Content-Type": "application/json",
                 "api-key": os.environ["AZURE_OPENAI_KEY"]})
    content = json.loads(raw)["choices"][0]["message"]["content"]
    return json.loads(content)


def synthesize(text: str, voice: str) -> bytes:
    """Render *text* in *voice*; returns raw 16 kHz mono 16-bit PCM (no header)."""
    region = os.environ.get("AZURE_SPEECH_REGION", "westeurope")
    ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xml:lang="en-US"><voice name="{voice}">'
            f'{_xml_escape(text)}</voice></speak>')
    return _post(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        ssml.encode("utf-8"),
        {"Content-Type": "application/ssml+xml",
         # `raw` rather than a container: the mixer concatenates samples, and a
         # RIFF header every 40 turns would land in the middle of the audio.
         "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
         "Ocp-Apim-Subscription-Key": os.environ["AZURE_SPEECH_KEY"],
         "User-Agent": "yazses-corpus-gen"},
    )


def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_meeting(script: dict, rng: random.Random, overlap_prob: float) -> tuple[bytes, list[Turn]]:
    """Render every turn and lay them out on one timeline, returning exact boundaries."""
    speakers = script["speakers"]
    voices = {name: VOICES[i % len(VOICES)] for i, name in enumerate(speakers)}

    track = bytearray()
    turns: list[Turn] = []
    for item in script["turns"]:
        name = item["speaker"]
        if name not in voices:  # the model occasionally invents a ninth attendee
            voices[name] = VOICES[len(voices) % len(VOICES)]
        pcm = synthesize(item["text"], voices[name])
        dur = len(pcm) / 2 / SAMPLE_RATE

        # Where this turn begins. A real meeting is mostly gaps with occasional
        # barge-in, so model both -- a corpus of clean non-overlapping turns would
        # not exercise the case diarization actually gets wrong.
        if turns and rng.random() < overlap_prob:
            back = min(rng.uniform(0.15, 0.6), (turns[-1].end - turns[-1].start) * 0.5)
            start = max(0.0, turns[-1].end - back)
        else:
            start = (turns[-1].end if turns else 0.0) + rng.uniform(0.15, 0.9)

        off = int(start * SAMPLE_RATE) * 2
        if off + len(pcm) > len(track):
            track.extend(b"\x00" * (off + len(pcm) - len(track)))
        _mix_into(track, pcm, off)
        turns.append(Turn(name, voices[name], item["text"], round(start, 3),
                          round(start + dur, 3)))
    return bytes(track), turns


def _mix_into(track: bytearray, pcm: bytes, offset: int) -> None:
    """Add *pcm* into *track* at byte *offset*, saturating rather than wrapping.

    Plain addition of two int16 streams wraps on overflow, which turns an overlap --
    the one region this corpus exists to contain -- into a burst of clipping noise
    that no diarizer could ever attribute. Saturation keeps it audible speech.
    """
    for i in range(0, len(pcm), 2):
        j = offset + i
        a = int.from_bytes(track[j:j + 2], "little", signed=True)
        b = int.from_bytes(pcm[i:i + 2], "little", signed=True)
        s = max(-32768, min(32767, a + b))
        track[j:j + 2] = s.to_bytes(2, "little", signed=True)


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)


def write_rttm(path: Path, meeting_id: str, turns: list[Turn]) -> None:
    """NIST RTTM, the format every diarization scorer (pyannote, dscore) reads."""
    with path.open("w", encoding="utf-8") as fh:
        for t in turns:
            fh.write(f"SPEAKER {meeting_id} 1 {t.start:.3f} {t.end - t.start:.3f} "
                     f"<NA> <NA> {t.speaker} <NA> <NA>\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--meetings", type=int, default=6)
    ap.add_argument("--turns", type=int, default=24)
    ap.add_argument("--overlap-prob", type=float, default=0.18,
                    help="fraction of turns that barge in on the previous one")
    # Seeded so a regenerated corpus is the same corpus: a fixture that changes
    # every run cannot show a regression, only noise.
    ap.add_argument("--seed", type=int, default=20260823)
    args = ap.parse_args()

    for var in ("AZURE_SPEECH_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY"):
        if not os.environ.get(var):
            print(f"error: ${var} is not set (see the module docstring)",
                  file=sys.stderr)
            return 2

    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    manifest = []
    for i in range(args.meetings):
        # 2..6 speakers: below 2 there is nothing to diarize, and above ~6 the
        # limit being measured is the voice inventory rather than the diarizer.
        n_spk = 2 + (i % 5)
        topic = TOPICS[i % len(TOPICS)]
        mid = f"meeting{i:02d}"
        print(f"[{mid}] {n_spk} speakers, {args.turns} turns -- {topic}", flush=True)
        script = write_dialogue(topic, n_spk, args.turns)
        pcm, turns = build_meeting(script, rng, args.overlap_prob)
        write_wav(args.out / f"{mid}.wav", pcm)
        write_rttm(args.out / f"{mid}.rttm", mid, turns)
        manifest.append({
            "id": mid, "topic": topic,
            "n_speakers": len({t.speaker for t in turns}),
            "n_turns": len(turns),
            "duration_s": round(len(pcm) / 2 / SAMPLE_RATE, 2),
            "voices": sorted({t.voice for t in turns}),
            "turns": [asdict(t) for t in turns],
        })
        print(f"[{mid}] {manifest[-1]['duration_s']}s, "
              f"{manifest[-1]['n_speakers']} speakers", flush=True)

    (args.out / "manifest.json").write_text(
        json.dumps({
            "generator": "scripts/gen-meeting-corpus.py",
            "sample_rate": SAMPLE_RATE,
            "seed": args.seed,
            "overlap_prob": args.overlap_prob,
            "tts": "Azure Speech neural TTS",
            "ground_truth": "exact by construction -- the mixer placed every turn",
            "caveat": "clean synthetic speech; DER here is a floor, not a real-room figure",
            "meetings": manifest,
        }, indent=2) + "\n", encoding="utf-8")
    total = sum(m["duration_s"] for m in manifest)
    print(f"\n{len(manifest)} meetings, {total / 60:.1f} min total -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
