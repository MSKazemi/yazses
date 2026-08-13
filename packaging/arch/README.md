# YazSes on Arch Linux — AUR publishing notes

`PKGBUILD` here is the recipe for the **Arch User Repository**. Once published, Arch users
install with:

```sh
yay -S yazses          # any AUR helper works
# or with the official tools:
git clone https://aur.archlinux.org/yazses.git
cd yazses && makepkg -si
```

## What this package actually is

- **Source is the PyPI sdist**, not a GitHub tag tarball. It is the artifact the release
  actually publishes, its checksum is stable and quotable, and it already contains the man
  page, the systemd user unit, the example config and the licence.
- **Dependencies are real packages**, not a `pip install` inside `package()`. Everything
  comes from `[extra]` except `python-faster-whisper`, `python-sounddevice` and (optionally)
  `python-sherpa-onnx`, which are themselves AUR packages — an AUR package may depend on AUR
  packages. An earlier revision pip-installed at build time, which downloads from PyPI during
  the build, is unreproducible, and is exactly what the AUR guidelines forbid.

## Verified before publishing (2026-08-13, v2.18.2)

Run in a clean `archlinux:latest` container, so none of this depends on the maintainer's box:

| Check | Result |
|---|---|
| `makepkg --printsrcinfo` | clean, 33 lines |
| `namcap PKGBUILD` | no findings |
| `makepkg --nodeps` full build | **succeeds** — wheel builds, `package()` installs |
| sdist SHA-256 vs `sha256sums=` | matches |
| Every file `package()` installs | present in the sdist |
| 12 `[extra]` dependencies | all exist |
| 3 AUR dependencies | exist (`python-faster-whisper` 1.2.1, `python-sounddevice` 0.5.5, `python-sherpa-onnx` 1.13.5) |

Note the package builds against **Python 3.14** on current Arch, ahead of the 3.11/3.12 the
CI matrix covers. `requires-python` is `>=3.11`, so this is allowed, but a runtime problem
would show up here first — `yazses doctor` after install is the check.

Reproduce any of it:

```sh
docker run --rm -v "$PWD:/pkg" -w /pkg archlinux:latest bash -c '
  pacman -Sy --noconfirm base-devel python-build python-installer python-wheel \
      python-hatchling namcap >/dev/null
  useradd -m builder && chown -R builder /pkg
  su builder -c "makepkg --nodeps --noconfirm" && namcap PKGBUILD'
```

## First publication (one-time, needs your AUR SSH key)

`.SRCINFO` is committed next to `PKGBUILD` and is already current, so this is a copy and a
push — nothing to compute.

1. Add your SSH key at <https://aur.archlinux.org> → *My Account → SSH Public Key*.
2. ```sh
   git clone ssh://aur@aur.archlinux.org/yazses.git yazses-aur
   cp packaging/arch/PKGBUILD packaging/arch/.SRCINFO packaging/arch/yazses.install yazses-aur/
   cd yazses-aur
   git add PKGBUILD .SRCINFO yazses.install
   git commit -m "Initial import: yazses 2.18.2"
   git push origin master
   ```

The package appears on the AUR within minutes. Confirm with:

```sh
curl -s "https://aur.archlinux.org/rpc/v5/info?arg[]=yazses" | grep -o '"Version":"[^"]*"'
```

## Per-release update

```sh
V=2.19.0
sed -i "s/^pkgver=.*/pkgver=$V/; s/^pkgrel=.*/pkgrel=1/" PKGBUILD
SHA=$(curl -sL "https://files.pythonhosted.org/packages/source/y/yazses/yazses-$V.tar.gz" \
      | sha256sum | awk '{print $1}')
sed -i "s/^sha256sums=.*/sha256sums=('$SHA')/" PKGBUILD
docker run --rm -v "$PWD:/pkg" -w /pkg archlinux:latest bash -c \
  'useradd -m b && chown -R b /pkg && su b -c "makepkg --printsrcinfo"' > .SRCINFO
```

then copy both files into the AUR clone, commit, push. `.SRCINFO` must be regenerated every
time — the AUR reads *it*, not the `PKGBUILD`, so a stale one silently advertises the old
version. `tests/test_packaging_arch.py` fails if the two disagree.

## Notes for users

- Add yourself to the `input` group and re-login: `sudo usermod -aG input "$USER"`.
  Hold-to-talk reads `/dev/input/event*` and cannot work without it.
- Enable the daemon: `systemctl --user enable --now yazses.service`.
- `yazses doctor` is the first stop for anything that misbehaves.
