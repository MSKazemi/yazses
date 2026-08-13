"""Point the Chocolatey package at a specific release, deriving the checksum.

Nothing regenerated the Chocolatey package: refresh-package-manifests.py covers
only the Homebrew cask and the winget manifests. The nuspec version, the download
URL and the checksum were all hardcoded, so the next tag would have packed
`yazses.<old>.nupkg` (the push then fails on a filename that does not exist) while
the install script still pointed at the previous release's .exe.

The checksum is read from the SHA256SUMS.txt published on the release itself, so
the package and the artifact cannot disagree.
"""
import re
import sys
import urllib.request

REPO = "MSKazemi/yazses"


def sha_for_exe(version: str) -> str:
    url = f"https://github.com/{REPO}/releases/download/v{version}/SHA256SUMS.txt"
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode()
    for line in text.splitlines():
        digest, _, name = line.partition("  ")
        if name.strip().endswith(".exe"):
            return digest.strip()
    raise SystemExit(f"no .exe line in SHA256SUMS.txt for v{version}:\n{text}")


def main(version: str, nuspec: str, install: str) -> int:
    sha = sha_for_exe(version)

    s = open(nuspec, encoding="utf-8").read()
    s, n = re.subn(r"<version>[^<]+</version>", f"<version>{version}</version>", s, count=1)
    if n != 1:
        raise SystemExit("could not find <version> in the nuspec")
    open(nuspec, "w", encoding="utf-8").write(s)

    p = open(install, encoding="utf-8").read()
    exe = f"YazSes-{version}-windows-x64.exe"
    p, a = re.subn(
        r"(url64bit\s*=\s*')[^']+(')",
        rf"\1https://github.com/{REPO}/releases/download/v{version}/{exe}\2", p, count=1)
    p, b = re.subn(r"(checksum64\s*=\s*')[^']+(')", rf"\g<1>{sha}\2", p, count=1)
    if a != 1 or b != 1:
        raise SystemExit(f"install script rewrite failed (url={a} checksum={b})")
    open(install, "w", encoding="utf-8").write(p)

    print(f"chocolatey package set to {version}, checksum {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
