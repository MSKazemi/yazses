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
