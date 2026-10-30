"""YazSes — hosted speech-recognition preview.

READ THIS FIRST, because it matters more than the demo:

    This hosted demo runs on Hugging Face's servers. It is NOT running on your
    machine, and the audio you send here leaves your computer.

    The YazSes desktop app is the opposite: it runs on your own CPU, with no cloud,
    no API key, no account, and no network access after the model is downloaded
    once. This page exists only so you can judge the transcription quality of the
    same engine family before deciding to install it. It does not claim to be the
    desktop app: it does not do desktop-wide hold-to-talk and does not type into
    other applications.

    If privacy is why you are here, do not rely on this page. Install the real app
    and verify it yourself. A normal install can be run with the network disabled:

        docker run --rm --network none -v yazses-models:/home/yazses/.cache \\
            -v "$PWD:/data" ghcr.io/mskazemi/yazses transcribe /data/<your-file>

    https://mskazemi.com/yazses/try-without-installing.html

Privacy of this app itself: the transcribe function is stateless. Nothing it receives
or produces is written to disk, a database, a log or an analytics service, and no
transcript is printed. The only module-level state is the lazily loaded model. The
hosting platform and Gradio's temporary upload cache are outside this file; the cache
is swept by the `delete_cache` setting below.
"""

import os

import gradio as gr
import spaces
from faster_whisper import WhisperModel
from validation import (
    ALLOWED_EXTENSIONS,
    MAX_DURATION_SECONDS,
    MAX_FILE_BYTES,
    check_declared_duration,
    check_duration,
    check_upload,
    container_duration_seconds,
    format_transcript,
    wav_duration_seconds,
)

PAGE_TITLE = "YazSes — Hosted Speech Recognition Preview"

# The decode settings below are what this Space has always run. They are deliberately
# the same engine and model family as the desktop app's defaults; see the README for
# the verified differences (VAD handling, the built-in prompt and post-processing).
MODEL_NAME = "base.en"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"
BEAM_SIZE = 5
VAD_FILTER = True

# Kept on one source line so the sentence is verbatim in the file, as the Space card is.
PRIVACY_SENTENCE = "This is a hosted demonstration. Audio submitted here is processed on Hugging Face infrastructure. For private, offline voice typing, install YazSes on your own computer."
PRIVACY_NOTICE = f"> ⚠️ {PRIVACY_SENTENCE}"

SETTINGS_LINE = (
    f"Model `faster-whisper {MODEL_NAME}` · {DEVICE.upper()} · {COMPUTE_TYPE} · "
    f"beam size {BEAM_SIZE} · voice-activity filter on · "
    f"up to {MAX_DURATION_SECONDS:.0f} seconds and {MAX_FILE_BYTES // (1024 * 1024)} MB"
)

_model = None


def _get_model():
    """Load the model once, on CPU int8 — the same precision the desktop app uses.

    Deliberately not CUDA: this Space runs on ZeroGPU, whose image ships no cuBLAS,
    and CTranslate2 only fails at encode time (RuntimeError: libcublas.so.12 not
    found) long after the model object is constructed, so a try/except around
    construction does not catch it. The GPU decorator on transcribe() exists only
    because ZeroGPU refuses to start a Space without one.
    """
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


@spaces.GPU(duration=60)
def transcribe(audio_path):
    ok, message = check_upload(audio_path)
    if not ok:
        return message
    # The length is read from the file's header before anything is decoded: faster-whisper
    # decodes the whole file into memory before it returns `info.duration`, so a check on
    # that value alone would run after the cost it exists to prevent. A container that does
    # not declare its length is accepted only if the file is small.
    duration = wav_duration_seconds(audio_path)
    if duration is None:
        duration = container_duration_seconds(audio_path)
    ok, message = check_declared_duration(duration, os.path.getsize(audio_path))
    if not ok:
        return message
    try:
        model = _get_model()
    except Exception:  # noqa: BLE001 - the cause is a server-side fault, not user data
        return "The speech model could not be loaded right now. Please try again later."
    try:
        segments, info = model.transcribe(
            audio_path, beam_size=BEAM_SIZE, vad_filter=VAD_FILTER
        )
        # A second, authoritative check on what the decoder actually found.
        ok, message = check_duration(info.duration)
        if not ok:
            return message
        texts = [segment.text for segment in segments]
    except Exception as exc:  # noqa: BLE001 - never show a stack trace or the file path
        # The class name alone says whether the file or the server is at fault, and it
        # carries nothing the visitor submitted.
        return (
            f"This file could not be read as audio ({type(exc).__name__}). Try one of: "
            + ", ".join(sorted(ext.lstrip(".").upper() for ext in ALLOWED_EXTENSIONS))
            + "."
        )
    return format_transcript(texts)


HEADER = """
# YazSes — Hosted Speech Recognition Preview

This page transcribes a file or a recording you give it, using the speech-recognition
engine family that YazSes uses, and shows the text back. It is a preview of
transcription quality only.

The YazSes desktop app is the private, offline product. It runs on your own computer
with no cloud, no API key and no account, and it types the text into whatever app has
focus. This page does neither of those things.
"""

FOOTER = """
### Liked the accuracy?

- **Install the desktop app:** <https://mskazemi.com/yazses/install-linux.html> (Linux; macOS and Windows guides are on the documentation home page <https://mskazemi.com/yazses/>)
- **Try it locally with nothing installed:** <https://mskazemi.com/yazses/try-without-installing.html>
- **Source (Apache-2.0):** <https://github.com/MSKazemi/yazses>
- **Paper:** <https://arxiv.org/abs/2607.28878>

The desktop app also transcribes recordings with speaker labels, and captures whole
meetings into a labelled transcript with locally generated minutes.
"""

with gr.Blocks(
    title=PAGE_TITLE,
    analytics_enabled=False,
    delete_cache=(600, 600),
) as demo:
    gr.Markdown(HEADER)
    gr.Markdown(PRIVACY_NOTICE)
    with gr.Row():
        audio_in = gr.Audio(
            sources=["microphone", "upload"], type="filepath", label="Speak or upload audio"
        )
        text_out = gr.Textbox(label="Transcript", lines=8)
    gr.Markdown(SETTINGS_LINE)
    run = gr.Button("Transcribe", variant="primary")
    run.click(fn=transcribe, inputs=audio_in, outputs=text_out)
    audio_in.stop_recording(fn=transcribe, inputs=audio_in, outputs=text_out)
    gr.Markdown(FOOTER)

demo.queue(max_size=20).launch()
