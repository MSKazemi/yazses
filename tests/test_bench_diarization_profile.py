"""A diarization result must name a threshold that something actually ships.

`bench_diarization.py` read `RecimportConfig()` unconditionally. Two features ship
*different* clustering defaults on purpose -- ADR-v2-133 gives `[recimport]` 1.0 and
`[meeting]` 1.2, because arbitrary files and one room with one microphone for forty
minutes are different problems -- and AMI is *the* Meeting Mode corpus. So "DER on AMI
at the shipped default" was measured at a threshold Meeting Mode does not ship, and the
gap is not cosmetic: the same corpus scores 26.71% at 1.2 and 33.58% at 1.0.

It survived because the artifact faithfully recorded `cluster_threshold`, so nothing was
ever *false* -- only measured against the wrong thing, which no guard was looking for.
A stale checkout on a rented VM then made it worse: still on the pre-ADR default of 0.5,
it produced 90% DER and 257 speakers for 4, a number that would have gone into the
archive looking like a regression.

So the profile is selected by *name*, never by a bare float: a caller cannot ask for a
threshold that no feature ships, and the artifact records which feature it stands for.
"""
from __future__ import annotations

import pytest

from tests.benchmark_deps import load

mod = load("bench_diarization", "bench_diarization.py")


def test_both_shipped_profiles_are_offered() -> None:
    assert set(mod.PROFILES) == {"recimport", "meeting"}


def test_each_profile_names_a_real_config_class() -> None:
    """Derived, not restated. A default that moves in `config.py` moves here."""
    import yazses.config as config

    for profile, class_name in mod.PROFILES.items():
        cls = getattr(config, class_name, None)
        assert cls is not None, f"{profile} names {class_name}, which config.py lacks"
        assert hasattr(cls(), "cluster_threshold"), f"{class_name} has no cluster_threshold"


def test_the_two_profiles_really_do_differ() -> None:
    """If they ever converge this whole distinction is dead weight -- but while they
    differ, measuring one corpus under the other is a silent 7-point error."""
    import yazses.config as config

    thresholds = {p: getattr(config, c)().cluster_threshold for p, c in mod.PROFILES.items()}
    assert len(set(thresholds.values())) == len(thresholds), (
        f"the profiles no longer differ ({thresholds}); either ADR-v2-133 was reverted "
        "or this parameter has stopped earning its place"
    )


def test_meeting_is_the_higher_threshold() -> None:
    """Direction, not just difference. ADR-v2-133's whole case is that meeting audio
    needs a *looser* cluster boundary than arbitrary files; a swap would score both
    corpora against the other's tuning and still pass a mere inequality check."""
    import yazses.config as config

    assert (getattr(config, mod.PROFILES["meeting"])().cluster_threshold
            > getattr(config, mod.PROFILES["recimport"])().cluster_threshold)


def test_an_unknown_profile_is_refused_not_defaulted() -> None:
    """Falling back to `recimport` would reintroduce the bug under a typo."""
    with pytest.raises(SystemExit) as exc:
        mod.run(corpus=None, profile="meetings")  # plural: the obvious typo
    assert "meetings" in str(exc.value)
    assert "recimport" in str(exc.value) and "meeting" in str(exc.value)


def test_the_profile_is_refused_before_the_corpus_is_read() -> None:
    """`corpus=None` above only proves the refusal if nothing touched the corpus
    first -- otherwise the test passes on an AttributeError dressed as SystemExit."""
    import inspect

    src = inspect.getsource(mod.run)
    check = src.index("if profile not in PROFILES")
    read = src.index("_read_manifest(corpus)")
    assert check < read, "the profile must be validated before the corpus is opened"


def test_the_result_records_which_profile_it_stands_for() -> None:
    """A threshold alone does not say whether it was the shipped one for that corpus."""
    import inspect

    src = inspect.getsource(mod.run)
    assert '"profile": profile' in src, (
        "run() records cluster_threshold but not the profile it came from; a reader "
        "cannot then tell a shipped default from an arbitrary sweep point"
    )
