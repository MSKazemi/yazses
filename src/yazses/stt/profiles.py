"""Speech profiles -- ``fast`` / ``balanced`` / ``accurate`` -- and a hardware pick (#930).

Pure: no probe, no config read, no download. A caller passes the :class:`Machine` it measured
and the ``[stt]`` values it loaded; :func:`recommend` answers with a model name and the
reasons, and changes nothing.

**Every figure in** :data:`PROFILES` **is copied from** ``docs/benchmarks.md`` and
``tests/test_speech_profiles.py`` fails when the two disagree. They describe the English-only
checkpoints, each measured on one machine. No decode time is carried here: the committed
latency figures come from different machines and that page says not to mix them.

The pick uses installed RAM only, following the table in
``docs/how-to/low-ram-models.md``. The CPU count is reported and never decides: the
committed measurements do not compare the three models across core counts, so a rule on it
would be a guess. ``accurate`` is not picked for English dictation; on the benchmark laptop
``small.en`` was the slowest of the three by a wide margin. ADR-036 (Proposed) records this.
"""
from __future__ import annotations

from dataclasses import dataclass

from yazses.language.capability import check, normalise_language, resolve_engine
from yazses.language.profiles import list_profiles

__all__ = [
    "PROFILES",
    "RAM_FAST_BELOW_GB",
    "MIN_TIMED_CPUS",
    "SpeechProfile",
    "Machine",
    "Recommendation",
    "get_profile",
    "model_for",
    "recommend",
]

#: Below this much installed RAM the pick is ``fast``. It sits between the low-RAM guide's
#: "2 GB: tiny.en" and "4 GB: base.en" rows, so a machine sold as 4 GB that reports a little
#: less keeps the default.
RAM_FAST_BELOW_GB = 3.0

#: The fewest logical CPUs behind any timing in ``docs/benchmarks.md``.
MIN_TIMED_CPUS = 4


@dataclass(frozen=True)
class SpeechProfile:
    id: str
    #: Checkpoint when ``[stt] language`` is English.
    english_model: str
    #: Checkpoint for any other language, and for auto-detect.
    multilingual_model: str
    #: The next three describe ``english_model`` only.
    disk_mb: int
    #: LibriSpeech ``test-clean`` word error rate, percent.
    wer_pct: float
    #: Peak resident memory of a process that imported the daemon, loaded the model and
    #: decoded an 11 s clip (re-measured 2026-10-21; the upper figure where two are given).
    peak_rss_mb: int
    summary: str


PROFILES: tuple[SpeechProfile, ...] = (
    SpeechProfile("fast", "tiny.en", "tiny", 78, 4.82, 272,
                  "smallest and quickest to decode; the most word errors"),
    SpeechProfile("balanced", "base.en", "base", 148, 4.07, 344,
                  "the shipped default"),
    SpeechProfile("accurate", "small.en", "small", 486, 2.59, 618,
                  "fewest word errors; the longest wait"),
)


@dataclass(frozen=True)
class Machine:
    """What a probe read. ``None`` means the OS would not say, never zero."""

    ram_gb: float | None = None
    logical_cpus: int | None = None


@dataclass(frozen=True)
class Recommendation:
    #: None when no profile applies (another engine, or a language none of them covers).
    profile: SpeechProfile | None
    model: str | None
    #: The normalised language the pick is for; "" is auto-detect.
    language: str
    reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def get_profile(profile_id: str) -> SpeechProfile:
    """The profile named *profile_id*; ``KeyError`` for any other name."""
    for profile in PROFILES:
        if profile.id == profile_id:
            return profile
    raise KeyError(profile_id)


def model_for(profile: SpeechProfile, language: str | None) -> str:
    """The checkpoint *profile* means for *language* (``[stt] language`` as written)."""
    if normalise_language(language) == "en":
        return profile.english_model
    return profile.multilingual_model


def _language_baseline(language: str) -> str:
    """The model ``yazses language`` already recommends for *language*, or ""."""
    for entry in list_profiles():
        if entry.speech_language == language:
            return entry.recommended_model
    return ""


def recommend(
    machine: Machine,
    *,
    engine: str | None = "faster-whisper",
    language: str | None = "en",
) -> Recommendation:
    """Which profile suits *machine*, given the configured engine and language."""
    lang = normalise_language(language)
    resolved = resolve_engine(engine)
    if resolved != "faster-whisper":
        return Recommendation(
            None, None, lang,
            (f"The profiles are faster-whisper checkpoints and [stt] engine is "
             f"{resolved!r}, so nothing is suggested.",),
        )

    ram = machine.ram_gb
    baseline = "" if lang == "en" else _language_baseline(lang)
    baseline_profile = next((p for p in PROFILES if p.multilingual_model == baseline), None)
    reasons: list[str] = []
    notes: list[str] = []

    if ram is not None and ram < RAM_FAST_BELOW_GB:
        profile = get_profile("fast")
        reasons.append(
            f"{ram:g} GB of RAM is installed, under {RAM_FAST_BELOW_GB:g} GB. The low-RAM "
            "guide picks the tiny checkpoint for a 2 GB machine and the base one from 4 GB. "
            "That advice is arithmetic on measured footprints, not a test on small hardware."
        )
        if baseline_profile is not None and baseline_profile != profile:
            notes.append(
                f"`yazses language list` gives {baseline!r} as the baseline for {lang!r}; "
                "it needs more memory than this suggestion."
            )
    elif baseline_profile is not None:
        profile = baseline_profile
        reasons.append(
            f"`yazses language list` gives {baseline!r} as the baseline for {lang!r}."
        )
    else:
        profile = get_profile("balanced")
        if ram is None:
            reasons.append(
                "Installed RAM could not be read, so the default size is suggested."
            )
        else:
            reasons.append(f"{ram:g} GB of RAM is installed, enough for the default size.")
        if lang == "en":
            notes.append(
                "'accurate' is not suggested for dictation: on the benchmark laptop it was "
                "the slowest of the three by a wide margin. Consider it for files and "
                "meetings, or if word errors bother you more than the wait."
            )

    model = model_for(profile, language)
    support = check(resolved, model, lang)
    if support.verdict == "unsupported":
        return Recommendation(None, None, lang, (support.reason,))

    if lang != "en":
        notes.append(
            f"No accuracy or memory figure is shown for {model!r}: the ones carried here "
            "are for the English-only checkpoints."
        )
    cpus = machine.logical_cpus
    if cpus is not None and cpus < MIN_TIMED_CPUS:
        notes.append(
            f"No timing in the benchmarks was measured with fewer than {MIN_TIMED_CPUS} "
            f"logical CPUs and this machine has {cpus}; judge the wait by trying it."
        )
    notes.append(
        "The CPU count does not change the suggestion: decode times for these models were "
        "not compared across core counts. After a few dictations `yazses status` shows "
        "this machine's own decode times."
    )
    return Recommendation(profile, model, lang, tuple(reasons), tuple(notes))
