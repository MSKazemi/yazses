"""Emit a Markdown twin of every page, and link it from the HTML.

AI crawlers and coding agents fetch pages with zero JavaScript and pay for every
token of navigation chrome, cookie banners and theme markup they have to read
past. A Material-for-MkDocs page is mostly chrome by byte count, so the useful
content arrives diluted.

Two things are true about how crawlers actually behave, and they point the same
way. First, `llms.txt` is largely ignored — no major crawler has committed to
reading it, so a single index file is not a delivery mechanism. Second, crawlers
*do* fetch dedicated `.md` URLs when a page advertises one, and prefer them:
the Markdown twin of a docs page is roughly 80% smaller than its HTML and
contains no boilerplate at all.

So this hook does the thing that works rather than the thing that is fashionable:
for every built page it writes `<page>.md` next to `<page>.html`, and adds

    <link rel="alternate" type="text/markdown" href="…​.md">

to the HTML head so the twin is discoverable rather than merely present. The
source markdown is copied verbatim apart from its YAML front matter, which is
build metadata rather than content.

This is deliberately *not* a replacement for the HTML: humans and search-index
crawlers keep getting the real page. It is a cheaper parallel surface for the
machine audience, which for a developer-tools project is a large fraction of the
readership.

`docs/llms.txt` is retained separately — it costs nothing and a few agents do
read it — but this hook is the load-bearing part.

Registered via `hooks:` in mkdocs.yml.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Strip a leading YAML front-matter block (title/description used by the theme).
# It is build metadata: repeating it in the Markdown twin would have the machine
# reader parse a header that says the same thing as the H1 immediately below it.
_FRONT_MATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)

# Injected immediately before </head>. Kept on one line so the minify plugin has
# nothing to reflow.
_LINK_TAG = '<link rel="alternate" type="text/markdown" href="{href}">'


def _strip_front_matter(text: str) -> str:
    """Return `text` without its leading YAML front-matter block, if present."""
    return _FRONT_MATTER.sub("", text, count=1)


def on_post_page(output: str, page: Any = None, config: Any = None, **_: Any) -> str:
    """Write the Markdown twin and advertise it from the HTML head.

    Runs per page after rendering, which is the first point where both the
    source markdown and the final output path are known.
    """
    src = getattr(page, "file", None)
    if src is None or not str(src.src_uri).endswith(".md"):
        return output

    dest = Path(getattr(src, "abs_dest_path", "") or "")
    if not dest.name.endswith(".html"):
        # Non-HTML output (assets copied through) — nothing to mirror.
        return output

    markdown = getattr(page, "markdown", None)
    if not markdown:
        return output

    twin = dest.with_suffix(".md")
    try:
        twin.parent.mkdir(parents=True, exist_ok=True)
        twin.write_text(_strip_front_matter(markdown), encoding="utf-8")
    except OSError:
        # A docs build must not fail because one mirror could not be written.
        return output

    tag = _LINK_TAG.format(href=twin.name)
    if "</head>" in output and tag not in output:
        output = output.replace("</head>", f"{tag}</head>", 1)
    return output
