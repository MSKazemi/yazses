"""The paper-v2 manuscript must still resolve as a document (PAPER2-TEXT-001, #532).

The draft is edited section by section by several people, and a LaTeX source that no longer
builds gives no warning in this repository: nothing here runs LaTeX. These checks read the
files and catch the three breakages that cost a rebuild to find, without a hand-written list
of section names: that list would go stale the first time a section is added, renamed or
merged, and fail on a legitimate edit.

- every `\\input` in `main.tex` points at a file that exists;
- every file under `sections/` is pulled in by `main.tex`, so none is silently left out;
- every citation key used in the manuscript is defined in the `.bib` file it loads.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANUSCRIPT = ROOT / "design" / "publication" / "paper-v2" / "manuscript"
MAIN_TEX = MANUSCRIPT / "main.tex"

_INPUT = re.compile(r"\\input\{([^}]+)\}")
_BIBLIOGRAPHY = re.compile(r"\\bibliography\{([^}]+)\}")
_CITE = re.compile(r"\\[A-Za-z]*cite[A-Za-z]*\*?(?:\[[^\]]*\])*\{([^}]+)\}")
_BIB_KEY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")


def _source(path: Path) -> str:
    """A `.tex` file's text with `%` comments removed (an escaped `\\%` is kept)."""
    text = path.read_text(encoding="utf-8")
    return "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in text.splitlines())


def _tex_path(name: str) -> Path:
    return MANUSCRIPT / (name if name.endswith(".tex") else f"{name}.tex")


def _inputs() -> list[str]:
    return _INPUT.findall(_source(MAIN_TEX))


def test_main_tex_exists():
    assert MAIN_TEX.is_file(), "paper-v2 manuscript entry point is missing"


def test_every_input_in_main_tex_exists():
    inputs = _inputs()
    # Guard the guard: a regex that matched nothing would make the loop below vacuous.
    assert inputs, "main.tex has no \\input lines; the entry point was emptied or the pattern broke"
    missing = [name for name in inputs if not _tex_path(name).is_file()]
    assert not missing, f"main.tex includes files that do not exist: {missing}"


def test_every_section_file_is_included_by_main_tex():
    sections = sorted(p.relative_to(MANUSCRIPT).with_suffix("").as_posix()
                      for p in (MANUSCRIPT / "sections").glob("*.tex"))
    assert sections, "no section files found under the manuscript's sections/ directory"
    included = {name.removesuffix(".tex") for name in _inputs()}
    orphans = [name for name in sections if name not in included]
    assert not orphans, f"section files that main.tex never includes: {orphans}"


def test_every_citation_key_is_defined_in_the_bibliography():
    main = _source(MAIN_TEX)
    stems = [stem for group in _BIBLIOGRAPHY.findall(main) for stem in group.split(",")]
    assert stems, "main.tex loads no bibliography"
    defined: set[str] = set()
    for stem in stems:
        bib = MANUSCRIPT / f"{stem.strip()}.bib"
        assert bib.is_file(), f"main.tex loads a bibliography that does not exist: {bib.name}"
        defined |= set(_BIB_KEY.findall(bib.read_text(encoding="utf-8")))

    sources = [MAIN_TEX, *(_tex_path(name) for name in _inputs() if _tex_path(name).is_file())]
    cited = {
        key.strip()
        for path in sources
        for group in _CITE.findall(_source(path))
        for key in group.split(",")
    }
    assert cited, "no citation found in the manuscript; the pattern is wrong or the text is gone"
    undefined = sorted(cited - defined)
    assert not undefined, f"cited but not defined in the .bib file: {undefined}"
