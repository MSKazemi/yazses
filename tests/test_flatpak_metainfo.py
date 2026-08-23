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

import json
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


# ---------------------------------------------------------------------------
# The listing is not the only thing the build has to produce.
#
# The metainfo declares `<component type="desktop-application">` and a
# `<launchable type="desktop-id">`, and the build manifest installed **none** of the
# three files that promise implies: no .desktop, no icon, and not even the metainfo
# itself. `grep -rl com.mskazemi.YazSes.desktop` matched exactly one file in the whole
# repository -- the metainfo naming it.
#
# Every check above this line reads the XML. So does `appstreamcli validate`, and so does
# pre-flight item 5 in SUBMISSION.md, which is why all of them passed: validating a file
# says nothing about whether the build ships it. These guards close that gap by reading
# the *manifest* and asking what lands in /app.
# ---------------------------------------------------------------------------

MANIFEST = ROOT / "packaging/flatpak/com.mskazemi.YazSes.yml"
FLATPAK_DIR = MANIFEST.parent


def _manifest() -> dict:
    import yaml

    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _install_destinations() -> list[str]:
    """Every ``${FLATPAK_DEST}`` path any module's build commands write to.

    Read across all modules rather than one named module: which module does the
    installing is an implementation detail, and a guard that names one would go green
    the day the work moves.
    """
    dests: list[str] = []
    for module in _manifest()["modules"]:
        if not isinstance(module, dict):
            continue  # a string is an external module file, e.g. python3-yazses.json
        for command in module.get("build-commands", []):
            flat = " ".join(command.split())
            dests += re.findall(r"\$\{FLATPAK_DEST\}(/\S+)", flat)
    return dests


def _app_id() -> str:
    return _root().findtext("id", "").strip()


def test_the_launchable_names_a_desktop_file_that_exists() -> None:
    """A desktop-id pointing at nothing is the listing having no app-grid entry."""
    launchable = _root().find("launchable[@type='desktop-id']")
    assert launchable is not None, "metainfo declares no <launchable type='desktop-id'>"
    name = (launchable.text or "").strip()
    assert name == f"{_app_id()}.desktop", (
        f"Flathub requires the desktop file to be named after the app ID; got {name!r}"
    )
    assert (FLATPAK_DIR / name).is_file(), (
        f"{name} is named by the metainfo but does not exist in packaging/flatpak/"
    )


def test_the_build_installs_the_desktop_file_the_launchable_names() -> None:
    name = (_root().findtext("launchable") or "").strip()
    assert f"/share/applications/{name}" in _install_destinations(), (
        "the manifest never installs the .desktop file the metainfo promises -- "
        "the app would have no launcher, no icon and no store entry"
    )


def test_the_build_installs_the_metainfo_itself() -> None:
    """Validating the XML in the repo proves nothing if /app never receives it."""
    wanted = f"/share/metainfo/{_app_id()}.metainfo.xml"
    assert wanted in _install_destinations(), (
        f"the manifest never installs the metainfo to {wanted}"
    )


def test_the_build_installs_an_icon_named_after_the_app_id() -> None:
    pattern = re.compile(
        rf"^/share/icons/hicolor/(scalable|\d+x\d+)/apps/{re.escape(_app_id())}\.(svg|png)$"
    )
    matches = [d for d in _install_destinations() if pattern.match(d)]
    assert matches, (
        "no hicolor icon named after the app ID is installed; stores resolve the "
        "listing's icon by app ID and would render the app with none"
    )


def test_every_file_the_manifest_declares_is_committed_beside_it() -> None:
    """`path:` sources are relative to the manifest, so the Flathub repository has to
    carry them too. A missing one fails the build there and nowhere here."""
    missing = []
    for module in _manifest()["modules"]:
        if not isinstance(module, dict):
            continue
        for source in module.get("sources", []):
            path = source.get("path")
            if path and not (FLATPAK_DIR / path).is_file():
                missing.append(path)
    assert not missing, f"manifest references files that do not exist: {missing}"


def test_the_desktop_entry_launches_the_command_the_manifest_exports() -> None:
    """`Exec` naming a command flatpak does not export is a launcher that does nothing.

    Flatpak rewrites Exec into `flatpak run --command=<first token> <app-id> <rest>`, so
    the first token has to be the manifest's own `command:`.
    """
    entry = dict(
        line.split("=", 1)
        for line in (FLATPAK_DIR / f"{_app_id()}.desktop")
        .read_text(encoding="utf-8")
        .splitlines()
        if "=" in line and not line.startswith(("#", "["))
    )
    assert entry["Type"] == "Application"
    assert entry["Name"], "desktop entry has no Name"
    assert entry["Exec"].split()[0] == _manifest()["command"], (
        f"Exec runs {entry['Exec'].split()[0]!r} but the manifest exports "
        f"{_manifest()['command']!r}"
    )
    assert entry["Icon"] == _app_id(), (
        "Icon must be the app ID: that is the name the installed hicolor icon carries"
    )
    assert entry["Categories"].endswith(";"), "Categories must be a ;-terminated list"


