"""A packaged systemd unit must name the binary its package actually installs.

`contrib/yazses.service` says `%h/.local/bin/yazses-daemon` (a pipx install). The deb and
Arch packages put the console script in /usr/bin, so each must rewrite that path -- left
alone, the unit fails 203/EXEC five times and systemd gives up while `yazses start`
reports success.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REWRITE = "s|%h/.local/bin/yazses-daemon|/usr/bin/yazses-daemon|g"


def test_contrib_unit_uses_the_pipx_path():
    text = (ROOT / "contrib" / "yazses.service").read_text(encoding="utf-8")
    assert "ExecStart=%h/.local/bin/yazses-daemon" in text


def test_deb_rewrites_the_execstart():
    assert REWRITE in (ROOT / "scripts" / "build-deb.sh").read_text(encoding="utf-8")


def test_arch_rewrites_the_execstart():
    assert REWRITE in (ROOT / "packaging" / "arch" / "PKGBUILD").read_text(encoding="utf-8")


def test_unit_self_heals_on_failure():
    text = (ROOT / "contrib" / "yazses.service").read_text(encoding="utf-8")
    assert "Restart=on-failure" in text
    assert "StartLimitBurst=" in text


# ---- every channel, discovered rather than listed ------------------------------------
#
# The three tests above name the deb and Arch files. A channel added tomorrow would not be
# named anywhere, which is how `debian/rules` shipped the same bug as `build-deb.sh` two
# directories away. So find the files instead: anything that mentions the contrib unit AND
# installs under a system path must rewrite its ExecStart.

_SYSTEM_TARGETS = ("/usr/", "_unitdir", "_userunitdir", "/lib/systemd")
_SKIP = {".git", ".venv", "node_modules", "docs", "design", "tests", "CHANGELOG.md"}


def _packaging_files():
    candidates = [ROOT / "debian", ROOT / "packaging", ROOT / "scripts", ROOT / "snap"]
    for base in candidates:
        for path in base.rglob("*"):
            if path.is_file() and not (set(path.parts) & _SKIP) and path.suffix not in {".png", ".svg", ".json"}:
                yield path
    for name in ("install.sh", "install-apt.sh", "install-pipx.sh"):
        yield ROOT / name


def _text(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def test_every_system_install_of_the_unit_rewrites_execstart():
    offenders = []
    for path in _packaging_files():
        text = _text(path)
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "contrib/yazses.service" not in line:
                continue
            # The install target sits on this line or a continuation just after it. A user
            # install (~/.config/systemd/user) legitimately keeps %h/.local/bin.
            window = " ".join(lines[i : i + 3])
            if any(t in window for t in _SYSTEM_TARGETS) and REWRITE not in text:
                offenders.append(path.relative_to(ROOT).as_posix())
                break
    assert not offenders, (
        "installs contrib/yazses.service under a system path without rewriting "
        f"%h/.local/bin -> /usr/bin (203/EXEC crash loop): {offenders}"
    )


def test_every_postinst_that_pipx_installs_links_usr_bin():
    """pipx installs into ~/.local/bin; the packaged unit names /usr/bin."""
    offenders = []
    for path in _packaging_files():
        text = _text(path)
        if "pipx install" in text and "configure" in text and "usr/lib/systemd" not in text:
            if "/usr/bin/$bin" not in text and "/usr/bin/yazses-daemon" not in text:
                offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, f"pipx-installing maintainer script without /usr/bin links: {offenders}"


def test_the_debian_source_package_is_covered():
    assert REWRITE in _text(ROOT / "debian" / "rules")
    assert "/usr/bin/$bin" in _text(ROOT / "debian" / "postinst")
