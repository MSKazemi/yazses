"""What a file-transcription decoder is built with, from the config. Pure.

One function answers "which model, language, device and precision does this file get
decoded with?" for every path that transcribes a file rather than a held key:
``yazses transcribe``, ``yazses meeting recover``, the meeting post-pass when it has no
engine of its own, and the MCP server's ``transcribe`` tool.

It exists because each of those used to answer the question for itself, and they
drifted:

* the MCP tool passed the **whole** ``Config`` where the ``[recimport]`` section belongs.
  ``getattr`` on the wrong object returns the default rather than failing, so every call
  decoded ``small.en`` in English whatever the user had configured;
* the pipeline's builder fell back to a hard-coded ``small.en`` instead of inheriting
  ``[stt] model``, which is what ``[recimport]``/``[meeting] model = ""`` documents -- so
  ``meeting recover`` decoded with a model nobody chose;
* none of them passed ``[stt] device`` or ``[stt] compute_type``, so a user on
  ``float32`` (a CPU that rejects ``int8``) or ``cuda`` got the default on every file.

The two inputs are typed and checked: a whole ``Config`` in either slot raises
``TypeError`` rather than being read as a section, because that substitution is
exactly the one that produced a plausible, wrong answer instead of an error.

Dependency-free beyond ``stt.download``'s pure name rules, so it is tested directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yazses.stt.download import language_model_problem

if TYPE_CHECKING:
    from yazses.config import MeetingConfig, RecimportConfig, SttConfig

#: The model a file decode falls back to when nothing usable is configured. The same
#: checkpoint the daemon's factory falls back to, so a default install transcribes a
#: file with the model it already has on disk rather than downloading a second one.
DEFAULT_MODEL = "base.en"


@dataclass(frozen=True)
class DecoderSettings:
    """Everything a Whisper decoder for one file is constructed with.

    ``language`` is what the decoder is pinned to (``""`` = auto-detect); ``task`` is
    ``"translate"`` when the section asked for X->English, which also forces
    auto-detection of the source. ``chinese_script`` and ``persian_normalisation`` are
    carried so the output wrappers read the *file's* model and language rather than the
    dictation ones. ``problems`` are human-readable warnings for the caller to log;
    building them here keeps this function free of side effects.
    """

    model: str
    language: str
    task: str | None
    device: str
    compute_type: str
    cpu_threads: int
    beam_size: int
    condition_on_previous_text: bool
    chinese_script: str
    persian_normalisation: bool
    problems: tuple[str, ...] = ()


def _is_whole_config(obj: object) -> bool:
    # Structural rather than `isinstance(obj, Config)`: importing `Config` here would
    # make this module load the whole config package, and a duck-typed whole config
    # (a test double, a future wrapper) is the same mistake.
    return hasattr(obj, "stt") and hasattr(obj, "recimport")


def require_section(section: object, caller: str) -> None:
    """Raise ``TypeError`` when *section* is the whole ``Config`` rather than a section.

    Every field a file decode reads is read with a default, so the whole ``Config``
    where ``[recimport]`` belongs raises nothing on its own: it decodes the fallback
    model in English, never diarizes, and looks like it worked. That is how the MCP
    ``transcribe`` tool shipped, so the substitution is refused at every entry point.
    """
    if _is_whole_config(section):
        raise TypeError(
            f"{caller}() was given the whole Config; pass the [recimport] or [meeting] "
            "section (e.g. cfg.recimport) and the [stt] section as stt=cfg.stt"
        )


def _foreign_checkpoint(model: str) -> bool:
    """Whether *model* names another engine's checkpoint, which Whisper cannot load.

    `[stt] model` may hold a Parakeet or Moonshine name when `[stt] engine` selects one.
    The file path is Whisper-only (it needs per-word timings), so inheriting such a name
    would fail to load rather than transcribe. Same names those engines recognise.
    """
    m = model.strip().lower()
    return "parakeet" in m or m.startswith("moonshine")


def file_decoder_settings(
    stt: SttConfig | None,
    section: RecimportConfig | MeetingConfig,
) -> DecoderSettings:
    """The decoder settings for transcribing a file under *section*.

    *stt* is the ``[stt]`` section (``None`` = its defaults): device, precision, threads,
    beam, conditioning, the Han script and the Persian opt-in come from it, and so does
    the model when the section leaves ``model`` empty. *section* is ``[recimport]`` or
    ``[meeting]``: its ``language`` is authoritative (``""`` auto-detects,
    ``"translate"`` renders into English) and a non-empty ``model`` overrides ``[stt]``.
    """
    require_section(section, "file_decoder_settings")
    if stt is not None and _is_whole_config(stt):
        raise TypeError(
            "file_decoder_settings() was given the whole Config as [stt]; pass cfg.stt"
        )

    problems: list[str] = []
    explicit = str(getattr(section, "model", "") or "").strip()
    inherited = str(getattr(stt, "model", "") or "").strip()
    if explicit:
        model = explicit
    elif inherited and _foreign_checkpoint(inherited):
        problems.append(
            f"[stt] model {inherited!r} is not a Whisper checkpoint, and file "
            f"transcription decodes with Whisper -- using {DEFAULT_MODEL!r}. Set "
            "[recimport] model (or [meeting] model) to choose another."
        )
        model = DEFAULT_MODEL
    else:
        model = inherited or DEFAULT_MODEL

    wish = str(getattr(section, "language", "en") or "").strip()
    task = "translate" if wish == "translate" else None
    language = "" if task else wish
    # An `.en` checkpoint has no language tokens, so it answers foreign speech with
    # fluent English nonsense rather than an error. Same rule as the daemon's factory.
    if problem := language_model_problem(model, language):
        problems.append(problem)

    return DecoderSettings(
        model=model,
        language=language,
        task=task,
        device=str(getattr(stt, "device", "cpu") or "cpu"),
        compute_type=str(getattr(stt, "compute_type", "int8") or "int8"),
        cpu_threads=int(getattr(stt, "cpu_threads", 0) or 0),
        beam_size=int(getattr(stt, "beam_size", 0) or 0),
        condition_on_previous_text=bool(getattr(stt, "condition_on_previous_text", True)),
        chinese_script=str(getattr(stt, "chinese_script", "") or ""),
        persian_normalisation=bool(getattr(stt, "persian_normalisation", False)),
        problems=tuple(problems),
    )
