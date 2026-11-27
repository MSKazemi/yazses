"""What the File transcription page runs and where the text lands. Pure beside the disk.

The window runs ``yazses transcribe`` as a child process rather than importing the decoder:
the speech model never loads into the window, and Cancel is simply ending the process.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yazses.recimport.render import VALID_FORMATS
from yazses.system.relaunch import Mode, command_for

_PREVIEW_LIMIT = 200_000
_FAILURE_LINES = 6
_FAILURE_CHARS = 600


@dataclass(frozen=True)
class Job:
    source: Path
    fmt: str = "txt"
    model: str = ""            # "" = the configured model
    speakers: bool = False
    count: int = 0             # 0 = detect; used only with ``speakers``
    translate: bool = False


def output_path(job: Job) -> Path:
    """The sidecar beside the source (``talk.mp3`` → ``talk.txt``), never the source."""
    source = job.source.resolve()
    out = source.with_suffix(f".{job.fmt}")
    return out if out != source else source.with_name(f"{source.name}.{job.fmt}")


def command(job: Job) -> list[str]:
    """The argv for *job*. A list, never a shell string; the source is made absolute."""
    if job.fmt not in VALID_FORMATS:
        raise ValueError(f"Unknown format {job.fmt!r}.")
    args = [
        "transcribe", str(job.source.resolve()), "--format", job.fmt,
        "--out", str(output_path(job)),
        "--diarize" if job.speakers else "--no-diarize",
    ]
    if job.speakers and job.count > 0:
        args += ["--speakers", str(job.count)]
    if job.model:
        args += ["--model", job.model]
    if job.translate:
        args += ["--language", "translate"]
    return command_for(Mode.CLI, *args)


def notes(stderr: str) -> str:
    """The warnings a successful run printed: no speaker labels, no speech, and so on."""
    return "\n".join(
        line.strip() for line in stderr.splitlines() if line.strip().startswith("Note:")
    )


def failure_text(stderr: str) -> str:
    """The end of what the command said, which is where it explains itself."""
    lines = [line.rstrip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return "Transcription failed without a message."
    return "\n".join(lines[-_FAILURE_LINES:])[-_FAILURE_CHARS:]


def preview(path: Path) -> str:
    """The start of a written transcript. Never raises."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(_PREVIEW_LIMIT + 1)
    except OSError as exc:
        return f"The transcript could not be read: {exc}"
    if len(text) > _PREVIEW_LIMIT:
        return text[:_PREVIEW_LIMIT] + "\n\n[Preview ends here. Open the file for the rest.]"
    return text
