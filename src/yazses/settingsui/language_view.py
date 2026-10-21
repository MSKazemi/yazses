"""The Settings window's language-profile row, as a Qt-free view-model (#497).

`app.py` used to format the profile choices, the staged-change hint and the
"prepare language profile?" question itself, inline in Qt slots. That is the one
part of a profile switch a user actually reads, and it could only be tested by
building a window, which most test environments cannot (no PySide6). It also
hard-coded the profile list, so a profile added to `yazses.language.profiles`
would appear in `yazses language list` and never in Settings.

Everything here is a pure function of the *same* `PreparedLanguageChange` the CLI
previews and the shared service applies, so the window, `yazses language set
--dry-run` and the commit cannot describe three different switches. No I/O, no Qt,
no optional dependency: importing this module costs what `yazses.language` costs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yazses.language.service import LanguageRequirements, PreparedLanguageChange

#: The combo-box entry that hands the low-level model/language pickers back.
CUSTOM_LABEL = "Custom / advanced"


def profile_choices() -> tuple[tuple[str, str], ...]:
    """``(label, profile id)`` rows for the profile combo box, custom first.

    Derived from the profile registry so Settings offers exactly what
    `yazses language list` lists. The empty id means "no profile owns the speech
    settings"; it is not a profile.
    """

    from yazses.language import list_profiles

    return ((CUSTOM_LABEL, ""), *((p.label, p.id) for p in list_profiles()))


def preparation_jobs(requirements: "LanguageRequirements") -> tuple[str, ...]:
    """The one-time local work a switch needs before its config can be written."""

    jobs: list[str] = []
    if requirements.missing_imports:
        jobs.append("install " + " ".join(requirements.packages))
    if not requirements.model_cached:
        jobs.append(f"download speech model {requirements.model}")
    return tuple(jobs)


def preview_hint(prepared: "PreparedLanguageChange") -> str:
    """The staged-change line shown under the Speech group. Writes nothing."""

    plan = prepared.plan
    changes = ", ".join(
        f"{m.key}: {m.before!r} → {m.after!r}" for m in plan.mutations
    ) or "no config-key changes"
    parts = [f"Language profile {plan.canonical_profile} staged — {changes}."]
    if plan.command_language_after and (
        plan.command_language_after != plan.command_language_before
    ):
        parts.append(
            f"Spoken commands follow: {plan.command_language_before or 'none'} → "
            f"{plan.command_language_after}."
        )
    parts.extend(f"Note: {warning}" for warning in plan.warnings)
    jobs = preparation_jobs(prepared.requirements)
    if jobs:
        parts.append("One-time preparation: " + "; ".join(jobs) + ".")
    parts.append("Nothing changes until Apply.")
    return " ".join(parts)


def confirmation_message(prepared: "PreparedLanguageChange") -> str | None:
    """The question to ask before spending bandwidth, or ``None`` if nothing to fetch."""

    jobs = preparation_jobs(prepared.requirements)
    if not jobs:
        return None
    return (
        f"Switching to {prepared.plan.canonical_profile} needs a one-time "
        + " and ".join(jobs)
        + ".\n\nThe existing config will not be changed unless all prerequisites "
        "are ready. Continue?"
    )
