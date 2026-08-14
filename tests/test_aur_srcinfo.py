"""`.SRCINFO` must agree with the PKGBUILD it is generated from.

AUR requires `.SRCINFO` in every package repository and **rejects a push without
it** — which is why the AUR submission could not proceed: the file simply did not
exist here.

It is a generated file, and generated files that are maintained by hand drift.
This one drifts in a way that is worse than usual, because the AUR *web page*
renders `.SRCINFO`, not the PKGBUILD: a stale copy advertises the wrong version
and the wrong checksum to everyone browsing the package, while `makepkg` uses the
PKGBUILD and does something different. The two disagreeing is the failure, not
either one being wrong on its own.

Canonically `.SRCINFO` comes from `makepkg --printsrcinfo`, which needs an Arch
box. This module is the check that can run anywhere.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKGBUILD = ROOT / "packaging" / "arch" / "PKGBUILD"
SRCINFO = ROOT / "packaging" / "arch" / ".SRCINFO"


def _expand(value: str) -> str:
    """Expand the shell variables makepkg expands when it writes `.SRCINFO`.

    `.SRCINFO` is the *expanded* form — `install = yazses.install`, never
    `${pkgname}.install` — so a comparison against the raw PKGBUILD text has to
    do the same substitution or it reports a difference that is not one.
    """
    for var in ("pkgname", "pkgver", "pkgrel"):
        raw = re.search(rf"^{var}=[\"']?([^\"'\n]+)[\"']?$", PKGBUILD.read_text(encoding="utf-8"), re.M)
        if raw:
            value = value.replace(f"${{{var}}}", raw.group(1).strip()).replace(f"${var}", raw.group(1).strip())
    return value


def _pkgbuild_scalar(name: str) -> str:
    match = re.search(rf"^{name}=[\"']?([^\"'\n]+)[\"']?$", PKGBUILD.read_text(encoding="utf-8"), re.M)
    assert match, f"PKGBUILD has no {name}"
    return _expand(match.group(1).strip())


def _pkgbuild_array(name: str) -> list[str]:
    """Entries of a bash array, with comment lines and inline comments dropped.

    Handles both spellings the PKGBUILD uses: a one-liner (`arch=('any')`) and a
    multi-line block. The single-line case must be matched first — a multi-line
    pattern anchored on a closing paren at column 0 runs straight past a
    one-liner and swallows the next array whole.
    """
    text = PKGBUILD.read_text(encoding="utf-8")
    one_liner = re.search(rf"^{name}=\(([^\n)]*)\)\s*$", text, re.M)
    if one_liner:
        return re.findall(r"[\"']([^\"']+)[\"']", one_liner.group(1))
    block = re.search(rf"^{name}=\((.*?)^\)", text, re.M | re.S)
    if not block:
        return []
    out = []
    for raw in block.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        item = re.match(r"^[\"']([^\"']+)[\"']", line)
        if item:
            out.append(item.group(1))
    return out


def _srcinfo() -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for raw in SRCINFO.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        fields.setdefault(key.strip(), []).append(value.strip())
    return fields


def test_srcinfo_exists() -> None:
    """Without it, `git push` to the AUR is refused outright."""
    assert SRCINFO.is_file(), "packaging/arch/.SRCINFO is required by the AUR"


def test_srcinfo_is_tab_indented() -> None:
    """makepkg emits tab-indented fields under `pkgbase`. Spaces parse in most
    tooling and then fail in someone else's, so keep the canonical form."""
    body = [ln for ln in SRCINFO.read_text(encoding="utf-8").splitlines()
            if ln and not ln.startswith(("pkgbase", "pkgname"))]
    bad = [ln for ln in body if ln.strip() and not ln.startswith("\t")]
    assert not bad, f"these .SRCINFO lines are not tab-indented: {bad[:3]}"


def test_version_and_release_match_the_pkgbuild() -> None:
    """The mismatch AUR users actually see: the package page renders .SRCINFO."""
    info = _srcinfo()
    assert info["pkgver"] == [_pkgbuild_scalar("pkgver")]
    assert info["pkgrel"] == [_pkgbuild_scalar("pkgrel")]


def test_checksum_and_source_match_the_pkgbuild() -> None:
    """A stale checksum here means the page advertises a hash that does not match
    the tarball the PKGBUILD actually fetches."""
    info = _srcinfo()
    pkgver = _pkgbuild_scalar("pkgver")
    assert info["sha256sums"] == _pkgbuild_array("sha256sums") or info["sha256sums"] == [
        re.search(r"sha256sums=\('([^']+)'\)", PKGBUILD.read_text(encoding="utf-8")).group(1)
    ]
    # The PKGBUILD source is templated with ${pkgname}/${pkgver}; .SRCINFO is expanded.
    assert len(info["source"]) == 1
    assert info["source"][0].endswith(f"yazses-{pkgver}.tar.gz")
    assert info["source"][0].startswith("https://files.pythonhosted.org/")


def test_dependency_lists_match_the_pkgbuild() -> None:
    """Adding a dependency to the PKGBUILD without regenerating .SRCINFO leaves
    the AUR page understating what the package pulls in."""
    info = _srcinfo()
    for field in ("depends", "makedepends"):
        assert info.get(field, []) == _pkgbuild_array(field), (
            f"{field} differs between PKGBUILD and .SRCINFO — regenerate with "
            f"`makepkg --printsrcinfo > .SRCINFO`"
        )


def test_optdepends_match_the_pkgbuild() -> None:
    info = _srcinfo()
    assert info.get("optdepends", []) == _pkgbuild_array("optdepends")


def test_scalar_metadata_matches() -> None:
    info = _srcinfo()
    for field in ("pkgdesc", "url", "install"):
        assert info[field] == [_pkgbuild_scalar(field)], f"{field} differs"
    assert info["arch"] == _pkgbuild_array("arch")
    assert info["license"] == _pkgbuild_array("license")


def test_pkgbase_and_pkgname_agree() -> None:
    info = _srcinfo()
    name = _pkgbuild_scalar("pkgname")
    assert info["pkgbase"] == [name]
    assert info["pkgname"] == [name]
