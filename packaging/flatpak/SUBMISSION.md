# Flathub resubmission pack

Everything needed to reopen the Flathub submission, in the order it is needed. Tracked as
[issue #45](https://github.com/MSKazemi/yazses/issues/45).

**Status: one blocker, and it needs a person with a microphone — a screen recording.**
Everything else in this document is done or is a copy-paste.

---

## 1. Why the first attempt was closed

[flathub/flathub#9765](https://github.com/flathub/flathub/pull/9765), **closed 2026-08-13**.
Two separate failures, and it is worth being precise because "Flathub rejected us" is not
what happened — nobody ever reviewed the app.

1. **The `submission-checker` bot auto-closed it**: *"Checklist(s) not completed or
   missing."* The PR body was a custom description rather than Flathub's template. The bot
   does not read prose; it looks for the template's checkboxes.
2. **The checklist was then posted as a comment, with one box left unchecked and
   unanswered**: *"Please attach a video showcasing the application on Linux using the
   Flatpak."*

So the submission has never been assessed on its merits. The permission argument for
`--device=input` — the part that genuinely needed defending — was never even read.

**A third blocker existed and nobody had noticed:** the metainfo had **no `<screenshots>`
block at all**. Flathub's linter flags a desktop-application with none, and the listing
would have rendered with no images in GNOME Software and KDE Discover. Fixed 2026-08-15 and
now guarded by `tests/test_flatpak_metainfo.py`, so the listing cannot silently lose its
images again.

---

## 2. Pre-flight — verify before opening the PR

| # | Check | How | State |
|---|---|---|---|
| 1 | Dependency modules committed | `packaging/flatpak/python3-yazses.json` exists, 45 pinned wheels with hashes | ✅ done |
| 2 | Listing metadata complete | `uv run python -m pytest tests/test_flatpak_metainfo.py` | ✅ 15 passing |
| 3 | Screenshots resolve | every URL in the metainfo points at a file on `main` | ✅ guarded by test |
| 4 | Release entry current | newest `<release>` matches `pyproject.toml` | ✅ guarded by test |
| 5 | AppStream validates | `flatpak run org.freedesktop.appstream-glib validate com.mskazemi.YazSes.metainfo.xml` | ⬜ run on a machine with flatpak |
| 6 | Manifest actually builds | `flatpak-builder --user --install --force-clean build com.mskazemi.YazSes.yml` | ⬜ **must pass before submitting** |
| 7 | Hold-to-talk works **inside the sandbox** | see the shot list below — this is also the video | ⬜ owner |
| 8 | Demo video recorded and uploaded | §4 | ⬜ **owner — the blocker** |

Checks 6 and 7 are not ceremony. Flathub will not accept a manifest that does not build, and
`--device=input` inside the sandbox is the one thing about this app that could fail in a way
no amount of local non-Flatpak testing would reveal.

---

## 3. The pull request

**Base branch must be `new-pr`.** Not `master`. A PR against the wrong base is closed
without review.

Repository: `flathub/flathub` · Branch name: `com.mskazemi.YazSes` · One file added:
`com.mskazemi.YazSes.json` or `.yml` (the manifest from this directory).

### Body — paste verbatim, then fill the two bracketed spots

```markdown
### Please confirm your submission meets all the criteria

- [X] Please describe the application briefly. YazSes is offline, on-device voice dictation for Linux. You hold a key, speak, and release; the audio is transcribed locally with faster-whisper on the CPU and typed into whatever window has focus — editor, browser, terminal or chat. After a one-time model download it needs no network: no account, no API key, no GPU, no subscription. It also transcribes existing recordings to text, SRT, WebVTT, Markdown or JSON, with on-device speaker labelling. Apache-2.0, and the upstream repository is https://github.com/MSKazemi/yazses.
- [X] Please attach a video showcasing the application on Linux using the Flatpak. < PASTE VIDEO LINK >
- [X] The Flatpak ID follows all the rules listed in the [Application ID requirements][appid]. `com.mskazemi.YazSes` is derived from mskazemi.com, a domain I control and which serves the project's documentation at https://mskazemi.com/yazses/.
- [X] I have read and followed all the [Submission requirements][reqs] and the [Submission guide][reqs2] and I agree to them.
- [X] I am an _author/developer_ to the project. **Link:** https://github.com/MSKazemi/yazses

### Notes for the reviewer

Two permissions are unusual for a utility, so here is the reasoning up front.

**`--device=input`** — this is the whole product. Hold-to-talk means noticing that a key is
being held *while another application has focus*, and there is no portal for that; the
`evdev` backend reads `/dev/input/event*`. Without it the app installs and cannot do the one
thing it exists to do. This is precisely the permission Snap's strict confinement could not
grant without a manual `snap connect`, which is why Flatpak is the better home for it.

**`--socket=x11` / `--socket=fallback-x11`** — text injection. The transcript is typed into
the focused window using `xdotool`/`ydotool`/`wtype`, which are bundled. On Wayland,
injection needs `ydotool` with a running `ydotoold`; the app detects what is available at
runtime and falls back to the clipboard when it cannot type, rather than silently dropping
the text.

**`--socket=pulseaudio`** — the microphone.

**No network permission is requested for dictation.** The model is downloaded once, on first
use, and everything after that is local. That is the project's central promise and it is
enforced by the sandbox, not just by policy.

[appid]: https://docs.flathub.org/docs/for-app-authors/requirements#application-id
[reqs]: https://docs.flathub.org/docs/for-app-authors/requirements
[reqs2]: https://docs.flathub.org/docs/for-app-authors/submission
```

> The template's own comment says to tick a box only when the step is complete, and to write
> **N/A with a reason** if one does not apply. Do not tick the video box until the link is
> in it — an unchecked box got the PR closed once; a *falsely* checked one would be worse.

---

## 4. The demo video — shot list

**Flathub's requirement is specific: the application, running on Linux, *as the Flatpak*.**
A polished product reel does not satisfy it. The reviewer is checking that the thing builds
and runs in the sandbox.

- **Length:** 60–90 seconds. Longer is not better.
- **Capture:** the whole screen, not a cropped window — the point is that text lands in a
  *different* application from the one dictating.
- **Audio:** your voice must be audible, so the reviewer can hear the words and see them
  appear. No music.
- **Where to host:** anywhere with a stable public link (a GitHub release asset on this repo,
  or an unlisted YouTube/PeerTube upload). Attaching directly to the PR is fine if it is
  under GitHub's size limit.

| # | Shot | What must be visible | Why it is in the list |
|---|---|---|---|
| 1 | `flatpak install` / already-installed listing | `flatpak list \| grep YazSes` in a terminal | Proves it is *the Flatpak*, not a pip install. Reviewers look for exactly this. |
| 2 | Launch | the app starting, tray icon appearing | It runs in the sandbox. |
| 3 | **Dictate into a text editor** | hold the key, speak a full sentence, release, text appears | The core feature, and the `--device=input` justification made visible. |
| 4 | **Dictate into a second, different app** | e.g. a browser search field or a chat window | Shows injection into an arbitrary focused window — the reason for the X11 socket. |
| 5 | Offline proof | disconnect the network (or show airplane mode), dictate again successfully | The central claim of the project, demonstrated rather than asserted. |
| 6 | A limitation, honestly | e.g. the clipboard fallback when typing is unavailable | Reviewers trust a submission that shows a rough edge far more than one that hides it. Shot 6 is optional; shots 1–5 are not. |

Script for shot 3, which reads well and exercises punctuation:

> "This is YazSes running as a Flatpak. Everything I am saying is being transcribed on this
> laptop's CPU, and nothing is being sent anywhere."

---

## 5. After it is merged

- Flathub builds from the manifest in **their** repo; this directory becomes the upstream
  copy to keep in step. Update both on a release.
- Add the Flathub badge and install line to the README and `docs/install-linux.md`.
- Close #45 with the merged PR link, and note in `docs/platform-support.md` that the Flatpak
  is available — it is currently absent from the Linux install-channel table.
