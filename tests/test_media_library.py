"""The public media library keeps its promises: licensed rows, final outputs only, small files.

`assets/media/` is where finished images, carousels and videos live so that other people can repost them.
A row that is approved without a licence, an editable source file, a PDF or a heavy binary would each
break that promise in a different way, so each is refused here. Videos live on the `media-kit` release
(see assets/media/README.md), never in Git.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "assets" / "media"
CATALOG = MEDIA / "CATALOG.md"

# Editable sources and raw material: the library publishes final exports only.
_SOURCE_SUFFIXES = {
    ".psd", ".ai", ".xcf", ".sketch", ".fig", ".afdesign", ".indd",
    ".pptx", ".ppt", ".key", ".odp",
    ".aep", ".prproj", ".drp", ".kdenlive", ".blend",
    ".mov", ".mkv", ".avi", ".wav", ".aiff",
    ".pdf",
}
_VIDEO_SUFFIXES = {".mp4", ".webm", ".m4v"}
_MAX_FILE_BYTES = 5 * 1024 * 1024  # small finals only; anything bigger is a release asset


def _approved_table() -> list[list[str]]:
    text = CATALOG.read_text(encoding="utf-8")
    start = text.index("## Approved media packs")
    end = text.index("\n## ", start + 1)
    rows = []
    for line in text[start:end].splitlines():
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= set("- :"):
            continue
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def test_every_approved_row_carries_a_licence() -> None:
    header, *rows = _approved_table()
    assert header[-1] == "License", f"the approved table must end with a License column, got {header}"
    assert rows, "the approved table is empty"
    for row in rows:
        assert len(row) == len(header), f"ragged row: {row}"
        status, licence = row[header.index("Status")], row[header.index("License")]
        assert status.startswith("approved"), f"a row in the approved table is not approved: {row[0]}"
        assert len(licence) >= 8 and licence.lower() not in {"tbd", "unknown", "n/a", "free"}, (
            f"{row[0]!r} is approved without a stated licence"
        )


def test_the_licence_file_names_cc_by_and_what_it_excludes() -> None:
    text = (MEDIA / "LICENSE.md").read_text(encoding="utf-8")
    assert "CC-BY-4.0" in text
    for needle in ("Third-party material", "Apache-2.0", "endorse"):
        assert needle in text, f"LICENSE.md no longer says {needle!r}"
    readme = (MEDIA / "README.md").read_text(encoding="utf-8")
    assert "LICENSE.md" in readme and "CC BY 4.0" in readme


def test_the_library_holds_final_outputs_only() -> None:
    offenders = []
    for path in sorted(MEDIA.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in _SOURCE_SUFFIXES:
            offenders.append(f"{rel}: editable source, raw footage or PDF")
        elif path.suffix.lower() in _VIDEO_SUFFIXES:
            offenders.append(f"{rel}: videos belong on the media-kit release, not in Git")
        elif path.stat().st_size > _MAX_FILE_BYTES:
            offenders.append(f"{rel}: {path.stat().st_size / 1e6:.1f} MB is too large for Git")
    assert not offenders, "\n".join(offenders)


def test_catalog_links_to_files_that_exist() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    missing = []
    for target in re.findall(r"\]\((\.\./[^)#\s]+|[A-Za-z0-9_./-]+\.md)(?:#[^)]*)?\)", text):
        if not (CATALOG.parent / target).resolve().exists():
            missing.append(target)
    assert not missing, f"CATALOG.md links to missing paths: {missing}"


def test_every_carousel_is_complete_and_in_order() -> None:
    """A carousel is posted in order: contiguous slide-NN.png, one alt-text line per slide, and a caption."""
    carousels = sorted((MEDIA / "carousels").glob("*/"))
    assert carousels, "no carousels in the library"
    for directory in carousels:
        slides = sorted(p.name for p in directory.glob("slide-*.png"))
        expected = [f"slide-{n:02d}.png" for n in range(1, len(slides) + 1)]
        assert slides == expected and len(slides) >= 3, f"{directory.name}: slides are not contiguous from 01: {slides}"
        alt = (directory / "alt-text-en.md").read_text(encoding="utf-8")
        described = re.findall(r"(?m)^(\d\d)\. ", alt)
        assert described == [f"{n:02d}" for n in range(1, len(slides) + 1)], (
            f"{directory.name}: alt text covers {described}, slides are {len(slides)}"
        )
        assert (directory / "caption-en.md").read_text(encoding="utf-8").strip(), f"{directory.name}: empty caption"
        listed = f"{directory.relative_to(MEDIA).as_posix()}/"
        assert listed in CATALOG.read_text(encoding="utf-8"), (
            f"{directory.name} is in the library but not in the catalog"
        )
