# YazSes on Arch Linux — AUR publishing notes

`packaging/arch/PKGBUILD` is the recipe for the **Arch User Repository**.
Once published, Arch users install with:

```sh
yay -S yazses          # any AUR helper works
# or with the official tools:
git clone https://aur.archlinux.org/yazses.git
cd yazses && makepkg -si
```

## Publish steps (one-time)

1. **Create an AUR account** at https://aur.archlinux.org if you don't have
   one, and add your SSH key in *My Account → SSH Public Key*.
2. **Compute the source tarball SHA-256** for the v0.4.0 GitHub tarball:

   ```sh
   curl -sL https://github.com/MSKazemi/yazses/archive/refs/tags/v0.4.0.tar.gz \
     | sha256sum
   ```

3. **Edit `PKGBUILD`** in this directory, replacing `'SKIP'` in `sha256sums=`
   with the real sum.
4. **Generate `.SRCINFO`** alongside `PKGBUILD`:

   ```sh
   makepkg --printsrcinfo > .SRCINFO
   ```

5. **Initialise the AUR git repo and push:**

   ```sh
   git clone ssh://aur@aur.archlinux.org/yazses.git yazses-aur
   cp PKGBUILD .SRCINFO yazses-aur/
   cd yazses-aur
   git add PKGBUILD .SRCINFO
   git commit -m "Initial import: yazses 0.4.0"
   git push origin master
   ```

The package shows up in AUR within minutes. Subsequent releases bump
`pkgver`, regenerate `.SRCINFO`, commit, and push.

## Per-release update

```sh
# In packaging/arch/, after a new release tag lands upstream:
sed -i 's/^pkgver=.*/pkgver=NEW_VERSION/' PKGBUILD
sed -i 's/^pkgrel=.*/pkgrel=1/' PKGBUILD
NEW_SHA=$(curl -sL https://github.com/MSKazemi/yazses/archive/refs/tags/vNEW_VERSION.tar.gz | sha256sum | awk '{print $1}')
sed -i "s/sha256sums=.*/sha256sums=('${NEW_SHA}')/" PKGBUILD
makepkg --printsrcinfo > .SRCINFO

# In your AUR clone:
cp PKGBUILD .SRCINFO ../yazses-aur/
cd ../yazses-aur
git add PKGBUILD .SRCINFO
git commit -m "Upgrade to NEW_VERSION"
git push origin master
```

## Notes

- The PKGBUILD pulls a few PyPI-only deps (`faster-whisper`, `evdev`,
  `sounddevice`) via `pip install --root` during the package step. Standard
  Arch deps (`numpy`, `typer`, `platformdirs`, `portaudio`) come from the
  official repos. This is a pragmatic compromise — strict AUR style would
  package each Python dep separately, but for a daemon with many transitive
  deps this keeps the recipe maintainable.
- The package installs a systemd user unit. Users still need to add
  themselves to the `input` group (`sudo usermod -aG input "$USER"`) and
  re-login.
- After install, `yazses doctor` is the first stop for verification.
