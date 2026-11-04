"""Right-to-left draft pages must let their body render as Markdown (fa, ar, ur).

`docs/{fa,ar,ur}/index.md` wrap their body in a right-to-left `<div>`. `mkdocs.yml`
enables `md_in_html`, and that extension only parses Markdown inside an HTML block
when the tag carries `markdown="1"`. A bare `<div dir="rtl">` therefore leaves every
heading, table, list and emphasis marker as literal text in the built page: the
Persian page shipped `## نصب` and `|---|---|` as raw characters.

The generator owns these drafts, so the wrapper is fixed in `render()`. This module
pins that: it checks what the generator produces and what is shipped on disk, and it
fails if any RTL wrapper in the docs tree is missing `markdown="1"`.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DOCS = ROOT / "docs"

#: Any `<div dir="rtl" ...>` opening tag, in any attribute order.
RTL_DIV = re.compile(r"<div\b[^>]*\bdir=\"rtl\"[^>]*>")
MARKDOWN_ON = re.compile(r'\bmarkdown="1"')


def _load_generator():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "gen_readme_translation", SCRIPTS / "gen-readme-translation.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_readme_translation"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()

RTL_LOCALES = sorted(code for code, spec in gen.LOCALES.items() if spec.get("rtl"))


def _unmarked_rtl_wrappers(text: str) -> list[str]:
    return [tag for tag in RTL_DIV.findall(text) if not MARKDOWN_ON.search(tag)]


def test_rtl_locales_are_the_three_expected() -> None:
    # Guards the parametrisation below: if the RTL set changes, this says so.
    assert RTL_LOCALES == ["ar", "fa", "ur"]


@pytest.mark.parametrize("code", RTL_LOCALES)
def test_generated_rtl_page_wraps_body_with_markdown_on(code: str) -> None:
    text = gen.render(code, gen.LOCALES[code], gen.TABLE_SOURCE_SHA)
    tags = RTL_DIV.findall(text)
    assert tags, f"{code}: generator emits no dir=\"rtl\" wrapper at all"
    assert _unmarked_rtl_wrappers(text) == [], (
        f"{code}: RTL wrapper without markdown=\"1\" would render its body as raw "
        f"Markdown text: {_unmarked_rtl_wrappers(text)}"
    )


@pytest.mark.parametrize("code", RTL_LOCALES)
def test_shipped_rtl_page_wraps_body_with_markdown_on(code: str) -> None:
    page = DOCS / code / "index.md"
    text = page.read_text(encoding="utf-8")
    assert RTL_DIV.search(text), f"{page}: no dir=\"rtl\" wrapper"
    assert _unmarked_rtl_wrappers(text) == [], (
        f"{page.relative_to(ROOT)} wraps its body in an RTL div without markdown=\"1\""
    )


def test_no_docs_page_has_an_rtl_div_without_markdown() -> None:
    offenders = []
    for page in sorted(DOCS.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        for tag in _unmarked_rtl_wrappers(text):
            offenders.append(f"{page.relative_to(ROOT)}: {tag}")
    assert offenders == []
