"""Regression tests for the paper-v2 public manuscript (PAPER2-TEXT-001).

Guards against destructive rewrites: the main entry point must keep all of its
section includes and its structural skeleton intact.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_TEX = REPO_ROOT / "design" / "publication" / "paper-v2" / "manuscript" / "main.tex"

REQUIRED_SECTIONS = [
    "sections/00_abstract",
    "sections/01_introduction",
    "sections/02_research_questions",
    "sections/03_system",
    "sections/04_methodology",
    "sections/05_results_asr",
    "sections/06_results_reproducibility",
    "sections/07_results_platform",
    "sections/08_results_interaction",
    "sections/09_results_meeting",
    "sections/10_discussion",
    "sections/11_threats",
    "sections/12_related_work",
    "sections/13_future_work",
    "sections/14_conclusion",
]

REQUIRED_PREAMBLE = [
    "\\documentclass[10pt]{article}",
    "\\input{macros}",
    "\\bibliographystyle{plainnat}",
    "\\bibliography{references}",
    "\\end{document}",
]


def test_main_tex_exists():
    assert MAIN_TEX.is_file(), "paper-v2 manuscript entry point is missing"


def test_main_tex_includes_all_claim_ledger_sections():
    content = MAIN_TEX.read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert "\\input{%s}" % section in content, "missing section include: %s" % section


def test_main_tex_keeps_preamble_and_ending():
    content = MAIN_TEX.read_text(encoding="utf-8")
    for token in REQUIRED_PREAMBLE:
        assert token in content, "missing manuscript token: %s" % token


def test_main_tex_is_not_gutted():
    lines = MAIN_TEX.read_text(encoding="utf-8").splitlines()
    non_empty = [line for line in lines if line.strip()]
    assert len(non_empty) >= 45, "manuscript was rewritten destructively"
