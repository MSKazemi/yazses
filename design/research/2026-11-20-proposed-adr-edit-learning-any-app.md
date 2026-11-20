---
description: >-
  Proposed, not accepted. How YazSes could learn a corrected word from any accessible Linux app over AT-SPI, reading only what it just typed, once, never from a password field, and storing only the word pair, encrypted.
---

# Proposed ADR — Learn a corrected word from any accessible app, not only Neovim

**Status:** Proposed for maintainer decision (2026-11-20); **NOT accepted**
**Issue:** none yet. Item M6 of the [November 2026 start plans](2026-11-19-landscape-start-plans.md#m6-learn-vocabulary-from-corrections-in-any-app)
**Research:** [Offline voice tech landscape, November 2026](2026-11-19-offline-voice-tech-landscape.md) (row M6), [GNOME and KDE Wayland assistive-tech limits](2026-11-05-gnome-kde-wayland-assistive-tech-limits.md)
**Governing records:** [ADR-011](../adr/adr-011.md), [ADR-012](../adr/adr-012-self-improvement-loop.md), [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md), [ADR-021](../adr/adr-021-invest-in-error-cost.md), [ADR-v2-079](../adr/adr-v2-079-self-learning-correction-dictionary.md)
**Scope:** design only during the [ADR-030 breadth freeze](../adr/adr-030-agent-era-direction.md)

This is an **ADR candidate in the research directory**. It is deliberately **not a numbered,
accepted ADR**, and it does not edit any generated ADR index. ADR-030 §3 says a proposal
outside the pillars "is written down as a *Proposed* ADR … and stops there", and the
2026-11-01 amendment keeps the freeze for everything except the biosignal switch pipeline.
This record therefore authorises **no code, config key, dependency, default or release**. It
becomes a numbered ADR only if a maintainer adopts it in a separate, reviewed change, after the
freeze is lifted or an amendment names this item.

## Labels used below

| Label | Meaning |
|---|---|
| `[Verified-in-code]` | Read in this repository on branch `research/landscape-2026-11` (base `af322ca1`). Proves what YazSes does, not what a desktop does. |
| `[Verified-primary]` | A primary source was fetched on 2026-11-20: API reference, or upstream toolkit source read from the project's own repository or its official GitHub mirror. |
| `[Secondary]` | A release note, news article or summary. Not the source of the behaviour it describes. |
| `[Unknown]` | Not established. Most items here need a live desktop to settle. |

**Nothing in this record was tested on a desktop.** No AT-SPI call was made, no app was opened.

## Context

### What exists today

`src/yazses/learning/edit_watch.py` holds `EditWatcher`. After an injected dictation it waits
`[learning] edit_capture_delay_s` (default 8 s), reads the text back once through an injected
`read_current_text()` callable, and if the text changed by a char-level distance in
(0, 0.5], calls `on_correction(injected, current)`. It never logs keystrokes. Its only reader is
Neovim's cursor line over a `--listen` socket (`build_neovim_reader`). The daemon builds it only
when the corpus is on (`[learning] enabled`) **and** `[learning] capture_edits = true` **and**
`editor_socket` reaches Neovim, and it calls `watch()` only for a burst that was injected and
classified as plain dictation `[Verified-in-code]` (`core/daemon.py`, the `_edit_watcher` block).

The correction goes to `CorpusWriter.update_correction_for`, which stores the **whole corrected
line** in `correction_text_enc`, encrypted with the corpus key (AES-256-GCM, `learning/crypto.py`,
key file `0600` in a `0700` directory) `[Verified-in-code]`. `corrdict/table.py` later diffs
`final_text` against `correction_text` with `corrdict/mine.py::pairs_from_texts`. That function
keeps only `replace` spans of at most three words a side whose similarity is at least 0.6, so a
clause rewrite is dropped. A pair becomes a rule only at `min_support` repeats with no tied rival
`[Verified-in-code]`.

### Why the reader is the limit

Most people do not dictate into Neovim. A misrecognised name fixed by hand in a browser text
box, a chat client or a GTK editor teaches YazSes nothing today. A competitor ships the obvious
fix: OpenWhispr's Linux text monitor "uses AT-SPI2 to detect text field changes after paste"
for "auto-learn correction monitoring" `[Secondary]` ([OpenWhispr releases](https://github.com/OpenWhispr/openwhispr/releases)).
The release notes seen say nothing about opt-in or password fields.

YazSes already speaks AT-SPI. `platform/linux/atspi_tree.py` reads the active window for the
Voice Pilot and Screen-Grounded Dictation. It deliberately reads **no text content from an
editable field**, and never from the roles `"password text"` or `"terminal"`
(`_SECRET_ROLES`) `[Verified-in-code]`. `inject/target.py::AtspiFocusTracker` follows focus to
learn the focused widget's role and `STATE_EDITABLE` `[Verified-in-code]`.

**This proposal crosses that line on purpose.** Reading an editable field's content is exactly
what `atspi_tree.py` refuses. It is a new privacy surface, which is why it needs its own record
and its own switch, and why its limits below are stricter than the Neovim path's.

## Proposed decision (conditional, **not yet binding**)

### 1. A platform Protocol, used as `EditWatcher`'s reader

Add one Protocol to `src/yazses/platform/base.py`, implemented first under
`platform/linux/` over AT-SPI2, with macOS (AX API) and Windows (UI Automation) later:

```python
@runtime_checkable
class TypedRegionReader(Protocol):
    def mark(self, injected_text: str) -> object | None:
        """Called once, right after injection. Records where the text went: the focused
        accessible, its app, and the caret offset. Reads no text. None = do not watch."""

    def read(self, mark: object) -> str | None:
        """Called once, after the delay. Returns the bounded window around that region,
        or None. Never raises."""
```

The daemon wraps the pair into the `read_current_text` callable `EditWatcher` already takes, so
**the diff logic in `edit_watch.py` stays as it is** and its existing tests keep holding. The
only change on that side is a per-watch reader: today `EditWatcher` holds one reader for its
lifetime, and an any-app reader needs the mark taken at injection time. That is a small,
backwards-compatible signature change (`watch(text, reader=None)`), tested with the existing
fake-timer pattern.

As with `AccessibilityBackend`, `Platform` gets a factory that is `None` where no backend
exists, with a stated reason, so macOS, Windows and the BSDs stay dormant rather than failing.

### 2. Read only the region YazSes just typed, once, after a delay

- **`mark` reads no text.** It records the focused accessible (an AT-SPI object reference),
  its process id and application name (`Atspi.Accessible.get_process_id`, `get_application`
  `[Verified-primary]`), the caret offset after injection (`Atspi.Text.get_caret_offset`
  `[Verified-primary]`), and the injected length in characters. When any check in §3 fails,
  `mark` returns `None` and nothing is watched.
- **`read` happens once**, `edit_capture_delay_s` later. It reads at most
  `len(injected) + 2 × margin` characters around the recorded span with
  `Atspi.Text.get_text(start, end)` `[Verified-primary]`. The margin is small, at most 16
  characters, so a correction that changes length still falls inside the window but
  neighbouring text mostly does not. It never calls `get_character_count` to read a whole
  document, and never walks the tree.
- **Re-check before reading.** The object must not be `ATSPI_STATE_DEFUNCT` ("no longer has a
  valid backing widget" `[Verified-primary]`), must belong to the same process, and must still
  pass every check in §3. If the object is gone, the read is skipped. It is never re-resolved
  by searching.
- **A pure function picks the span.** `locate_region(injected, window) -> str | None` (new, pure,
  beside `edit_watch.py`) aligns the injected text inside the window and returns the matching
  span, or `None` when no span is within the existing 0.5 distance bound. The window string
  is dropped as soon as this returns. It is never logged, stored, sent to an event or put in
  a notification.

Whether the caret offset read right after injection is the end of the injected text depends on
the injector. `ydotool`, the portal and `wtype` deliver keys asynchronously `[Unknown]`. The
build must measure this per backend. Until it does, a mark taken while injection may still be in
flight is refused, not guessed.

### 3. Never read a secret

A field is read only when **all** of these hold at both `mark` and `read`:

1. The role is not `ATSPI_ROLE_PASSWORD_TEXT` ("A text object uses for passwords, or other
   places where the text content is not shown visibly to the user") and not
   `ATSPI_ROLE_TERMINAL` `[Verified-primary]` ([Atspi.Role](https://docs.gtk.org/atspi2/enum.Role.html)).
   The build reuses `atspi_tree.py`'s `_SECRET_ROLES` rather than a second list. A terminal is
   excluded because its Text interface is the scrollback, as that module already says.
2. The state set contains `ATSPI_STATE_EDITABLE` and not `ATSPI_STATE_READ_ONLY`
   ([Atspi.StateType](https://docs.gtk.org/atspi2/enum.StateType.html)) `[Verified-primary]`.
3. The object implements the Text interface (`get_text_iface` `[Verified-primary]`).
4. The application is not on the deny-list (§3.1).
5. `inject/target.py` did not report the injection target as a password field for this burst.

**AT-SPI has no "secret" state.** The StateType enumeration has nothing for password, protected
or masked content. `SENSITIVE` means responsive to interaction `[Verified-primary]`. So the role
is the only signal the bus gives, and it is only as good as each toolkit's mapping:

| Toolkit | How a password field becomes `PASSWORD_TEXT` | Label |
|---|---|---|
| GTK 4 | `GtkPasswordEntry` documents the ARIA-style `GTK_ACCESSIBLE_ROLE_TEXT_BOX`. The AT-SPI bridge turns `TEXT_BOX` into `ATSPI_ROLE_PASSWORD_TEXT` only when the `GtkText` input purpose is `PASSWORD` or `PIN`. Otherwise it is plain `ATSPI_ROLE_TEXT` | `[Verified-primary]` ([GtkPasswordEntry](https://docs.gtk.org/gtk4/class.PasswordEntry.html); [gtkatspiutils.c](https://github.com/GNOME/gtk/blob/main/gtk/a11y/gtkatspiutils.c), [gtkaccessible.c](https://github.com/GNOME/gtk/blob/main/gtk/gtkaccessible.c) `gtk_accessible_is_password_text`) |
| Qt 5/6 | `AtSpiAdaptor::getRole` returns `ATSPI_ROLE_PASSWORD_TEXT` for `QAccessible::EditableText` with `state().passwordEdit` | `[Verified-primary]` ([atspiadaptor.cpp](https://github.com/qt/qtbase/blob/dev/src/gui/accessible/linux/atspiadaptor.cpp)) |
| Chromium (and Electron, by inheritance) | A text field or search box with the `kProtected` state maps to `ATK_ROLE_PASSWORD_TEXT`, else `ATK_ROLE_ENTRY` | `[Verified-primary]` for Chromium ([ax_platform_node_auralinux.cc](https://github.com/chromium/chromium/blob/main/ui/accessibility/platform/ax_platform_node_auralinux.cc)). Electron inheriting it: `[Unknown]` (assumed, since Electron embeds Chromium) |
| Firefox (Gecko) | `RoleMap.h` maps its `PASSWORD_TEXT` role to `ATK_ROLE_PASSWORD_TEXT` | `[Verified-primary]`, read from the archived [gecko-dev mirror](https://github.com/mozilla/gecko-dev/blob/master/accessible/base/RoleMap.h); current Firefox source not re-checked |
| GTK 3 | Through ATK. A 2019 GTK commit gave password entries the password-text role | `[Secondary]` (commit-list mail only) |

The table shows the gap. A field that masks its text **without telling the toolkit** is not
caught by role. Examples: a GTK 4 `GtkText` with visibility off but a free-form purpose, a custom
widget, or a web page that hides an ordinary text input with CSS `[Unknown]` how common these
are. Hence the defence in depth:

- **The window is bounded to what YazSes typed.** If YazSes typed into a mis-labelled password
  field, the dictated words were already there. The danger is the margin, which is why it stays
  at 16 characters or fewer and is dropped after `locate_region`.
- **A masked-text skip.** If the window is a run of one repeated mask glyph (`•`, `●`, `*`),
  the read is discarded. This is a silent skip and never a prompt, so AGENTS.md rule 9 (a guard
  that interrupts is judged on how rarely it fires) does not apply. It is a backstop, not the
  guard.
- **Only plain dictation.** As today, only a burst classified `dictate` and actually injected is
  watched. Commands, secrets spelled by voice and `[staged]` buffers are not.

#### 3.1 The deny-list

A built-in list that the user can extend but not shrink, matched on the AT-SPI application name
and the process executable name (`/proc/<pid>/comm` on Linux). The draft list is password
managers (KeePassXC, 1Password, Bitwarden, Proton Pass, Seahorse), authentication prompts
(`pinentry-*`, polkit agents, GNOME Shell's own prompts), and terminal emulators, which are
already excluded by role. Whether each one reports a stable application name over AT-SPI is
`[Unknown]` and is a build-time check. The user's additions go in a list key (§6).

### 4. Store only the word pair, through the existing encrypted store

The Neovim path stores the whole corrected line. **This path must not:** an arbitrary app's line
can hold text the user never dictated.

After `locate_region`, the daemon runs the existing pure `pairs_from_texts(injected, span)`. That
gives at most a few `(wrong, right)` phrase pairs of three words or fewer a side, with
similarity of at least 0.6. It then **rebuilds** the "corrected" text by applying only those
pairs to the injected text, and passes that to `update_correction_for` with a distinct `signal`
value marking the accessibility source. The result:

- What reaches `correction_text_enc` is the dictated sentence plus the user's replacement words,
  encrypted with the existing corpus key. No character from outside the region YazSes typed,
  and no unpaired edit inside it, is ever written.
- `corrdict/table.py` mines it unchanged, because it already diffs `final_text` against
  `correction_text`.
- No pair, no write. A rewrite, a deletion or an insertion yields no pair under the existing
  rules, so nothing is stored.
- `[learning] redact_patterns` apply as for every other corpus field.

Whether the source tag belongs in the existing `edit_signal` column or in a new nullable column
is an open schema question for the build. Either way it must stay readable by
`yazses corpus status` without decrypting text.

### 5. Review and delete, and a visible first time

- **The first time** this path stores a pair in a session, the tray or overlay shows a short,
  local notification: "Learned a correction in *app name*. Review: `yazses corpus edits`".
  It names the app, never the words. After that it is silent, apart from a count in
  `yazses corpus status`.
- **Review:** a new `yazses corpus edits` lists the learned pairs, decrypted locally, with their
  source and time. `--delete <id>` deletes one, and `--source accessibility --delete-all`
  deletes all of this path's pairs. New CLI surface is L3 work. Until it exists,
  `yazses corpus forget` and `corpus destroy` already delete the material.
- **Turning the switch off** stops reading at once. It does not delete what was learned; the
  disable message says how to.

### 6. Off by default, behind its own key

Two new keys in `[learning]`, dormant (AGENTS.md rule 2), both L3:

- `capture_edits_accessibility = false`. Separate from `capture_edits`, so a Neovim user's
  existing opt-in never widens into reading every app. It also requires `[learning] enabled`,
  as the Neovim path does.
- `edit_capture_deny_apps = []` — the user's additions to the built-in deny-list.

`pyatspi` stays an OS package imported lazily inside the reader (rule 3), as in
`atspi_tree.py`. No PyPI dependency is added. Turning accessibility on system-wide is not
YazSes's call (§7).

### 7. It stays inside ADR-019's "learning corpus never leaves" category

- **No new egress.** AT-SPI is a D-Bus service. The accessibility bus, like the session bus, is
  a per-user AF_UNIX socket. `tests/test_egress_inventory.py` does not scan D-Bus, and its own
  comment records that the session bus "is an AF_UNIX socket owned by the user", the transport
  `inject/portal.py` already uses `[Verified-in-code]`. Reading a widget's text from another
  local process is an **inbound** read on this machine. It sends nothing. The build should still
  add a test pinning that the reader module imports no network primitive, in the style of
  `test_the_ble_backend_opens_no_socket`.
- **ADR-019 §3** says the learning corpus "may never escalate, whatever the guardrails". What
  this path stores *is* learning-corpus material: it goes into the same encrypted store, under
  the same key, and inherits that boundary with no new exception. No future cloud path,
  including ADR-019 §2's consented escalation, may read it.
- **ADR-011 §9, "no ambient capture".** The read happens only after the user dictated, only
  once, and only on the text that dictation produced. It is not background indexing. A design
  that read on every text-changed event, or watched fields YazSes did not type into, would
  breach §9 and is rejected below.
- **Third parties.** A shared document or chat thread can hold other people's words next to the
  dictated region. The 16-character margin and the "store only the pair" rule are what keep them
  out. That is a privacy argument the build must test, not assume (T6).

### 8. Do not switch accessibility on behind the user's back

Chromium enables its ATK bridge only when `ACCESSIBILITY_ENABLED`, `GNOME_ACCESSIBILITY` or
`QT_ACCESSIBILITY` is `1`, or when `org.a11y.Status.IsEnabled` on the accessibility bus is true,
or when the GNOME setting `toolkit-accessibility` is true. It checks once, at startup
`[Verified-primary]` ([atk_util_auralinux.cc](https://github.com/chromium/chromium/blob/main/ui/accessibility/platform/atk_util_auralinux.cc)).
Qt does the same with `QT_LINUX_ACCESSIBILITY_ALWAYS_ON`, `ScreenReaderEnabled` or `IsEnabled`
`[Verified-primary]` (Qt `dbusconnection.cpp`, same directory as above). YazSes could set
`IsEnabled` and make many more apps readable. **It must not do so silently.** That flag changes
every application's behaviour and performance on the desktop, not just YazSes's. If the build
offers it, it is a separate, explained, user-run step (a `doctor` hint), never a side effect of
the learning switch.

## Toolkit coverage risk

The feature only works where text is exposed. Coverage is the main reason to expect it to be
patchy:

| Surface | Exposes text over AT-SPI? | Label |
|---|---|---|
| GTK 4 | Directly over D-Bus (`gtk4/gtk/a11y`) | `[Verified-primary]` ([AT-SPI toolkits](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/toolkits.html)) |
| GTK 3, Firefox, LibreOffice, Java Swing | Through ATK (Swing via java-atk-wrapper) | `[Verified-primary]` (same page) |
| Qt 5/6 | Over D-Bus, **only when accessibility is enabled** (§8) | `[Verified-primary]` (Qt source); KDE default `[Unknown]` |
| Chromium | Through ATK and AT-SPI, **only when accessibility is enabled at startup** (§8) | `[Verified-primary]` |
| Electron apps (VS Code, Slack, Discord, Obsidian …) | Electron enables accessibility "in the presence of assistive technology" and offers `app.setAccessibilitySupportEnabled`; its docs say nothing about Linux | `[Verified-primary]` for the doc ([Electron accessibility](https://www.electronjs.org/docs/latest/tutorial/accessibility)); Linux behaviour `[Unknown]`, assumed to follow Chromium |
| Terminals | Excluded by role (§3) | by design |
| Wayland | AT-SPI is D-Bus, not compositor API, so text reading should be compositor-independent. Only coordinates are unreliable | `[Secondary]` per [the #818 note](2026-11-05-gnome-kde-wayland-assistive-tech-limits.md); hardware `[Unknown]` |

What this means for the claim: the feature can be described only as "learns from corrections
in apps that expose their text to accessibility tools". The docs must not say "any app" until a
hardware matrix (the #818 checklist plus a read-back row) records which apps actually work.
That is ADR-030 Pillar 1.

**macOS and Windows, later.** UI Automation gives the same guard in a stronger form. An edit
control with `UIA_IsPasswordPropertyId` true "must return an error" when `Value` is queried
`[Verified-primary]` ([Edit control type](https://learn.microsoft.com/windows/win32/winauto/uiauto-supporteditcontroltype);
[property ids](https://learn.microsoft.com/windows/win32/winauto/uiauto-automation-element-propids)).
On macOS, password fields carry the `AXSecureTextField` subrole. Gecko's role map pairs
`PASSWORD_TEXT` with `NSAccessibilitySecureTextFieldSubrole` `[Verified-primary]` (mirror above),
but Apple's own reference page for the constant was not found `[Unknown]`. Both need their own
Protocol implementation and their own hardware record. Neither is in scope for the first build.

## Alternatives

| Alternative | Decision at proposal stage | Consequence |
|---|---|---|
| Keep Neovim-only | Status quo during the freeze | No new surface; learning stays limited to one editor |
| Listen to AT-SPI `text-changed` events continuously | Reject | Ambient capture (ADR-011 §9): reads edits YazSes did not cause, keystroke-adjacent |
| Read the whole field or document once | Reject | Captures unrelated and third-party text to get one word pair |
| Store the full corrected line, as the Neovim path does | Reject for this path | Imports text from arbitrary apps into the corpus |
| Clipboard or OCR read-back | Reject | Clipboard clobbers user state; OCR adds a heavy dependency and reads the whole screen |
| Set `org.a11y.Status.IsEnabled` automatically to widen coverage | Reject | A desktop-wide side effect the user did not choose (§8) |
| This proposal: one bounded read, role and deny-list guards, pair-only storage | Propose | Patchy coverage, but every read is attributable to one dictation |

## Invariants for approval

- **I1** No text is read unless `[learning] enabled` and `capture_edits_accessibility` are both
  true. A default install loads no reader code.
- **I2** At most one `get_text` call per injected dictation, with a window of at most
  `len(injected) + 32` characters, after the delay.
- **I3** No read from `PASSWORD_TEXT` or `TERMINAL` roles, from non-editable or read-only
  objects, from a defunct object, or from a deny-listed app, checked at mark and at read.
- **I4** The window string is never logged, stored, emitted or shown. Only the rebuilt
  correction (injected text plus mined pairs) is written, encrypted, and only when there is at
  least one pair.
- **I5** No new egress: the reader module imports no network primitive, and the corpus
  boundary of ADR-019 §3 holds unchanged.
- **I6** The first stored pair per session is announced, by app name only. Every stored pair
  can be listed and deleted.
- **I7** YazSes never changes the desktop's accessibility enablement as a side effect.

## Test plan (all offline, with a fake reader)

Every test runs in the normal suite without pyatspi, a desktop or a bus.

- **T1 Fake reader conformance.** A `FakeTypedRegionReader` holds a scripted field: role,
  states, app name, text and caret. It records every call. Tests assert `mark` reads no text and
  that `read` is called at most once per watch (I2). The existing `timer_factory` injection in
  `EditWatcher` drives time.
- **T2 Secret guards.** Parametrised over `password text`, `terminal`, no `EDITABLE`,
  `READ_ONLY`, `DEFUNCT` at read time, a deny-listed app, an app added through
  `edit_capture_deny_apps`, and a target that `inject/target.py` flagged as a password. Each
  must produce zero reads and zero writes (I3).
- **T3 Masked text.** A window of `••••••` is discarded without a write.
- **T4 `locate_region` (pure).** Correction inside the span, a length-changing correction, a
  correction plus unrelated neighbouring text, the region deleted, the region moved beyond the
  margin, Unicode (combining marks, CJK, emoji) with offsets in characters.
- **T5 Pair-only storage.** With a fake corpus, a field reading "Dear Ana, the yaz says build is
  green — Bob's private note" after YazSes typed "the yaz says build is green" stores exactly
  "the YazSes build is green". It stores nothing at all from "Dear Ana" or "Bob's private note",
  and nothing when the change is a rewrite (I4).
- **T6 Neighbouring third-party text.** A window whose margin holds another person's words
  never contributes a character to the store, whatever the edit.
- **T7 No egress.** The reader module and its Linux implementation import no network primitive
  (extends `tests/test_egress_inventory.py`).
- **T8 Dormant default.** With default config, the daemon builds no reader and imports no
  reader module (pattern of `tests/test_biosignal_default_stays_out.py`).
- **T9 First-time indicator.** The first stored pair raises one notification naming the app and
  not the words. The second does not.
- **T10 Linux backend, mocked.** A fake `pyatspi` module, as in the existing AT-SPI tests,
  checks the role and state names used and that a binding missing a state constant answers
  "do not read" rather than "safe".
- **Hardware (not CI):** a row per app in the #818 checklist (GTK 4 editor, Qt editor, Firefox,
  Chromium, one Electron app, LibreOffice), on GNOME and KDE Wayland and on X11. It records
  whether the read-back works, whether a password field is refused, and the caret-after-
  injection offset per injector.

## Consequences, risks and unknowns

**Benefits:** corrections made where people actually type start feeding the existing,
high-precision ADR-v2-079 miner. It also matches a competitor feature on the platform YazSes
leads, with tighter limits than any seen documented.

**Costs:** a new privacy surface that needs its own disclosure page, a hardware matrix, and
review of the new CLI and config keys (L3).

**Risks:**

- Patchy coverage, especially in Electron and Chromium apps where accessibility is off.
- A mis-labelled masked field the role check cannot see.
- Caret offsets that do not match the injected span on asynchronous injectors.
- Users mistaking "learns from my edits" for keystroke logging. The disclosure must say
  plainly what is read and when.

**Unknowns:** KDE's default accessibility enablement, Electron's Linux behaviour, deny-list
app names on the bus, and real false-capture rates.

## Review / acceptance gate

This needs a maintainer's explicit decision, and either the ADR-030 freeze lifted or an
amendment naming this item. If accepted: allocate a real ADR number, regenerate indexes with
their generators, and open a scoped delivery issue for the Linux build alone. **Until then,
this is a proposed research document, and runtime behaviour is unchanged.**

## Sources (fetched 2026-11-20)

- AT-SPI2 reference: [Atspi.Role](https://docs.gtk.org/atspi2/enum.Role.html), [Atspi.StateType](https://docs.gtk.org/atspi2/enum.StateType.html), [Atspi.Text](https://docs.gtk.org/atspi2/iface.Text.html), [Atspi.Accessible](https://docs.gtk.org/atspi2/class.Accessible.html) (library 2.52). One quirk: the `get_text_iface` entry's description says "AtspiTable", which looks like a documentation error.
- [AT-SPI toolkits page](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/toolkits.html).
- GTK 4: [GtkPasswordEntry](https://docs.gtk.org/gtk4/class.PasswordEntry.html) (docs for 4.24.1); source [gtkatspiutils.c](https://github.com/GNOME/gtk/blob/main/gtk/a11y/gtkatspiutils.c) and [gtkaccessible.c](https://github.com/GNOME/gtk/blob/main/gtk/gtkaccessible.c), read from the GNOME GitHub mirror, `main`, on 2026-11-20.
- Qt: [atspiadaptor.cpp](https://github.com/qt/qtbase/blob/dev/src/gui/accessible/linux/atspiadaptor.cpp) and `dbusconnection.cpp` in the same directory, `dev`, on 2026-11-20.
- Chromium: [ax_platform_node_auralinux.cc](https://github.com/chromium/chromium/blob/main/ui/accessibility/platform/ax_platform_node_auralinux.cc), [atk_util_auralinux.cc](https://github.com/chromium/chromium/blob/main/ui/accessibility/platform/atk_util_auralinux.cc), `main`, on 2026-11-20.
- Gecko: [RoleMap.h](https://github.com/mozilla/gecko-dev/blob/master/accessible/base/RoleMap.h), the archived gecko-dev mirror (not current Firefox).
- [Electron accessibility tutorial](https://www.electronjs.org/docs/latest/tutorial/accessibility).
- Microsoft: [Edit control type](https://learn.microsoft.com/windows/win32/winauto/uiauto-supporteditcontroltype), [Automation element property identifiers](https://learn.microsoft.com/windows/win32/winauto/uiauto-automation-element-propids).
- [OpenWhispr releases](https://github.com/OpenWhispr/openwhispr/releases) (secondary for this purpose).

Source code was read as fetched at the date given. A line can move, so the build must
re-verify each mapping against the toolkit versions it supports.
