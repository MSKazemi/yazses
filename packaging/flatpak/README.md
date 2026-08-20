# YazSes on Flathub — packaging notes

Flathub is the biggest desktop-Linux distribution surface: the default or one-click store
on Fedora Workstation, Linux Mint, elementary, Pop!\_OS and SteamOS, and every app gets an
indexed page on flathub.org. It is tracked as [issue #45](https://github.com/MSKazemi/yazses/issues/45).

It is also the right target *because* Debian is not. Debian requires every dependency to be
packaged in Debian, and neither `faster-whisper` nor `ctranslate2` is — so a Debian package
means packaging a C++ inference library first, then two Python packages, then finding a
Debian Developer to sponsor all three. A Flatpak bundles its own dependencies, so that
entire problem disappears.

## Files here

| File | What it is |
|---|---|
| `com.mskazemi.YazSes.yml` | The build manifest |
| `com.mskazemi.YazSes.metainfo.xml` | The store listing — description, categories, limitations |
| `com.mskazemi.YazSes.desktop` | The launcher the metainfo's `<launchable>` names. Without it the app has no app-grid entry and Flathub's linter rejects the listing |
| `com.mskazemi.YazSes.svg` | The app icon, installed as `hicolor/scalable/apps/<app-id>.svg`. A byte copy of `contrib/icons/yazses.svg` — a Flathub repository is flat and cannot reach into `contrib/`; guarded against drift by `tests/test_icon_assets.py` |
| `python3-yazses.json` | Generated dependency modules — 45 pinned wheels with hashes. Committed; regenerate via the Flatpak workflow, never by hand |
| `SUBMISSION.md` | The resubmission pack: why flathub#9765 closed, the filled-in PR body, and the demo-video shot list |

## The app ID is permanent

`com.mskazemi.YazSes`, from a domain the maintainer controls, as Flathub requires. It cannot
be changed after publication without shipping a different app and orphaning every install.
Decide once.

## The permission question decides everything

This is not a packaging problem, it is a sandbox problem, and it must be settled before the
submission rather than after a rejection.

| Permission | Why | Risk |
|---|---|---|
| `--socket=pulseaudio` | Microphone. Without it there is no audio. | routine |
| `--device=input` | **Hold-to-talk.** `evdev` reads `/dev/input/event*`. There is no portal for "notice a key held while another app has focus". | reviewed, but this is exactly what Snap could not grant — see [#44](https://github.com/MSKazemi/yazses/issues/44) |
| `--socket=x11` / `--socket=wayland` | Typing the transcript into the focused window. | **contested** — synthesising input into applications outside the sandbox is precisely what sandboxing prevents |
| `--share=network` | The one-time speech-model download. Inference never uses it. | routine, but state it plainly |

**If Flathub declines the injection permissions, the package still ships** — set
`[injection] backend = "clipboard"` and the transcript goes to the clipboard for the user to
paste. That is a real degradation of the product and it belongs in the store description,
not in a footnote. Do not ship a build that cannot type and describe it as if it can.

## Before submitting

1. Generate the dependency modules with
   [flatpak-pip-generator](https://github.com/flatpak/flatpak-builder-tools):

   ```sh
   python3 flatpak-pip-generator --runtime=org.kde.Sdk//6.7 yazses --output python3-yazses
   ```

   Regenerate whenever the base dependencies in `pyproject.toml` change. Do not hand-edit
   the result — a generated file is reviewable as a regeneration, a hand-edited one is not.

2. Build and install locally on a real desktop:

   ```sh
   flatpak-builder --user --install --force-clean build com.mskazemi.YazSes.yml
   ```

3. Verify the two things that actually matter, in a real session:
   - hold-to-talk fires (this is the whole product)
   - the transcript lands in another application's text field

4. Validate the listing metadata:

   ```sh
   flatpak run org.freedesktop.appstream-glib validate com.mskazemi.YazSes.metainfo.xml
   ```

   ⚠️ This reads the XML file and nothing else. It passed for months on a build that
   installed neither the metainfo nor the desktop file the metainfo promises, which is a
   listing with no icon and no app-grid entry. What the build actually puts in `/app` is
   guarded by `tests/test_flatpak_metainfo.py`; run both.

5. Submit a pull request to [flathub/flathub](https://github.com/flathub/flathub) **against
   the `new-pr` base branch**, using **their template verbatim** — see
   [SUBMISSION.md](SUBMISSION.md), which carries the filled-in body ready to paste. The first
   attempt ([flathub#9765](https://github.com/flathub/flathub/pull/9765)) was auto-closed by
   the submission-checker bot for using a custom description instead of the template, so this
   is not a formality. Reviewers ask about `--device=input` and the injection sockets every
   time; answering before being asked shortens the review considerably.

## Runtime choice

`org.kde.Platform` rather than the GNOME runtime, because it carries Qt 6 and PySide6 —
which the voice-activity overlay and tray icon need — is in the base install. Pulling
PySide6 through pip against the GNOME runtime means building Qt inside the sandbox.
