---
title: Running YazSes fully air-gapped
description: Which model files YazSes needs, how to move them to a machine with no network, and how to prove for yourself that nothing tries to phone home.
---

# Running fully air-gapped

YazSes transcribes on-device, so an air-gapped machine is a supported case rather
than a workaround. The only thing that ever needs the network is **fetching a model
once**, and this page shows how to do that elsewhere and carry it across — and how
to verify the claim rather than take it on trust.

!!! info "Verified on"

    Ubuntu 24.04 · Python 3.14 · YazSes 2.18.2 · faster-whisper, int8 CPU. Every
    command below was run there.

## What actually needs the network

| Thing | When | Air-gapped answer |
|---|---|---|
| The Whisper model | first use of each model | copy the cache directory |
| Diarization models | first `--diarize` only | copy the data directory |
| The package itself | install | `pip download` on a connected machine |
| **Anything else** | never | — |

There is no telemetry, no update check on the dictation path, and no cloud
inference. The one place a remote endpoint can be configured — the optional LLM
cleanup — **refuses a non-loopback address** unless you explicitly opt out with
`[filters.disfluency] llm_allow_remote_endpoint`, and the daemon warns on every
start while that is on.

## Step 1 — fetch the models on a connected machine

Install YazSes there, then pull each model you want by using it once:

```bash
yazses transcribe some-recording.wav --model base.en
yazses transcribe --download-models      # only if you want --diarize
```

Confirm where they landed:

```bash
yazses doctor | grep -i "model cache"
```

```
  [OK] Model cache: /home/mohsen/.cache/huggingface/hub
```

```bash
du -sh ~/.cache/huggingface/hub/models--Systran--faster-whisper-base.en
```

```
141M	/home/mohsen/.cache/huggingface/hub/models--Systran--faster-whisper-base.en
```

## Step 2 — carry two directories across

```bash
# on the connected machine
tar czf yazses-models.tar.gz \
    -C ~ .cache/huggingface/hub \
    .local/share/yazses/diarization      # omit if you do not use --diarize
```

```bash
# on the air-gapped machine
tar xzf yazses-models.tar.gz -C ~
```

Sizes, so you can pick media: `tiny.en` 78 MB, `base.en` 148 MB, `small.en` 486 MB
on disk; the diarization pair is about 45 MB.

## Step 3 — install the package without a network

On the connected machine, matching the target's Python version and architecture:

```bash
pip download yazses -d yazses-wheels
```

On the air-gapped machine:

```bash
pip install --no-index --find-links yazses-wheels yazses
```

!!! warning "`evdev` builds from source on Linux"

    It publishes **no wheels at all**, so `pip download` fetches an sdist and the
    target machine needs a compiler and kernel headers — `build-essential
    python3-dev` on Debian/Ubuntu. This catches people out precisely because every
    other dependency is a wheel.

## Step 4 — prove it does not phone home

Do not take this page's word for it. Every model loader asks for a cached snapshot
first and only falls back to downloading if that fails, so setting the hub offline is a
real test rather than a placebo. Note that `HF_HUB_OFFLINE=1` also *disables* that
fallback: with it set, a model that is not already on disk fails instead of being fetched,
which is the behaviour an air-gapped machine wants and the reason this check means
something.

```bash
HF_HUB_OFFLINE=1 python3 -c "
import soundfile as sf, dataclasses
from yazses.config import SttConfig
from yazses.stt.factory import build_engine
eng = build_engine(dataclasses.replace(SttConfig(), model='base.en'))
a, sr = sf.read('clip.wav', dtype='float32')
print(eng.transcribe(a, sr)[:60])"
```

Real output:

```
And so my fellow Americans, ask not what your country can do
```

Stronger, and the one worth doing if it matters to you — watch the syscalls:

```bash
sudo strace -f -e trace=network -o /tmp/net.log yazses transcribe clip.wav
grep -c "connect(" /tmp/net.log
```

Strongest — take the interface down and dictate:

```bash
sudo ip link set <iface> down
yazses restart && yazses status
```

## What to turn off

Nothing on the dictation path reaches out. One optional feature would, if enabled:

```toml
[filters.disfluency]
llm_enabled = false                # or point it at 127.0.0.1 and keep the guard on
```

That is the whole list. There is **no update-check setting to disable**, because
there is no automatic update check: `yazses update` contacts PyPI or the Snap Store
only when you run it, and is never called on your behalf.

## What is not covered here

- **`yazses update` on an air-gapped machine** has no offline path; upgrade by
  repeating step 3 with newer wheels.
- **A genuinely disconnected machine was not used for this page.** The verification
  above was done with the hub forced offline and the model cache in place, which
  exercises the same code path — but nobody unplugged a cable. If you run YazSes on
  a real air-gapped system,
  [tell us what happened](https://github.com/MSKazemi/yazses/issues).
