# YazSes — offline transcription and diarization in a box (#76).
#
# WHAT THIS IMAGE IS: the headless side of YazSes — `yazses transcribe`, including
# `--diarize`, on a file you mount. No install, no Python environment, no network
# once the models are cached.
#
# WHAT IT IS NOT: hold-to-talk dictation. That needs a microphone, /dev/input and
# keystroke injection into your desktop session; a container is the wrong shape for
# it and pretending otherwise would waste people's time. Install natively for that
# — see https://mskazemi.github.io/yazses/.
#
# Multi-stage so the compilers and wheel caches used to install do not ship. The
# final stage carries the interpreter, the packages, and ffmpeg — nothing else.

# ---- build stage -----------------------------------------------------------
FROM python:3.12-slim AS build

# Version to install. Pinned by CI to the tag being built so the image and the
# release cannot disagree about what is inside it; defaults to the newest release.
ARG YAZSES_VERSION=""

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# `evdev` is a hard Linux dependency of the package (it is how hold-to-talk reads
# the keyboard) and it publishes **no wheels**, so it compiles from source and
# needs a C compiler plus the kernel's input headers. The container never uses it
# — dictation is out of scope here — but pip still has to resolve and build it.
# This is why the image is multi-stage: the toolchain exists only in this stage
# and never reaches the published one.
RUN apt-get update \
    && apt-get install --no-install-recommends -y gcc libc6-dev linux-libc-dev \
    && rm -rf /var/lib/apt/lists/*

# Installed into a virtualenv rather than the system interpreter so the whole
# installation is one directory to copy into the final stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# `diarization` is the extra that makes `--diarize` work (sherpa-onnx int8 ONNX).
# Without it the flag is accepted and silently produces an un-attributed
# transcript, which is exactly the failure this image should not ship with.
RUN if [ -n "$YAZSES_VERSION" ]; then \
        pip install "yazses[diarization]==${YAZSES_VERSION}"; \
    else \
        pip install "yazses[diarization]"; \
    fi

# ---- final stage -----------------------------------------------------------
FROM python:3.12-slim

LABEL org.opencontainers.image.title="YazSes" \
      org.opencontainers.image.description="Offline speech-to-text and speaker diarization. Transcribe a file with no cloud, no account and no network." \
      org.opencontainers.image.url="https://mskazemi.github.io/yazses/" \
      org.opencontainers.image.source="https://github.com/MSKazemi/yazses" \
      org.opencontainers.image.documentation="https://mskazemi.github.io/yazses/docker/" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.authors="Mohsen Seyedkazemi Ardebili <mohsen.seyedkazemi@gmail.com>"

# ffmpeg is the decode fallback for formats PyAV cannot open. It is the only
# system package the transcribe path needs.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Non-root. The container only ever reads a mounted file and writes a transcript
# beside it; nothing here needs root, and a transcription tool running as root
# over a volume the user mounted is an unpleasant surprise.
RUN useradd --create-home --uid 1000 yazses
USER yazses
WORKDIR /data

# Models land here. Mount a named volume (`-v yazses-models:/home/yazses/.cache`)
# and they download once instead of on every run.
ENV XDG_CACHE_HOME=/home/yazses/.cache \
    HF_HOME=/home/yazses/.cache/huggingface

ENTRYPOINT ["yazses"]
CMD ["--help"]