# --- what a Flathub install would actually contain ---------------------------------


PYTHON_SOURCES = ROOT / "packaging/flatpak/python3-yazses.json"

#: `yazses-2.29.0-py3-none-any.whl` -> `2.29.0`, from the wheel's own filename. PEP 427
#: puts the version in the second `-`-separated field, so this reads the artifact rather
#: than the URL path, whose hash directories say nothing.
_WHEEL = re.compile(r"/(yazses)-([^-]+)-py3-none-any\.whl$")


def _yazses_wheel_sources() -> list[dict]:
    sources = json.loads(PYTHON_SOURCES.read_text(encoding="utf-8"))["sources"]
    return [s for s in sources if _WHEEL.search(s.get("url", ""))]


def test_the_flatpak_installs_exactly_one_yazses_wheel():
    """Non-vacuity, and a second pin would make "which one wins" a build-order question."""
    found = _yazses_wheel_sources()
    assert len(found) == 1, (
        f"{len(found)} yazses wheels pinned in {PYTHON_SOURCES.name}: "
        f"{[s.get('url') for s in found]}"
    )


def test_the_pinned_wheel_is_the_version_the_listing_advertises():
    """The listing said 2.29.0 and the build installed 2.18.2 — eleven releases apart.

    `test_the_newest_release_entry_matches_the_project_version` above already holds the
    *metainfo* to `pyproject.toml`, which is exactly why this went unnoticed: that guard
    kept the advertised half current while the installed half stayed where it was. A
    Flathub user would have read 2.29.0 on the store page and run 2.18.2, and nothing in
    the repository disagreed. Half a relationship checked is not the relationship checked.

    Bumping the version therefore has to bump this pin too, hash included — the URL is
    content-addressed by PyPI, so a stale hash is a hard build failure rather than a
    silently old install, and that is the failure mode to prefer.
    """
    (source,) = _yazses_wheel_sources()
    match = _WHEEL.search(source["url"])
    assert match is not None
    pinned = match.group(2)
    project = PYPROJECT["project"]["version"]
    assert pinned == project, (
        f"the Flatpak build installs yazses {pinned}, but this project is at {project} "
        f"and the metainfo advertises it. Update the `url` *and* the `sha256` in "
        f"{PYTHON_SOURCES.name} from https://pypi.org/pypi/yazses/{project}/json"
    )


def test_the_pinned_wheel_states_a_sha256():
    """Flatpak verifies it; an absent or placeholder hash fails at build, not at review."""
    (source,) = _yazses_wheel_sources()
    digest = str(source.get("sha256", ""))
    assert re.fullmatch(r"[0-9a-f]{64}", digest), (
        f"the yazses wheel pin has no usable sha256 (got {digest!r})"
    )


def test_every_linux_runtime_dependency_is_pinned_in_the_manifest():
    """A Flatpak that installs the right version and is missing an import is no better.

    `python3-yazses.json` is regenerated only by a `workflow_dispatch` run of
    `.github/workflows/flatpak.yml`, whose artifact a human then commits — it cannot be
    produced on a laptop, because the wheels must match the *runtime's* Python inside
    `org.kde.Sdk` rather than the host's. That manual step is why the yazses pin sat
    eleven releases behind, and it is equally why a dependency added to `pyproject.toml`
    afterwards would simply not be in the Flatpak.

    Platform-gated dependencies are excluded by reading their environment marker, not by
    listing their names: `pyobjc-*`, `rumps` (darwin), `pywin32`, `pystray`, `Pillow`
    (win32) are all correctly absent from a Linux build, and a name list would have to be
    remembered every time one is added.
    """
    pinned = set()
    sources = json.loads(PYTHON_SOURCES.read_text(encoding="utf-8"))["sources"]
    for source in sources:
        match = re.search(r"/([A-Za-z0-9_.\-]+)-\d[^/]*\.(?:whl|tar\.gz)$", source.get("url", ""))
        if match:
            pinned.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    assert len(pinned) > 20, f"only {len(pinned)} pins parsed out of {len(sources)} sources"

    missing = []
    for spec in PYPROJECT["project"]["dependencies"]:
        requirement, _, marker = spec.partition(";")
        if "darwin" in marker or "win32" in marker:
            continue
        name = re.split(r"[\[<>=!~ ]", requirement.strip(), maxsplit=1)[0]
        if re.sub(r"[-_.]+", "-", name).lower() not in pinned:
            missing.append(name)

    assert not missing, (
        f"{missing} are runtime dependencies on Linux but are pinned nowhere in "
        f"{PYTHON_SOURCES.name}, so the Flatpak would install without them. Re-run the "
        "`regenerate` job of .github/workflows/flatpak.yml and commit its artifact."
    )
