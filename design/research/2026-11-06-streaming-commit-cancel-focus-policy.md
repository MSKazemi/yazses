# Decision packet: streaming commit/cancel after a focus, caret or unit mismatch

**Status:** RESEARCH DRAFT — REVIEW PENDING. A proposal for a maintainer decision; **not**
an accepted ADR, and it authorises no code, default, dependency or release.
**Issue:** [#796](https://github.com/MSKazemi/yazses/issues/796) (parent #787)
**Builds on:** [Proposed ADR — streaming delivery boundary](2026-11-03-proposed-adr-streaming-delivery-boundary.md)
(invariant 4, "no blind cleanup"), [streaming endpointing and commit safety](2026-11-03-streaming-endpointing-and-commit-safety.md),
and the [replay protocol spec](../specs/streaming-commit-replay-protocol.md) (SR-006, SR-011).
**Code baseline:** `main` @ `8a72bbc6`. Every `file:line` below is at that commit.
**Evidence class:** code reading plus the synthetic fake-screen tests. Nothing here was run
against a real editor, X11, Wayland, macOS or Windows; statements about real editors are
labelled *hypothesis*.

## 1. The question for the maintainer

`[streaming] enabled = true` (off by default, `src/yazses/config.py:331`) types live
partials into the focused application and, at hold release, replaces them blind:
`StreamingInjector.commit()` sends `shift+Left × chars_injected` then types the final text,
and `cancel()` sends `BackSpace × chars_injected` (`src/yazses/inject/streaming.py:68-91`).
`chars_injected` is `len(text)` in Python code points (`streaming.py:66`). Nothing checks
that the field, the caret, or the unit of caret movement is still the one the count was
made against.

`tests/test_streaming_fake_screen.py` pins this with strict xfails. The decision is **which
policy turns them green, and what YazSes does with the final text when the answer is "we
cannot safely clean up"**.

## 2. The xfails this packet is about

| Id | Test (`tests/test_streaming_fake_screen.py`) | Hazard | Today on the fake screen |
|---|---|---|---|
| X2c, X2k | `test_desired_cleanup_after_focus_change_leaves_foreign_text[commit]` / `[cancel]` (`:272-284`) | focus moves A→B after a preview; cleanup acts in B | `"foreignfinal"` / `"foreign"` — `" text"` deleted from B, `"draft"` orphaned in A (`:260-269`) |
| X3 | `test_desired_cancel_after_caret_move_keeps_user_text` (`:302-309`) | user clicks inside their own text; cancel backspaces from the new caret | `"abc draft"` becomes `" draft"` (`:295-299`) |
| X4z, X4r | `test_desired_commit_keeps_text_before_a_multi_unit_preview[zwj-emoji+combining]` / `[rtl-with-harakat]` (`:343-358`) | code points ≠ caret units; shift+Left over-selects | `"keep|"` loses 3 / 1 characters (`:331-340`) |

Out of scope, named so it is not mistaken for covered: **X1**
`test_desired_every_confirmed_delta_reaches_the_reader` (`:221-234`) is the engine's
one-slot pending partial. None of the options below touch it; it needs a queue or a
"replace the preview with the full confirmed prefix" contract in `stt/streaming.py`, a
separate decision.

One gap the current suite does **not** pin, and every option must close: after focus moves
to B, the poll thread keeps typing new partials **into B** (`daemon.py:6678-6685` calls
`inject_partial` with no target check). SR-006's oracle (`target_writes == ()`) forbids it.

## 3. Options

### Option A — focus token checked before every write and before cleanup

Capture an opaque token for "where the preview lives" at the first partial; re-read it
before each later partial and before `commit()`/`cancel()`. On a mismatch or an unreadable
token, **do not select, do not delete, do not type** into the current target; seal and
report an outcome the daemon routes to recovery.

*Granularity, by what the code base can already read:*

| Platform | Window level | Field level | Caret | Existing code |
|---|---|---|---|---|
| X11 | `xdotool getactivewindow` | no (needs AT-SPI) | no | `windowctl/focus.py:196-201` |
| Linux + AT-SPI | via focus event's app | yes — focus events already handled | possible: `Text.caretOffset` (not read today) | `inject/target.py:85-102` |
| Windows | `GetForegroundWindow` | `GUITHREADINFO.hwndFocus` (control, not text field) | no offset | `platform/windows/winfo.py:138-150` |
| macOS | frontmost app (`FocusedAppProvider`) | AX focused element — needs Accessibility permission, *not* read today | AX selected range (*hypothesis*, unverified) | `platform/macos/focused_app.py:61-72` |
| Wayland without AT-SPI | none — no portal for another client's focus | none | none | `windowctl/focus.py:18-20` says so |

A pure window-level token turns **X2** green. It does **not** turn **X3** green: the caret
moved inside the same field, and the token is unchanged. X3 needs a caret check, and the
caret check has a trap: our own typing moves the caret, so a "caret changed" counter fires
on every partial. The check has to be *expected offset vs observed offset* — record
`caretOffset` after each own write, compare before cleanup — which only AT-SPI (and
possibly macOS AX) can do. Everywhere else the caret is unverifiable, and Option A then
falls through to Option C's behaviour for X3.

### Option B — count caret units as grapheme clusters, not code points

Replace `len(text)` with `units(text)`, the number of extended grapheme clusters
([UAX #29](https://www.unicode.org/reports/tr29/) — reference, not re-read 2026-11-06).
Turns **X4z and X4r** green *on the fake screen*, because the fake's approximate cluster
model (`tests/test_streaming_fake_screen.py:55-72`) agrees with UAX #29 on both fixtures
(`"👩‍💻 café"` with a combining acute = 6 clusters; `"سَلام"` = 4).

Risks that make B insufficient on its own:

1. **One unit does not fit two keys.** *Hypothesis to verify per editor:* many editors move
   `shift+Left` by grapheme cluster but delete `BackSpace` by code point inside some
   scripts (combining marks, Arabic harakat, Indic clusters), so `commit` and `cancel`
   may need different counts. The fake screen deletes by cluster too (`:108-113`), so it
   cannot show this.
2. **Editors disagree with UAX #29 and with each other** (terminals moving by cell or code
   point, emoji sequences the editor's font does not join). A count right for one app
   deletes foreign text in another — the guard-rarity rule in ADR-021 cuts the other way
   here: a destructive action needs proof, not a better guess.
3. **Normalisation in flight.** If the injector or the target normalises (NFC/NFD) what
   it receives, the count is of a string the target never held.
4. **No stdlib segmenter.** Python's `unicodedata` has no UAX #29 segmentation. The third-
   party [`regex`](https://pypi.org/project/regex/) module's `\X` does it; at `8a72bbc6`
   `regex` is only in `uv.lock` as a dependency of `whisper-normalizer` (`uv.lock:6462`),
   not a base dependency. Adding it is rule 4 work (latest stable, `>=` floor) and a
   hand-written segmenter is the "hand-written set is the defect" pattern.

B reduces how much is deleted when the count is wrong; it never makes a blind deletion
safe, so it does not touch X2 or X3.

### Option C — abandon the preview on any doubt (no blind cleanup)

When the target cannot be shown unchanged — token mismatch, token unreadable, caret
unverifiable, preview contains anything outside a "provably 1 code point = 1 caret unit"
set — `commit()`/`cancel()` send **no** selection, **no** backspace, and do not type the
final text into the current target. The preview stays where it was; the final text goes to
recovery (clipboard plus a notice, reusing the lost-dictation notice path already on
`main`, or the staged buffer when `[staged]` is on).

Turns **X2**, **X3** and **X4** green by construction, at a cost: the user is left with a
stale preview to remove by hand, and on a target with no probe (Wayland without AT-SPI)
*every* commit abandons — streaming becomes "preview, then paste-by-hand". That is the
honest consequence of the proposed ADR's invariant 4, and the natural follow-on is to
**refuse to start live partial typing when no probe exists** (fall back to batch, say why
once), rather than to abandon at the end.

### Option D — no external preview (for completeness)

Already listed as "defer" in the 2026-11-03 proposed ADR: show partials only in the
overlay; type once at release. X2, X3 and X4 become green trivially (nothing to clean
up). It is the only option that removes the hazard rather than detecting it. It is
mentioned so the comparison is complete, not re-argued here.

## 4. Which xfails each option turns green (fake screen)

| | X2c / X2k focus | X3 caret | X4z / X4r units | new: partial typed into B |
|---|---|---|---|---|
| A (window/field token) | **green** | red | red | **green** if the partial path checks too |
| A + caret offset (AT-SPI only) | **green** | **green** where readable | red | **green** |
| B (grapheme units) | red | red | **green** (fake model only) | red |
| C (abandon on doubt) | **green** | **green** | **green** | **green** |
| A + C (recommended shape) | **green** | **green** (C covers the unverifiable caret) | **green** (C covers non-trivial text) | **green** |
| A + B + C | as A + C, plus fewer abandons for plain-Unicode text on verified targets | | | |
| D | green | green | green | n/a |

**Caveat that applies to every row:** the xfail tests build `StreamingInjector(screen)`
with no probe (`:241-245`, `:288-292`, `:354-357`), and `FakeScreen` has no notion of a
token. None of them turns green without the **fixture** also modelling the probe — e.g.
`FakeScreen.focus_token()` returning `(focused, caret_version)` — and the test passing it
in (or the injector discovering it). That is a fixture change, legitimate because the
fake must model what the real screen reports, but it must be reviewed as such: a fixture
that hands the injector the answer can make any implementation look right.
When an xfail turns green it XPASSes, which fails the suite under `xfail_strict`; the
change must promote it to an ordinary test and delete the paired "current behaviour" test
in the same commit.

## 5. Interface sketch (proposal; no code written)

```python
# src/yazses/inject/focus_token.py — pure, no platform imports
@dataclass(frozen=True)
class FocusToken:
    window: str              # opaque: X11 window id, HWND, macOS pid:window number
    element: str = ""        # opaque per-session element handle; "" = not readable
    caret: int | None = None # caret offset in the element, None = not readable

def same_target(before: FocusToken | None, now: FocusToken | None) -> bool | None:
    """True/False when provable; None when either side cannot tell (treated as False)."""

class Outcome(Enum):
    REPLACED = "replaced"                  # preview selected and replaced (today's path)
    TYPED = "typed"                        # no preview was typed; final typed normally
    ABANDONED_TARGET = "abandoned_target"  # focus/caret provably changed
    ABANDONED_UNKNOWN = "abandoned_unknown"# could not verify; nothing sent
```

```python
# src/yazses/platform/base.py — new Protocol, next to FocusedAppProvider (:468-487)
@runtime_checkable
class FocusTokenProvider(Protocol):
    def token(self) -> FocusToken | None:
        """Cheap, never raises, never returns a title or on-screen text."""
```

```python
# src/yazses/inject/streaming.py
class StreamingInjector:
    def __init__(self, injector, focus_probe: Callable[[], FocusToken | None] | None = None,
                 select_units: Callable[[str], int] = len,
                 delete_units: Callable[[str], int] = len) -> None: ...
    def inject_partial(self, text: str) -> None: ...   # checks token; on mismatch stops previewing
    def commit(self, final_text: str) -> Outcome: ...  # caller routes ABANDONED_* to recovery
    def cancel(self) -> Outcome: ...
```

Daemon touch points: construction at `daemon.py:4034`, the commit at `daemon.py:5390`
(the only caller that must act on the outcome — an `ABANDONED_*` result must not fall
through to "injected"), and the poll loop at `daemon.py:6678-6685`. The ~25 `cancel()`
calls between `daemon.py:4262` and `:4814` can keep ignoring the return value.

Privacy and the offline rule: tokens are opaque ids held in process memory, never titles
or text, never logged above DEBUG, and add no outbound primitive (no change to the
ADR-019 egress inventory).

## 6. Decisions the maintainer needs to make

1. **Default when no probe exists** (`focus_probe=None`): keep today's blind cleanup, or
   fail closed (Option C)? Failing closed changes behaviour for anyone who opted into
   streaming; keeping it leaves X2–X4 red wherever there is no probe.
2. **Where an abandoned final goes:** clipboard + notice, staged buffer, or the current
   target anyway (batch-mode semantics: the text lands wherever focus is at release,
   which is what non-streaming YazSes already does). SR-006's oracle says *no write*;
   batch mode says *write where focus is*. Pick one and record why.
3. **Refuse-to-preview on unprobeable targets** (Wayland without AT-SPI) vs abandon at
   the end.
4. **Option B at all**, and if so: separate select and delete units, and a `regex`
   dependency (base, or an extra with an `len` fallback that then abandons non-ASCII).
5. Whether this lands before or after the `[staged]`+`[streaming]` safety fix the
   2026-11-03 proposal puts first.

**Proposal (not a decision):** A + C, with C as the fail-closed default; refuse live
preview where no probe exists; B deferred until per-editor evidence exists for which unit
each key moves. Rationale: only C removes blind deletion everywhere, A keeps the common
"nothing moved" case working where it can be verified, and B's correctness depends on
editor facts nobody has measured.

## 7. Acceptance tests (all deterministic, fake-screen; to be written with the change)

1. Promote X2c, X2k, X3, X4z, X4r; delete their paired current-behaviour tests
   (`:260-269`, `:295-299`, `:331-340`) or flip them to assert the new outcome.
2. **Partial after focus change:** preview in A, focus B, one more partial → B unchanged,
   A unchanged, `commit()` returns `ABANDONED_TARGET`.
3. **Unchanged target regression:** ASCII and plain-Arabic controls (`"hello"`, `"مرحبا"`)
   with a stable token → still `"keep|X"` and `Outcome.REPLACED` (the feature keeps working).
4. **Probe returns None / raises** → no `shift+Left`, no `BackSpace`, no final typed,
   `ABANDONED_UNKNOWN`; the probe exception does not escape.
5. **A→B→A:** focus returns to A before release with the caret where we left it → REPLACED
   only if the caret offset matches; otherwise abandoned.
6. **Seal still holds:** a late partial after an abandoned commit is dropped (extends
   `:364-371`).
7. **Daemon:** an `ABANDONED_*` outcome at `daemon.py:5390` reaches recovery exactly once,
   records the dictation as not injected, and types nothing.
8. **Option B only:** `units()` over the vendored UAX #29 `GraphemeBreakTest.txt` cases
   (Unicode licence; vendored, since tests are offline), and a property test that
   `select_units(s) <= len(s)` for every string.
9. **Latency:** the probe runs under the injector lock on the hold-release path; X11's
   `xdotool` path costs one subprocess per check (2 s timeout at `inject/target.py:159`).
   Measure before/after on hardware; this is a hardware-QA item, not a CI test.

## 8. Residual risks no option removes

- **TOCTOU:** focus can change between the probe and the keystroke. The lock serialises
  YazSes against itself, not against the user or the window manager.
- **Window-level tokens miss in-window focus moves** (another tab, another field in the
  same window) on X11 and Windows without element-level focus.
- **Fake-screen green is not editor green.** Promotion to a default, or any claim that
  streaming is safe on a named platform, needs the hardware/application verification the
  replay spec's stop/go section requires (`design/specs/streaming-commit-replay-protocol.md` §8).
