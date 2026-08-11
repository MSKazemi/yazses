"""Heading anchors that survive Indic scripts.

`pymdownx.slugs.slugify` — which `mkdocs.yml` selects so that generated pages and
GitHub agree on anchors — strips every character outside `[^\\w\\- ]`. Python's
`\\w` is alphanumerics plus underscore, and a Unicode *combining mark* is not
alphanumeric: `'ा'.isalnum()` is `False` (category `Mc`), as is `'ँ'` (`Mn`).

Devanagari, Tamil, Bengali and Telugu write most of their vowels as exactly those
marks. So the Hindi heading `ईमानदार सीमाएँ` slugged to `ईमनदर-समए` — every matra
silently deleted, leaving a consonant skeleton that is not a word in any language.

It stayed invisible because it was *self-consistent*: the heading's own id and the
"On this page" entry pointing at it were mangled identically, so in-page navigation
worked. Only a hand-written cross-link — `[ईमानदार सीमाएँ](#ईमानदार-सीमाएँ)` in
`hi/hindi-voice-typing.md` — spelled the anchor correctly, did not match, and
aborted the strict build. Any hand-written link into any Indic heading would have
failed the same way, and the deep links themselves were unusable.

This slugifier keeps the two properties `mkdocs.yml` already depends on:

* **GitHub-compatible spacing.** Each space becomes one separator, spaces are not
  collapsed, so `Accuracy & correction` still yields `accuracy--correction` to
  match the anchors `scripts/gen-docs.py` writes into `docs/features.md`.
* **Lowercasing and tag stripping**, as `case: lower` asked for.

and adds one: characters in Unicode categories `Mn`/`Mc`/`Me` are kept, so a
vowel sign is treated as part of the letter it attaches to rather than punctuation.
That is script-agnostic — it fixes Arabic harakat and Thai vowel signs on the same
terms, without this file needing to know those scripts exist.

Applied from `on_config` rather than named directly in `mkdocs.yml` because the
`!!python/name:` YAML tag is resolved against `sys.path` while the config is being
parsed, and the repository root is not on it (the docs job installs the toolchain
with `--no-install-project`). Hooks are loaded by *path*, so this always resolves.

Registered via `hooks:` in mkdocs.yml.
"""

from __future__ import annotations

import re
import unicodedata

# Matches an HTML tag, so markup in a heading does not leak into its anchor.
# Mirrors `pymdownx.slugs.RE_TAGS`.
RE_TAGS = re.compile(r"</?[^>]*>")

# Unicode general categories for combining marks: non-spacing, spacing-combining,
# and enclosing. These carry the vowels in abugida scripts.
_MARK_CATEGORIES = frozenset({"Mn", "Mc", "Me"})


def _keep(char: str) -> bool:
    """Is `char` allowed to survive into a slug?

    The `\\w\\- ` allowance of the upstream slugifier, widened by combining marks.
    """
    if char.isalnum() or char in "_- ":
        return True
    return unicodedata.category(char) in _MARK_CATEGORIES


def slugify_unicode(text: str, sep: str) -> str:
    """Slugify `text`, preserving combining marks.

    Signature matches what Python-Markdown's `toc` extension calls: the heading
    text and the separator character.
    """
    slug = RE_TAGS.sub("", unicodedata.normalize("NFC", text)).strip().lower()
    slug = "".join(char for char in slug if _keep(char))
    # One separator per space, never collapsed — this is what makes the output
    # match GitHub's anchors for headings containing dropped punctuation.
    return slug.replace(" ", sep)


def on_config(config):  # noqa: D103 - mkdocs hook signature
    config["mdx_configs"].setdefault("toc", {})["slugify"] = slugify_unicode
    return config
