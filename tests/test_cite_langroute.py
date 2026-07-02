"""Citation-by-Voice (ADR-v2-071) + Per-Language Auto Switching (ADR-v2-072) — pure cores."""
from __future__ import annotations

from yazses.cite.library import Entry, format_citation, parse_bibtex, resolve_citation
from yazses.langroute.route import LangRegistry, ModelChoice, route_language

BIB = """
@article{vaswani2017,
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki},
  title = {Attention Is All You Need},
  year = {2017}
}
@inproceedings{devlin2019,
  author = {Devlin, Jacob},
  title = "BERT Pretraining",
  year = {2019}
}
"""


# ---- citations -------------------------------------------------------------

def test_parse_bibtex():
    entries = parse_bibtex(BIB)
    assert len(entries) == 2
    v = entries[0]
    assert v.key == "vaswani2017" and v.year == "2017"
    assert "Vaswani" in v.authors and v.title == "Attention Is All You Need"
    assert entries[1].title == "BERT Pretraining"   # quoted-value field


def test_resolve_citation_by_author_year():
    entries = parse_bibtex(BIB)
    assert resolve_citation("cite Vaswani 2017", entries).key == "vaswani2017"
    assert resolve_citation("reference Devlin", entries).key == "devlin2019"   # surname alone resolves
    assert resolve_citation("cite Devlin 2019", entries).key == "devlin2019"


def test_resolve_citation_no_match():
    entries = parse_bibtex(BIB)
    assert resolve_citation("cite Nobody 1999", entries) is None


def test_format_citation_styles():
    v = parse_bibtex(BIB)[0]
    assert format_citation(v, "latex") == r"\cite{vaswani2017}"
    assert format_citation(v, "plain") == "Vaswani et al. (2017)"
    d = parse_bibtex(BIB)[1]
    assert format_citation(d, "apa") == "Devlin (2019)"


def test_format_citation_empty_authors():
    e = Entry(key="misc2020", authors="", year="2020")
    assert format_citation(e, "plain") == "misc2020 (2020)"   # falls back to key


def test_resolve_title_word_alone_is_weak():
    entries = parse_bibtex(BIB)
    # a title word alone scores +1, below the threshold → no confident match
    assert resolve_citation("cite attention", entries) is None


# ---- language routing ------------------------------------------------------

def _registry():
    return LangRegistry(
        default_model="base.en",
        default_itn="en",
        models={"fr": "distil-fr", "de": "distil-de"},
        itn={"fr": "fr", "de": "de"},
        min_confidence=0.5,
    )


def test_route_known_language():
    choice = route_language("fr", 0.9, _registry())
    assert choice == ModelChoice("fr", "distil-fr", "fr")


def test_route_low_confidence_falls_back():
    choice = route_language("fr", 0.2, _registry())
    assert choice.model == "base.en" and choice.language == "fr"


def test_route_unknown_language_uses_default():
    choice = route_language("es", 0.99, _registry())
    assert choice.model == "base.en" and choice.itn == "en"


def test_route_blank_language():
    choice = route_language("", 0.99, _registry())
    assert choice.language == "und" and choice.model == "base.en"


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "cite" in slugs and "langroute" in slugs
    assert Config().cite.enabled is False and Config().langroute.enabled is False
