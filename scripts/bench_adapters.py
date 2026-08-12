#!/usr/bin/env python3
"""External STT adapters for `bench-stt.py`, so the harness can measure rivals too.

`bench-stt.py` builds its engine through `yazses.stt.factory.build_engine`, which means
it can only ever compare YazSes against itself. That is fine for choosing a default model
and useless as a public comparison: nobody cites a benchmark in which the author is the
only entrant.

These adapters let the same harness, the same corpus and the same machine also measure
other tools, so the published table is a method rather than a claim.

Two rules hold everything together:

**Subprocess only.** A competitor is never imported into this process. Their dependency
trees conflict with each other and with ours, an in-process import would pollute the peak-RSS
measurement that `bench-stt.py` reports, and a crash in their code would take the harness
with it.

**Absence is reported, never faked.** If a tool is not installed, the adapter says so and
the run is skipped. It does not silently substitute a different tool, and it does not
report a zero.

Publish the losses. A benchmark that only ever flatters the author is marketing, and the
citations that make this worth building stop the moment a reader finds one implausible row.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

#: How long any single-file transcription may take before we give up on it. Generous:
#: a large model on a slow CPU is legitimately slow, and killing a real run would put a
#: fabricated gap in the results table.
TIMEOUT_S = 900


@dataclass(frozen=True)
class Adapter:
    """One external tool the harness can measure.

    `argv` and `read_output` are kept as plain functions so the command construction and
    the output parsing can be unit-tested on a machine where the tool is not installed —
    which is every CI runner.
    """

    name: str
    binary: str
    #: What this actually measures, printed with the results. Several of these tools are
    #: not what a reader assumes, and an unlabelled row would be misleading.
    note: str
    argv: Callable[[Path, str, Path], list[str]]
    read_output: Callable[[str, Path], str]

    def available(self) -> bool:
        return shutil.which(self.binary) is not None


def _stdout(stdout: str, _out_dir: Path) -> str:
    return stdout.strip()


def _whisper_cpp_argv(wav: Path, model: str, _out_dir: Path) -> list[str]:
    # -nt drops timestamps, -np drops the progress chatter; what remains on stdout is
    # the transcript. Writing to a file instead would mean guessing its naming scheme,
    # which has changed between releases.
    return ["whisper-cli", "-m", model, "-f", str(wav), "-nt", "-np"]


def _openai_whisper_argv(wav: Path, model: str, out_dir: Path) -> list[str]:
    return [
        "whisper", str(wav),
        "--model", model,
        "--output_format", "txt",
        "--output_dir", str(out_dir),
        "--fp16", "False",
        "--verbose", "False",
    ]


def _read_txt_sidecar(_stdout_text: str, out_dir: Path) -> str:
    """Read the single .txt the tool wrote, rather than trusting its stdout."""
    files = sorted(out_dir.glob("*.txt"))
    if not files:
        raise RuntimeError(f"tool wrote no .txt output into {out_dir}")
    return files[0].read_text(encoding="utf-8").strip()


def _vosk_argv(wav: Path, model: str, _out_dir: Path) -> list[str]:
    argv = ["vosk-transcriber", "-i", str(wav), "-t", "text"]
    if model:
        argv += ["-m", model]
    return argv


ADAPTERS: dict[str, Adapter] = {
    "whisper-cpp": Adapter(
        name="whisper.cpp",
        binary="whisper-cli",
        note="ggml/GGUF model passed via --model; the path, not a name like base.en.",
        argv=_whisper_cpp_argv,
        read_output=_stdout,
    ),
    "openai-whisper": Adapter(
        name="openai-whisper",
        binary="whisper",
        note="The reference PyTorch implementation. Slowest of the three, and the "
             "accuracy figure most other published numbers are quoted against.",
        argv=_openai_whisper_argv,
        read_output=_read_txt_sidecar,
    ),
    "vosk": Adapter(
        name="VOSK",
        binary="vosk-transcriber",
        note="Measured as a stand-in for nerd-dictation, which has no file input at all "
             "— it is a live-microphone tool. VOSK is the engine underneath it, so this "
             "is what determines nerd-dictation's accuracy, but it is NOT a measurement "
             "of nerd-dictation itself and must not be labelled as one.",
        argv=_vosk_argv,
        read_output=_stdout,
    ),
}


class AdapterUnavailable(RuntimeError):
    """The tool is not installed. Raised rather than returning an empty transcript."""


def transcribe(tool: str, wav: Path, model: str = "") -> str:
    """Run `tool` over `wav` in a subprocess and return its transcript.

    Raises `AdapterUnavailable` when the binary is missing, and `RuntimeError` when the
    tool runs but fails — never a silent empty string, which would score as a 100% error
    rate and look like a real result.
    """
    adapter = ADAPTERS.get(tool)
    if adapter is None:
        raise KeyError(f"unknown tool {tool!r}; known: {', '.join(sorted(ADAPTERS))}")
    if not adapter.available():
        raise AdapterUnavailable(
            f"{adapter.name}: `{adapter.binary}` is not on PATH — install it or drop "
            f"--tool {tool} from this run. Skipping is honest; a zero is not."
        )

    with tempfile.TemporaryDirectory(prefix="yazses-bench-") as tmp:
        out_dir = Path(tmp)
        argv = adapter.argv(wav, model, out_dir)
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{adapter.name} exceeded {TIMEOUT_S}s on {wav.name}") from exc
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            raise RuntimeError(f"{adapter.name} failed on {wav.name}: {' / '.join(tail)}")
        return adapter.read_output(proc.stdout, out_dir)


def describe(tool: str) -> str:
    """One line for the results header, so a row is never printed unlabelled."""
    adapter = ADAPTERS[tool]
    return f"{adapter.name} — {adapter.note}"
