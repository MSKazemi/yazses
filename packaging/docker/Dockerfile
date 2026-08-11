# YazSes — offline transcription in a container.
#
# SCOPE, honestly: this image runs the *file → text* side of YazSes
# (`yazses transcribe`). It is a way to hear how good the on-device
# transcription is before you install anything on your machine.
#
# It deliberately does NOT do hold-to-talk dictation. Dictation needs the
# host's microphone, the kernel input device for the hotkey, and the ability to
# inject keystrokes into the focused window — three things a container is the
# wrong shape for. Install YazSes natively for dictation:
#   https://mskazemi.com/yazses/install-linux.html
#
# Build:
#   docker build -f packaging/docker/Dockerfile -t yazses .
#
# Run (model is cached in a named volume so it downloads once):
#   docker run --rm -v yazses-models:/models -v "$PWD:/data" yazses meeting.m4a
#
# ---------------------------------------------------------------------------
# Stage 1 — build. `evdev` publishes an sdist and no wheels at all, so it is
# compiled from C source and needs a toolchain plus the Python headers. None of
# that has to reach the runtime image.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS build

ARG YAZSES_VERSION=

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# PySide6 is a base dependency because the voice-activity overlay ships in the
# default install. The overlay is a desktop feature and cannot run here, so it
# is excluded to keep the image roughly a gigabyte smaller. Transcription never
# imports it.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir "yazses${YAZSES_VERSION:+==$YAZSES_VERSION}" \
 && pip uninstall -y PySide6 PySide6-Addons PySide6-Essentials shiboken6 || true

# ---------------------------------------------------------------------------
# Stage 2 — runtime.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

LABEL org.opencontainers.image.title="YazSes" \
      org.opencontainers.image.description="Offline, on-device speech-to-text — transcribe audio and video files with no cloud, no API key, no subscription." \
      org.opencontainers.image.url="https://mskazemi.com/yazses/" \
      org.opencontainers.image.source="https://github.com/MSKazemi/yazses" \
      org.opencontainers.image.licenses="Apache-2.0"

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Keep the Whisper model outside the image so the image stays small and the
# model survives `docker run --rm`. Mount a volume at /models to cache it.
ENV HF_HOME=/models \
    XDG_CACHE_HOME=/models

# Transcription is pure CPU maths; one thread per core is not always a win and
# unbounded threads hurt on small machines. Callers can override.
ENV OMP_NUM_THREADS=4

RUN useradd --create-home --uid 1000 yazses \
 && mkdir -p /models /data \
 && chown yazses:yazses /models /data
USER yazses
WORKDIR /data

ENTRYPOINT ["yazses", "transcribe"]
CMD ["--help"]
