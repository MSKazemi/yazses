"""The Flathub listing must be complete before it is submitted, not after.

`packaging/flatpak/com.mskazemi.YazSes.metainfo.xml` **is** the Flathub listing: GNOME
Software and KDE Discover render it, and flathub.org indexes it as a web page. A field
missing here is not a packaging detail, it is a listing defect that a reviewer sees
before anyone installs anything.

This exists because the submission ([#45](https://github.com/MSKazemi/yazses/issues/45),
flathub/flathub#9765) was **closed**, and the post-mortem in that issue names the demo
video as the blocker. It was not the only one: the metainfo also had no `<screenshots>`
block at all, which flathub's own linter flags and which would have left the listing with
no images. Nothing in this repository would have caught that, because nothing read this
file.

So these are listing-completeness guards, in the same spirit as
`test_packaging_metadata.py`'s drift guards -- with one addition that a linter cannot do:
every screenshot URL is checked to correspond to a file that actually exists in this
repository, since a listing whose images 404 is worse than one with none.
"""

from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
METAINFO = ROOT / "packaging/flatpak/com.mskazemi.YazSes.metainfo.xml"
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

#: House floor, not a Flathub rule -- worth being precise about, because an invented
#: requirement enforced by a test is indistinguishable from a real one to whoever hits
#: it next. Flathub's quality guidelines state no minimum; they say a screenshot's
#: *window* should be 1000x700 or smaller (2000x1400 HiDPI). 620px is the width below
#: which appstream-glib has historically warned and below which store thumbnails
#: render poorly, so it is a sensible floor to hold ourselves to.
MIN_SCREENSHOT_WIDTH = 620

#: Flathub's quality guidelines, verbatim: "Every screenshot should have a caption
#: briefly describing it. Captions should only be one sentence and not end with a full
#: stop." These two are real, citable requirements -- unlike the width above.
MAX_SCREENSHOT_HEIGHT_HIDPI = 1400

RAW_PREFIX = "https://raw.githubusercontent.com/MSKazemi/yazses/main/"


def _root() -> ET.Element:
    return ET.parse(METAINFO).getroot()


@pytest.mark.parametrize(
    "field",
    ["id", "name", "summary", "metadata_license", "project_license", "description"],
)
def test_the_listing_has_every_required_appstream_field(field: str):
    assert _root().find(field) is not None, f"metainfo has no <{field}>"


def test_the_listing_has_screenshots():
    """A desktop-application with no screenshots is what flathub's linter rejects."""
    shots = _root().findall("screenshots/screenshot")
    assert shots, (
        "no <screenshots> in the metainfo — GNOME Software and KDE Discover would "
        "show this app with no images at all, and flathub's linter flags it"
    )


def test_exactly_one_screenshot_is_the_default():
    """A house rule rather than a Flathub one: the store shows a header image, and
    leaving which one to chance means it changes when the list is reordered."""
    shots = _root().findall("screenshots/screenshot")
    default = [s for s in shots if s.get("type") == "default"]
    assert len(default) == 1, (
        f"{len(default)} screenshots marked type='default'; exactly one should be, and "
        f"it is the image shown in the store listing header"
    )


def test_every_screenshot_has_a_caption():
    """An uncaptioned screenshot is rendered, unexplained, to someone deciding to install."""
    for shot in _root().findall("screenshots/screenshot"):
        caption = shot.find("caption")
        image = shot.find("image")
        url = (image.text or "") if image is not None else "?"
        assert caption is not None and (caption.text or "").strip(), (
            f"screenshot {url} has no <caption>"
        )


def test_every_screenshot_file_exists_in_this_repository():
    """A listing whose images 404 is worse than a listing with none.

    The URLs point into this repo on `main`, so the file being present here is exactly
    the condition for the published listing resolving.
    """
    for image in _root().findall("screenshots/screenshot/image"):
        url = (image.text or "").strip()
        assert url.startswith(RAW_PREFIX), (
            f"{url} is not a raw URL into this repository, so this test cannot verify "
            f"it resolves — either use one, or update this guard deliberately"
        )
        path = ROOT / url[len(RAW_PREFIX):]
        assert path.is_file(), f"{url} points at {path.relative_to(ROOT)}, which does not exist"


def test_every_screenshot_is_wide_enough_to_render_well():
    for image in _root().findall("screenshots/screenshot/image"):
        width = image.get("width")
        assert width, f"{image.text} declares no width"
        assert int(width) >= MIN_SCREENSHOT_WIDTH, (
            f"{image.text} is {width}px wide, below our {MIN_SCREENSHOT_WIDTH}px floor "
            f"-- store thumbnails render poorly below it"
        )


def test_no_screenshot_exceeds_the_hidpi_window_size_guideline():
    """Flathub: the window should be 1000x700 or smaller, 2000x1400 for HiDPI."""
    for image in _root().findall("screenshots/screenshot/image"):
        height = int(image.get("height", 0))
        assert height <= MAX_SCREENSHOT_HEIGHT_HIDPI, (
            f"{image.text} is {height}px tall; Flathub's guideline caps the captured "
            f"window at 2000x1400 even for HiDPI"
        )


def test_captions_follow_flathubs_stated_style():
    """Verbatim from the quality guidelines: one sentence, no trailing full stop.

    Small, but it is the kind of thing a reviewer notices immediately and it costs a
    round trip on a submission that has already been closed once.
    """
    for caption in _root().findall("screenshots/screenshot/caption"):
        text = (caption.text or "").strip()
        assert not text.endswith("."), (
            f"caption {text!r} ends with a full stop; Flathub asks that captions do not"
        )
        assert text.count(".") == 0 and ";" not in text, (
            f"caption {text!r} looks like more than one sentence; Flathub asks for one"
        )


def test_the_declared_screenshot_dimensions_match_the_real_files():
    """A wrong width/height is a silently stretched image in the store."""
    Image = pytest.importorskip("PIL.Image", reason="Pillow renders the check")
    for image in _root().findall("screenshots/screenshot/image"):
        url = (image.text or "").strip()
        path = ROOT / url[len(RAW_PREFIX):]
        if not path.is_file():
            continue
        real = Image.open(path).size
        declared = (int(image.get("width", 0)), int(image.get("height", 0)))
        assert real == declared, (
            f"{path.name} is {real[0]}x{real[1]} but the metainfo declares "
            f"{declared[0]}x{declared[1]}"
        )


def test_the_newest_release_entry_matches_the_project_version():
    """A listing that announces an older version than the one being submitted."""
    releases = _root().findall("releases/release")
    assert releases, "no <releases> in the metainfo"
    versions = {r.get("version") for r in releases}
    assert PYPROJECT["project"]["version"] in versions, (
        f"metainfo lists releases {sorted(versions)} but the project is at "
        f"{PYPROJECT['project']['version']}"
    )


def test_the_app_id_is_the_one_flathub_has_reserved():
    """The ID is permanent — changing it orphans every existing install."""
    assert (_root().findtext("id") or "").strip() == "com.mskazemi.YazSes"


def test_no_url_field_is_left_as_a_placeholder():
    for url in _root().findall("url"):
        text = (url.text or "").strip()
        assert text and not re.search(r"example\.(com|org)|TODO|FIXME", text), (
            f"<url type={url.get('type')!r}> is a placeholder: {text!r}"
        )
