"""Tests for the Markdown-mirror docs hook (``hooks/markdown_mirrors.py``).

The hook's value is entirely in two side effects — a `.md` twin on disk and a
`<link rel="alternate">` in the head — and both are silent when they fail. A
build stays green whether or not a single mirror was written, so without these
tests a refactor could disable the machine-readable surface with no signal.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

_HOOK = Path(__file__).resolve().parents[1] / "hooks" / "markdown_mirrors.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("markdown_mirrors", _HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["markdown_mirrors"] = module
    spec.loader.exec_module(module)
    return module


hook = _load_hook()


def _page(tmp_path: Path, markdown: str, name: str = "guide"):
    dest = tmp_path / f"{name}.html"
    return SimpleNamespace(
        markdown=markdown,
        file=SimpleNamespace(src_uri=f"{name}.md", abs_dest_path=str(dest)),
    )


HTML = "<html><head><title>x</title></head><body>y</body></html>"


def test_writes_markdown_twin_next_to_the_html(tmp_path: Path) -> None:
    page = _page(tmp_path, "# Title\n\nBody text.\n")

    hook.on_post_page(HTML, page=page)

    twin = tmp_path / "guide.md"
    assert twin.exists()
    assert twin.read_text(encoding="utf-8") == "# Title\n\nBody text.\n"


def test_front_matter_is_stripped_from_the_twin(tmp_path: Path) -> None:
    """Front matter is build metadata; a machine reader should get content."""
    page = _page(tmp_path, "---\ntitle: T\ndescription: D\n---\n# Title\n\nBody.\n")

    hook.on_post_page(HTML, page=page)

    twin_text = (tmp_path / "guide.md").read_text(encoding="utf-8")
    assert twin_text.startswith("# Title")
    assert "description:" not in twin_text


def test_head_advertises_the_twin(tmp_path: Path) -> None:
    out = hook.on_post_page(HTML, page=_page(tmp_path, "# T\n"))

    assert '<link rel="alternate" type="text/markdown" href="guide.md">' in out
    # Injected inside the head, not appended to the document.
    assert out.index("alternate") < out.index("</head>")


def test_link_is_not_duplicated_if_already_present(tmp_path: Path) -> None:
    once = hook.on_post_page(HTML, page=_page(tmp_path, "# T\n"))
    twice = hook.on_post_page(once, page=_page(tmp_path, "# T\n"))

    assert twice.count('type="text/markdown"') == 1


def test_page_without_markdown_is_passed_through(tmp_path: Path) -> None:
    page = _page(tmp_path, "")

    assert hook.on_post_page(HTML, page=page) == HTML
    assert not (tmp_path / "guide.md").exists()


def test_unwritable_destination_does_not_break_the_build(tmp_path: Path) -> None:
    """A docs build must never fail because one mirror could not be written."""
    page = SimpleNamespace(
        markdown="# T\n",
        file=SimpleNamespace(
            src_uri="guide.md",
            # A path whose parent is an existing *file* — mkdir will raise.
            abs_dest_path=str(tmp_path / "blocker" / "guide.html"),
        ),
    )
    (tmp_path / "blocker").write_text("not a directory", encoding="utf-8")

    assert hook.on_post_page(HTML, page=page) == HTML
