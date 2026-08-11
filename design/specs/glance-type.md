# Spec: Glance-Type — Coarse Gaze-Targeted Dictation

| Field | Value |
|---|---|
| **ID** | spec-glance-type |
| **Status** | Proposed |
| **Date** | 2026-06-14 |
| **Module** | `src/yazses/platform/gaze/` (new, optional) |
| **Vision card** | the Glance-Type vision card (internal) |
| **Dossier** | the 2026-06-14 ten-feature SoA dossier (internal) (Glance-Type block, verdict row #2) |
| **Related** | ADR-005 (InputBackend Protocol pattern), ADR-v04-003 (optional-backend / config-gated dep pattern), ADR-011 (offline / no-capture premise) |

---

## Context

YazSes dictation always injects into the **focused window**. In a multi-pane workflow (editor + terminal + chat) the user must break hold-to-talk flow to grab the mouse and re-aim the caret before dictating into a different pane — the exact hand-trip hold-to-talk exists to abolish.

The seed feature **Glance-Type** proposes fusing offline webcam gaze with the voice trigger so dictation lands where the user is *looking*. The state-of-the-art sweep makes the central constraint non-negotiable:

- **Webcam gaze is coarse.** Best webcam→screen mapping is **~3.2–3.3° / ~50 mm RMSE with a still head**, degrading to **5.1° / 80 mm under head motion** `[paper:PMC11019238, tier2, A]`. A text line is ~4–5 mm; 50 mm is ten lines. A dedicated IR tracker (Tobii) reaches 15 mm / 0.9° — webcams do not.
- **Calibration is heavy** for the accurate variants — GazeRecorder reaches ~17.5 mm but needs **~30 calibration points** and loses ~9% under motion; WebGazer (~40 mm) self-calibrates via clicks but is validated only for **coarse, wide regions** `[paper:PMC11019238, tier2, B]` `[web:WebGazer+PMC10841511, tier2/3, B]`.
- **Perception is cheap and real-time.** MediaPipe face/iris runs **90+ FPS at ~5% CPU** but **does not output gaze** — a regressor must be bolted on `[doc:Google-Research, tier3, B]`. L2CS-Net gives **3.92° angular error** on MPIIGaze from plain RGB, pip-installable `[paper:arXiv2203.03339, tier2, A]`.

**The accuracy ceiling is the central constraint of this spec.** It is real-time and CPU-feasible, but **accuracy-bounded**: webcam gaze can reliably resolve *which pane / window / field* you are looking at, not *which line or caret position*. Designing for caret precision would over-promise and feel broken. This spec therefore re-scopes the feature before any code is written.

## Decision

**Re-scope Glance-Type to coarse "look-to-pane / look-to-field" targeting, NOT caret placement.** Concretely:

1. **New optional gaze module** `src/yazses/platform/gaze/`, behind a `GazeBackend` Protocol in the same shape as the other platform backends (`HotkeyBackend`, `InjectorBackend` in `platform/base.py`). Built on **MediaPipe Face Landmarker** (real-time landmarks + head pose) plus a **light per-user gaze→screen regressor** (ridge / low-order polynomial on iris-centre + head-pose features), with **WebGazer-style implicit click calibration** as an optional refinement layer. Fully dormant unless `[gaze] enabled = true`.

2. **A calibration step.** A short **5–9-point** explicit wizard (mirroring `accessibility/enroll.py`) fits the per-user regressor and persists it to a calibration-data file. We deliberately do *not* require the ~30-point GazeRecorder ceremony `[paper:PMC11019238]` — coarse targeting does not need its precision, and the friction would kill adoption (Vision card LOFA-3).

3. **Fuse with the voice trigger at a single instant.** On `core/daemon.py::_on_hold_start`, capture **one** gaze snapshot (optionally a short multi-frame median), hit-test it against window/pane geometry, and if confidence clears a threshold, set the dictation **target = the pane/window under gaze** (raise/focus it) *before* recording begins. Snapping at one instant — when the head is briefly still — is the mitigation for the 50→80 mm head-motion collapse `[paper:PMC11019238]`. There is **no continuous tracking**; gaze is sampled once per utterance, not held.

4. **Always-safe fallback.** When confidence is below threshold, or geometry is unavailable, or gaze is disabled, the target is exactly today's behaviour — the **focused window**. By construction the feature is never worse than no feature: a low-confidence glance is a no-op, not a misfire into the wrong pane.

5. **CPU/real-time feasible but accuracy-bounded.** Perception fits the existing CPU budget `[doc:Google-Research]`; the bound is spatial resolution, not latency. Targets are sized to the pane grain (≥ the ~50 mm error radius), never the caret.

This mirrors the optional-backend pattern of ADR-v04-003 (a new capability, config-gated, dormant by default, dep behind an extra, no change to the core pipeline) and the abstraction-seam intent of ADR-005 (formalise the seam now so a future precision jump is a single-module addition, not a refactor).

### `GazeBackend` Protocol (sketch)

Added to `src/yazses/platform/base.py`, same `@runtime_checkable Protocol` style as the existing backends:

```python
@dataclass(frozen=True)
class GazePoint:
    x: float           # screen pixels (0..screen_w)
    y: float           # screen pixels (0..screen_h)
    confidence: float  # 0..1; below [gaze] confidence_threshold → ignore, use focused window
    ts: float

@runtime_checkable
class GazeBackend(Protocol):
    """Offline webcam gaze estimator. Optional; dormant unless [gaze] enabled."""

    def start(self) -> None:
        """Open the webcam and begin landmark inference on a background thread."""

    def stop(self) -> None:
        """Release the webcam. Frames are never stored or transmitted."""

    def snapshot(self) -> GazePoint | None:
        """Return the current best gaze point, or None if no confident estimate.
        Called once at hold-start — NOT polled continuously."""

    def calibrate(self, points: list[tuple[float, float]]) -> bool:
        """Fit/refit the per-user regressor from on-screen calibration targets.
        Persists the artifact to [gaze] calibration_path. Returns success."""
```

A `PaneResolver` (platform-specific) maps a `GazePoint` to a target window/pane using window-manager geometry (X11 `_NET_*` / AT-SPI, Wayland portal where available, macOS Accessibility/CG, Windows UIA). On geometry failure it returns `None` → focused-window fallback.

## Rationale

**Coarse is the only honest scope.** The webcam error envelope (~50–80 mm) `[paper:PMC11019238, tier2, A]` is a field-gap, not an engineering shortfall — no amount of YazSes code shrinks it. Pane/window/field targets are large relative to that radius; caret targets are not. Shipping caret precision would be selling the demo (`[grade F]` in the Vision card bullshit filter), not the science.

**Single-instant snapping dodges the worst error mode.** Head motion is what turns 50 mm into 80 mm `[paper:PMC11019238]`. Sampling once, at the moment the user commits to speak (hold-start), captures a briefly-still head and avoids the continuous-tracking drift that plagues always-on eye cursors.

**Light regressor + few-point calibration beats heavy ceremony.** GazeRecorder's ~30 points buy ~17.5 mm `[paper:PMC11019238]` — precision we don't need for pane grain. WebGazer shows a self-calibrating, click-driven, region-accurate path `[web:WebGazer]`. A 5–9-point wizard plus optional implicit click refinement is the right friction/accuracy point for coarse targeting and keeps the once-per-setup promise.

**Reuse the existing seams.** `inject/auto.py` already probes injectors and targets the focused window — adding a gaze-chosen target is a localised change to *which* window is targeted, not a pipeline rewrite. `_on_hold_start` is the natural single fusion instant. `accessibility/enroll.py` already establishes the calibration-wizard pattern.

**Optional, dormant, local.** Like the EMG backend (ADR-v04-003), the dep is behind an extra and nothing imports it unless `[gaze] enabled`. Honours ADR-011: an always-on camera is the most privacy-sensitive sensor in the product, so it is off by default, explicitly enabled, frames never stored or transmitted, with a visible active state and a hard kill.

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| **Caret-precise gaze typing** (gaze *is* the cursor) | Webcam error is ~50–80 mm `[paper:PMC11019238]`; ten lines of slop. Only IR trackers (15 mm) reach caret grain — out of scope for a commodity-webcam offline daemon. This is the core scope-down. |
| **Continuous gaze tracking** (cursor follows eyes live) | Head-motion penalty (50→80 mm) `[paper:PMC11019238]` makes a live cursor jittery and untrustworthy; also a constant CPU/webcam draw. Single hold-start snapshot is more accurate and less invasive. |
| **30-point GazeRecorder-grade calibration** | Buys ~17.5 mm `[paper:PMC11019238]` precision we don't need for pane grain, at a friction cost that kills adoption (Vision card LOFA-3). |
| **Require a dedicated IR eye tracker (Tobii)** | Reaches 15 mm `[paper:PMC11019238]` but breaks the commodity-hardware, offline-laptop premise. A future `IrGazeBackend` can slot into the same Protocol if demand appears. |
| **MediaPipe iris alone, no regressor** | MediaPipe does not output gaze `[doc:Google-Research]`; iris landmarks without a screen-mapping regressor cannot pick a target. |
| **Cloud gaze API** | Violates the offline / no-capture premise (ADR-011). Non-starter — webcam frames must never leave the device. |

## Configuration

New `[gaze]` section in `config.py` (`GazeConfig` dataclass), all defaults dormant:

```toml
[gaze]
enabled = false                 # master switch; false = module never imported (default)
camera_index = 0                # OpenCV device index
confidence_threshold = 0.6      # below this, ignore gaze → focused-window fallback
target_grain = "pane"           # "pane" | "window" | "field" — never "caret"
calibration_path = ""           # persisted regressor; empty → must run `yazses enroll --gaze`
calibration_points = 9          # 5..9 explicit wizard points (NOT ~30)
implicit_calibration = true     # WebGazer-style click/keystroke refinement on top
snapshot_frames = 3             # frames median-pooled at hold-start (1 = single frame)
require_still_head = false      # if true, skip the snap when head-pose velocity is high
max_fps = 30                    # cap webcam inference rate to bound CPU
```

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Master switch. `false` → module fully dormant, webcam never opened. |
| `camera_index` | `int` | `0` | OpenCV capture device index. |
| `confidence_threshold` | `float` | `0.6` | Minimum `GazePoint.confidence` to act on; below → focused-window fallback. |
| `target_grain` | `str` | `"pane"` | Targeting granularity: `pane`/`window`/`field`. `caret` is intentionally unsupported. |
| `calibration_path` | `str` | `""` | Path to the persisted per-user regressor artifact. Empty = uncalibrated. |
| `calibration_points` | `int` | `9` | Explicit calibration target count (5–9). |
| `implicit_calibration` | `bool` | `true` | Refine the regressor passively from click/keystroke locations (WebGazer-style). |
| `snapshot_frames` | `int` | `3` | Frames median-pooled at the hold-start snap to reduce single-frame noise. |
| `require_still_head` | `bool` | `false` | Skip the gaze snap (→ fallback) when head motion is high at hold-start. |
| `max_fps` | `int` | `30` | Upper bound on webcam inference rate to cap CPU. |

`enabled` defaulting to `false` means the daemon behaves exactly as today unless the user opts in — no webcam access, no new imports.

## Integration with `inject/` target selection

Current flow: `core/daemon.py::_on_hold_start` begins recording; on `_on_hold_end` the text is injected via `_active_injector()` into the **focused** window (`inject/auto.py::get_injector`).

Gaze integration adds a **target-selection step at hold-start only**:

1. `_on_hold_start(leaked)` — if `[gaze] enabled` and a `GazeBackend` is wired, call `gaze.snapshot()`.
2. If a `GazePoint` returns with `confidence ≥ confidence_threshold`, pass it to the platform `PaneResolver` to hit-test against window/pane geometry.
3. If it resolves to a target pane/window, **raise/focus that target** before recording — so the existing focused-window injection path (`inject/auto.py`) lands the text there with **no change to the injector itself**.
4. If gaze is low-confidence, unresolved, or disabled → no focus change → inject into the focused window exactly as today.

This keeps `inject/base.py` / `inject/auto.py` untouched: gaze changes *which window is focused* at the dictation instant, and injection continues to target focus. The `GazeBackend` is wired in `platform/factory.py` (like the EMG backend) only when `[gaze] enabled`.

## Dependencies

New optional dep group `gaze` in `pyproject.toml`, latest stable, imported only when `[gaze] enabled`:

```toml
[project.optional-dependencies]
gaze = [
  "mediapipe >= 0.10",   # Face Landmarker (landmarks + head pose); pin to current stable at impl time
  "opencv-python >= 4.10",
  "numpy >= 1.26",       # already a transitive dep; pinned here for the regressor math
]
```

Install with `uv sync --extra gaze`. L2CS-Net is **not** a hard dependency — the first build uses the MediaPipe-landmarks + light-regressor path; an L2CS feature backbone is an optional escalation (see Phase plan / Open questions). Verify and bump each pin to the actual current stable at implementation time.

## Phased plan

**P1 — Calibration + coarse pane targeting (the bet).**
- `GazeBackend` Protocol + MediaPipe-based implementation; OpenCV capture; ridge/poly regressor.
- 5–9-point calibration wizard (`yazses enroll --gaze`), persisted artifact.
- `_on_hold_start` single-snapshot fusion; `PaneResolver` for one platform (Linux first); focused-window fallback everywhere.
- `[gaze]` config, off by default; `gaze` extra.
- **Gate (from Vision card LOFA-1):** correct-pane accuracy **≥ 85%** on a still-head 4-pane layout, panes ≥ ~¼ screen. **If < 85%, stop** — the webcam error ceiling is fatal even at pane grain.

**P2 — Robustness + implicit calibration.**
- WebGazer-style implicit click/keystroke refinement; `require_still_head` gating; multi-frame median tuning.
- `PaneResolver` for macOS/Windows.
- Validate the head-motion mitigation (LOFA-2: < 15-point accuracy drop with natural head motion).

**Deferred — caret precision (pending SoA jump).**
- Caret/line-level placement is **explicitly out of scope** until a head-pose-invariant webcam regressor or commodity depth/IR moves the error envelope below pane grain `[paper:PMC11019238]`. The Protocol seam means this becomes a new backend/grain, not a refactor (ADR-005 intent). An `IrGazeBackend` for users with a Tobii-class tracker is a candidate here.

## Testing approach

- **Unit:** `MockGazeBackend` returning scripted `GazePoint`s (mirrors ADR-005's `MockInputBackend`) — daemon target-selection and fallback logic tested with no webcam. Cover: high-confidence resolve → target switch; low-confidence → focused-window fallback; geometry-unavailable → fallback; `enabled = false` → no gaze code path.
- **Regressor:** synthetic calibration points → fit → assert screen-mapping error within the expected coarse envelope; degrade gracefully on too-few points.
- **`PaneResolver`:** geometry hit-test against fixture window layouts (no live WM needed for the math).
- **Integration / acceptance (the real bet):** the scripted **pane-hit-rate** harness from LOFA-1 — "look at pane X, trigger, record landed pane" × N across a 4-pane layout, still-head and moving-head. This is the pass/fail gate, not a unit test.
- **CPU budget:** assert inference stays within the `max_fps`/CPU envelope `[doc:Google-Research]` on the dev machine; gaze must not regress dictation latency.
- **Privacy invariant:** test that `stop()` releases the camera and that no frame buffer is ever written to disk or sent over IPC.

## Risks & mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| **Accuracy ceiling** — ~50 mm still / 80 mm moving; can't even pick a small pane | `[paper:PMC11019238, tier2, A]` | Scope to pane/window grain ≥ error radius; LOFA-1 85% gate kills it if pane grain still fails; never attempt caret. |
| **Head motion collapse** (50→80 mm) | `[paper:PMC11019238]` | Snap once at hold-start (head briefly still), not continuously; optional `require_still_head` skip → fallback; multi-frame median. |
| **Calibration burden** (~30 points for accuracy) | `[paper:PMC11019238, tier2, B]` | Use 5–9 points + WebGazer-style implicit click refinement `[web:WebGazer]`; persist once; tolerate coarse fit since target is coarse. |
| **Calibration drift over a session** | `[web:WebGazer]` | Implicit click/keystroke recalibration; confidence-gate so drift → fallback, never a wrong-pane misfire. |
| **Webcam privacy** (always-on camera) | ADR-011 premise | **Local only** — frames never stored, never transmitted; off by default; explicit enable; visible active state; hard kill; tested invariant. |
| **CPU cost / latency regression** | `[doc:Google-Research]` (~5% CPU but not free) | Cap `max_fps`; single snapshot not continuous decode; gaze inference off the dictation hot path. |
| **Pane geometry unavailable** (Wayland sandbox, etc.) | `[unverified]` | `PaneResolver` returns `None` → focused-window fallback; per-platform support landed incrementally. |
| **Over-promise / demo-vs-science** | Vision card §7 (grade F on caret demos) | Spec, config (`target_grain` excludes `caret`), and docs state coarse-only plainly; fallback makes it never-worse-than-today. |

## Consequences

- **New optional module + dep group** (`gaze`): `mediapipe`, `opencv-python`, `numpy`. Not imported unless `[gaze] enabled`. Mirrors the EMG `extra` pattern (ADR-v04-003).
- **Webcam becomes an input** for opted-in users — a new permission surface; `yazses doctor` should report camera availability when `[gaze] enabled` (as it does for the EMG serial port).
- **One new calibration ceremony** (`yazses enroll --gaze`) and a persisted per-user artifact at `calibration_path`.
- **Injector untouched** — gaze changes which window is focused at hold-start; `inject/auto.py` continues to target focus. No pipeline rewrite.
- **A future precision jump is a single-module addition** (new `GazeBackend` / grain), not a refactor — the seam is the lasting value even if P1 stalls (ADR-005 intent).

### Why this is scoped down (explicit)

Caret-precise gaze typing is the seductive version, and it is **not feasible on a commodity webcam today**. Every credible source puts webcam→screen error at **tens of millimetres** (best ~50 mm still-head, 80 mm moving) `[paper:PMC11019238, tier2, A]`; only dedicated IR trackers reach the single-digit-millimetre, caret-grade range. MediaPipe gives cheap real-time landmarks but **no gaze** `[doc:Google-Research]`, and WebGazer-class self-calibrating webcam gaze is validated only for **coarse regions** `[web:WebGazer]`. So this spec deliberately ships the **honest, useful slice** — *look-to-pane / look-to-field with a focused-window fallback* — and **defers caret precision until the state of the art moves the error envelope below pane grain**. The fusion seam (calibration, hold-start snap, pane hit-test, confidence-gated fallback) is built now so YazSes can absorb that future precision jump as a drop-in backend rather than a rewrite — which is precisely why the Vision card scores this **watch with high regret-risk (4/5)**, not no-go.

---
### Evidence tag legend
`[paper:X, tierN, grade]` peer-reviewed · `[doc:tool]` official docs · `[web:source]` web source · `[unverified]` no source yet. Source tiers: 1 peer-reviewed → 7 forum; grade A–F = argument quality.
