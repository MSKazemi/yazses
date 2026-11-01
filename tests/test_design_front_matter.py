"""Front-matter on the published design tier must parse and must survive being a meta tag.

`tests/test_docs_frontmatter.py` guards `docs/`. The design tier (`design/`) is published
into the same site by `hooks/design_tier.py` and is indexed by search engines — four of its
pages are the only ones, apart from the home page, that have earned Google clicks — but it
had no such guard. Two failures are silent there and both leave the build green:

* front-matter that is not valid YAML is not an error to MkDocs; the block is rendered as
  visible page text and the page ships with the site-wide default description;
* MkDocs writes `description:` into `<meta name=description content="...">` unescaped, so a
  double quote closes the attribute early and the snippet is cut mid-sentence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

DESIGN = Path(__file__).resolve().parent.parent / "design"


def _front_matter(path: Path) -> tuple[bool, dict]:
    """(has_block, parsed). A block that fails to parse raises, so the test names the file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return False, {}
    end = text.find("\n---", 4)
    if end == -1:
        return False, {}
    loaded = yaml.safe_load(text[4:end])
    return True, loaded if isinstance(loaded, dict) else {}


def _pages() -> list[Path]:
    return sorted(DESIGN.rglob("*.md"))


def test_there_are_pages_to_check():
    """Guard the guard: a walk that silently finds nothing would pass forever."""
    assert len(_pages()) >= 100
    assert sum(1 for p in _pages() if _front_matter(p)[0]) >= 10


@pytest.mark.parametrize("path", _pages(), ids=lambda p: p.relative_to(DESIGN).as_posix())
def test_front_matter_parses_and_description_is_attribute_safe(path: Path):
    has_block, meta = _front_matter(path)
    if not has_block:
        return
    description = meta.get("description")
    if description is None:
        return
    assert isinstance(description, str) and description.strip(), f"{path}: empty description"
    assert '"' not in description, (
        f"{path}: a double quote in `description` ends the <meta> attribute early"
    )
