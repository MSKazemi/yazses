"""Emit reciprocal `hreflang` links between translated versions of a page.

The docs are written in English, but some pages exist to answer a question that
people ask in another language — "hindi voice typing software for pc offline" is
searched in Hindi at least as often as in English. When a translation exists,
search engines need to be told that the two pages are the *same* page in
different languages, or they treat them as unrelated duplicates and usually pick
one to show to everybody.

That signal is `<link rel="alternate" hreflang="…">`, and it has one hard rule:
it must be **reciprocal**. A page declaring an alternate that does not point back
is ignored outright, so this hook derives both directions from a single
declaration rather than trusting two pages to stay in sync by hand.

Usage — in the *translation's* front matter, name the original:

    ---
    title: …
    alternates:
      en: use-cases/hindi-voice-typing.md
    ---

The page's own language comes from its top-level docs directory (`docs/hi/…` is
Hindi); anything outside a known language directory is the site default. Both
sides of the pair then receive the full set of tags, plus `x-default` pointing at
the default-language version, which is what search engines fall back to for a
locale they have no better match for.

Absolute URLs are required by the spec — relative hrefs in an alternate link are
silently dropped — so these are built from `site_url`.

Registered via `hooks:` in mkdocs.yml. Tested in tests/test_hreflang_hook.py.
"""

from __future__ import annotations

from typing import Any

# Top-level docs directories that denote a translation rather than a section.
# Keep in step with any language directory added under docs/.
#
# `hi` and `zh` predate the rest: they hold single use-case pages written to answer a
# question people ask in that language. The remainder arrived when the 28 README
# translations moved out of the repo root, where a `blob/main/README.xx.md` page could
# carry neither `hreflang` nor `canonical` and the whole set read to a search engine as
# unrelated duplicates of each other.
LANGUAGE_DIRS = {
    "ar", "bn", "cs", "de", "el", "es", "fa", "fr", "he", "hi", "id", "it", "ja",
    "ko", "nl", "pl", "pt-BR", "ru", "sv", "ta", "te", "th", "tr", "uk", "ur",
    "vi", "zh", "zh-CN", "zh-TW",
}

DEFAULT_LANGUAGE = "en"

# Kept on one line so the minify plugin has nothing to reflow.
_LINK_TAG = '<link rel="alternate" hreflang="{lang}" href="{href}">'


def page_language(src_uri: str) -> str:
    """Return the language code for a page, from its top-level directory.

    ``hi/hindi-voice-typing.md`` is Hindi; ``use-cases/foo.md`` is the site
    default. Pure.
    """
    head, _, rest = src_uri.partition("/")
    if rest and head in LANGUAGE_DIRS:
        return head
    return DEFAULT_LANGUAGE


def _page_url(site_url: str, src_uri: str) -> str:
    """Absolute URL for a source page, honouring `use_directory_urls: false`."""
    return f"{site_url.rstrip('/')}/{src_uri.removesuffix('.md')}.html"


def build_alternates(
    src_uri: str, declared: dict[str, str], site_url: str
) -> dict[str, str]:
    """Return ``{lang: absolute_url}`` for every version of this page.

    Includes the page itself and an ``x-default`` entry pointing at the
    default-language version. Pure, so the reciprocity rule can be tested
    without building the site.
    """
    pages = {page_language(src_uri): src_uri}
    for lang, uri in declared.items():
        pages[lang] = uri

    out = {lang: _page_url(site_url, uri) for lang, uri in pages.items()}
    if DEFAULT_LANGUAGE in out:
        out["x-default"] = out[DEFAULT_LANGUAGE]
    return out


def _collect_pairs(config: Any) -> dict[str, dict[str, str]]:
    """Map every page in a translation pair to its ``{lang: src_uri}`` group.

    Built once from the whole page set so the *original* gets its tags too,
    without needing a declaration of its own — which is what keeps the pair
    reciprocal even when only the translation is edited.
    """
    groups: dict[str, dict[str, str]] = {}
    for page in getattr(config, "_hreflang_pages", []):
        declared = (page.meta or {}).get("alternates") or {}
        if not isinstance(declared, dict) or not declared:
            continue
        group = {page_language(page.file.src_uri): page.file.src_uri}
        for lang, uri in declared.items():
            group[str(lang)] = str(uri)
        for uri in group.values():
            groups[uri] = group
    return groups


def on_nav(nav: Any, config: Any = None, files: Any = None, **_: Any) -> Any:
    """Stash the page list so a page can see its partner during rendering."""
    pages = [f.page for f in files if getattr(f, "page", None) is not None]
    config._hreflang_pages = pages  # type: ignore[union-attr]
    config._hreflang_groups = None  # type: ignore[union-attr]
    return nav


def on_post_page(output: str, page: Any = None, config: Any = None, **_: Any) -> str:
    """Inject the reciprocal hreflang set into this page's head, if it has one."""
    if page is None or config is None or "</head>" not in output:
        return output

    groups = getattr(config, "_hreflang_groups", None)
    if groups is None:
        groups = _collect_pairs(config)
        config._hreflang_groups = groups

    src_uri = getattr(getattr(page, "file", None), "src_uri", "")
    group = groups.get(src_uri)
    if not group:
        return output

    site_url = str(config.get("site_url") or "").strip()
    if not site_url:
        # Without an absolute base the tags would be invalid; emit nothing
        # rather than something search engines will discard.
        return output

    tags = "".join(
        _LINK_TAG.format(lang=lang, href=href)
        for lang, href in sorted(build_alternates(src_uri, group, site_url).items())
    )
    if tags and tags not in output:
        output = output.replace("</head>", f"{tags}</head>", 1)
    return output
