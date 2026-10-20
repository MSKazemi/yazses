# Dedicated eye-tracker study (EYE-TRACKER-001, #412)

**Status:** research note. **No implementation yet.** No vendor SDK, dependency, config key or
code is added by this note.
**Date:** 2026-10-15 (every web source below was accessed on this date).
**Answers:** the checklist in [ROADMAP.md](ROADMAP.md) Phase 7 and `AGENT_TASKS.md` EYE-TRACKER-001.
**Risk closed or narrowed:** R-22 in [RISK_REGISTER.md](RISK_REGISTER.md).
**Related:** [ADR-v2-145](../adr/adr-v2-145-shared-camera-perception.md),
[ADR-v2-149](../adr/adr-v2-149-gaze-calibration-coordinate-space.md),
[ADR-019](../adr/adr-019-egress-inventory-and-escalation.md).

## How to read this note

Every claim carries one of three labels.

- **FACT** — stated by the cited page. Wording in quotation marks is the page's own.
- **INFERENCE** — my reasoning from facts. It may be wrong; it is here so a maintainer can check it.
- **UNVERIFIED** — I looked and could not confirm it, or the page is gated. Nothing marked
  UNVERIFIED may be used as a licence or API claim. A wrong licence statement is worse than none.

**Retrieval caveat.** The pages were read through a retrieval tool that returns a model-written
summary of each page, not the raw HTML. Quotations are the summary's quotations of the page.
Before any licence or redistribution decision, a maintainer must re-read the primary licence text
in a browser. This note is a map of where to look, not legal advice.

**Project licence.** YazSes is Apache-2.0 (`pyproject.toml`, `LICENSE`). The issue text and this
study's brief say "MIT"; the repository says Apache-2.0, and that is what this note assumes.

## Summary of the recommendation

1. **Do not add any vendor SDK now.** None of the proprietary SDKs below has a redistribution grant
   that I could verify, and the Tobii Stream Engine documentation is not publicly retrievable at all.
2. **The existing `GazeBackend` seam is the right shape for a prototype, and the wrong shape for a
   product.** Its sample is a camera-derived feature `(yaw, pitch)`, not a point; it has no
   timestamp; and the daemon refuses to start gaze without a webcam calibration file. Details in
   [What the current seam gets wrong](#what-the-current-seam-gets-wrong-for-a-tracker). No bug exists
   today, because no tracker exists, so no code or test is proposed.
3. **When a tracker is wanted, define `GazeSampleProvider` as a small, vendor-type-free Protocol
   that emits a normalized screen point with a monotonic timestamp,** and keep every vendor type
   inside one adapter module. Proposed contract below.
4. **A tracker provider is bring-your-own-SDK.** It imports the vendor library lazily, ships none of
   its binaries, and is an optional extra only where the vendor library is verifiably
   redistributable and permissively licensed.
5. **Neither the OS-level APIs nor the webcam path is a stand-in for a dedicated tracker.** Keep the
   accuracy class separate, as [README.md](README.md) already requires.

## Per-device and per-platform findings

### Tobii Pro SDK (research trackers: Spark, Nano, Fusion, Spectrum)

| Question | Finding |
|---|---|
| Delivery | FACT: gaze data arrives by callback: "You will get an object of this type to the callback you supply in EyeTracker.subscribe_to with EYETRACKER_GAZE_DATA." [Python GazeData reference](https://developer.tobiipro.com/tobii.research/python/reference/2.1.0.3-alpha-gd8b35e1b/classtobii__research_1_1GazeData.html) |
| Rate | FACT: Tobii Pro Spark "Sampling frequency: 60 Hz (default) or 33 Hz". [Spark page](https://www.tobii.com/products/eye-trackers/screen-based/tobii-pro-spark) |
| Accuracy | FACT: 0.45 deg accuracy, 0.26 deg RMS precision "in optimal conditions" (same page; vendor claim, not independently measured). |
| Coordinate space | FACT: gaze is normalized to the Active Display Area: "The point (0, 0) denotes the upper left corner and (1, 1) the lower right corner of it." Eye positions use a millimetre User Coordinate System. [Coordinate systems](https://developer.tobiipro.com/commonconcepts/coordinatesystems.html) |
| Timestamps | FACT: two clocks. The device stamp comes from "the internal clock in the eye tracker hardware"; the system stamp "uses the computer on which the application is running as the source". Units are "generally" microseconds "measured from an arbitrary point in time". The SDK maps the two clocks itself. [Time stamps and timing](https://developer.tobiipro.com/commonconcepts/timestamp-and-timing.html) |
| OS | FACT: Spark page lists "Windows, macOS, and Linux". [What's new](https://www.developer.tobiipro.com/tobiiprosdk/whatsnew.html) lists macOS 13/14 (Apple silicon and Intel) and Ubuntu 22.04 for release 2.1; Spark, Nano, Fusion, Spectrum supported. |
| Redistributable runtime | FACT: PyPI `tobii-research` 2.1.0 has wheels for Windows x86-64, Linux `manylinux2014_x86_64` and macOS 14+ universal2, all CPython 3.10, and the licence field reads "Other/Proprietary License (https://go.tobii.com/tobii-pro-sdk-license-agreement)". [PyPI](https://pypi.org/project/tobii-research/) |
| Licence | FACT (from the licence summary page, [Tobii Software Development License Agreement](https://www.tobii.com/products/integration/tobii-sdk-license)): two licences. The Research Development License "is for research and exploration use at universities, academic institutions or companies", is for "low-scale development with no plan to commercialize", and "is available only with Tobii Pro eye tracker products". The Commercial Development License "allows you to develop your software without commercial use or distribution" until a further agreement is signed. The page is "a summary, not the full license text". **The agreement text itself (the `go.tobii.com` link) returned nothing, so its grant, redistribution and field-of-use clauses are UNVERIFIED.** |
| Does the licence permit an Apache-2.0 offline dictation tool to ship or call it? | **UNVERIFIED.** INFERENCE: the research licence's stated scope (research, low scale, no commercialization) does not obviously cover a general-purpose accessibility tool distributed to the public, so shipping or depending on it by default is not safe. Calling a library the *user* installed under their own licence is a different question, also UNVERIFIED. |
| Privacy | UNVERIFIED whether the SDK contacts any Tobii service. The trackers are described as "usb and network eye trackers" (PyPI), which suggests local transport (INFERENCE). |
| Cost | FACT: the Spark page gives no price ("our advisors will provide pricing"); it says "Free Tobii Pro SDK and Eye Tracker Manager licenses are included." Hardware price: UNVERIFIED (a 2017 forum figure I saw is too old to cite). |

### Tobii Eye Tracker 5 and Stream Engine (consumer trackers)

| Question | Finding |
|---|---|
| API shape | **UNVERIFIED.** The Stream Engine reference is not publicly retrievable; the developer pages I reached name only the EyeX SDK licence and "Tobii Game Integration". FACT: "a Native C++ API called Tobii Game Integration API", with bindings for C#, Unity and Unreal Engine 4. [PC gaming](https://developer.tobii.com/pc-gaming/) Whether Eye Tracker 5 is reachable through it, and through what, is not established by those pages. |
| Coordinates, rate, timestamps | UNVERIFIED for Stream Engine. A third-party tool says "2-D gaze points on screen in normalized coordinates is provided" ([LSL app README](https://github.com/labstreaminglayer/App-TobiiStreamEngine)); that is secondary and says nothing on timestamps. |
| Licence types | FACT: "There are three licensing types for developers using Tobii developer software and SDKs": Getting Started, Commercial, Research. [PC gaming](https://developer.tobii.com/pc-gaming/) The terms of each for Stream Engine: UNVERIFIED. |
| Redistribution | FACT (third-party README): the LSL app "does not include the DLL"; "you will need to provide your own copy of tobii_stream_engine.dll from the SDK". It also says "This is not intended for research use. Please check the Software License Agreement to see if your use case is compliant." FACT: the `tobii-sys` Rust crate is "MIT" and "Based on the stream engine headers from v1.2.1.305" ([docs.rs](https://docs.rs/tobii-sys)); INFERENCE: the MIT covers the bindings, not the vendor library. |
| OS | FACT: the Windows Eye Control supported-device list names Tobii Eye Tracker 4C, EyeX and several Tobii Dynavox devices; the list as retrieved did **not** name the Eye Tracker 5 (UNVERIFIED whether the retrieved list was complete). [Microsoft support](https://support.microsoft.com/help/4043921/windows-10-get-started-eye-control) Linux: UNVERIFIED officially. Community wrappers claim Ubuntu use (a Java wrapper tested "Ubuntu 18.04", per a search summary of [GazePlay/TobiiStreamEngineForJava](https://github.com/GazePlay/TobiiStreamEngineForJava)); that is old, unofficial and says nothing about licence. macOS: no evidence of support. |
| Privacy and cost | UNVERIFIED. The Tobii gaming page links a privacy policy and a data transparency policy but their contents were not retrieved; no price was stated. |

### Gazepoint (GP3 family)

| Question | Finding |
|---|---|
| Delivery | FACT (secondary): the Open Gaze API is a socket on the local machine, default port 4242, TCP/IP, XML commands such as `<SET ID=... STATE=... />`. [DMDX help](https://psy1.psych.arizona.edu/~jforster/dmdx/help/dmdxhsendkeyword.htm) The authoritative reference is Gazepoint's API PDF, which I did not read (and which this repo must not cite by `.pdf` URL). Field names, coordinate space and timestamps: UNVERIFIED. |
| Rate | A forum user reports about 60 Hz ([OpenSesame forum](https://forum.cogsci.nl/discussion/comment/6206/)); UNVERIFIED against the vendor. |
| OS | FACT: "compatible with Microsoft Windows 7 and up". [gazept.com](https://www.gazept.com/) Linux and macOS: UNVERIFIED. |
| Licence / redistribution | FACT: "Every order includes an open standard API and SDK". The SDK licence is UNVERIFIED; the Downloads page is password protected, so I could not read it. [Downloads](https://www.gazept.com/downloads/) |
| Privacy | INFERENCE: a loopback TCP API sends nothing off the machine by itself, but the vendor's analysis software was not examined. UNVERIFIED. |
| Cost | FACT: described as "professional grade equipment available at a consumer price point"; no figure. |

### EyeTech (TM5 Mini and relatives)

| Question | Finding |
|---|---|
| OS-level | FACT: the **TM5 Mini** is on the Windows Eye Control supported list ([Microsoft support](https://support.microsoft.com/help/4043921/windows-10-get-started-eye-control)). |
| SDK | A reseller states the SDK "offers support for both Windows and Android" and that the TM5 mini is discontinued ([Zyteq](https://www.zyteq.com.au/products/eye_gaze/eyetech-tm5-mini)); an iMotions page for a sibling model calls the API proprietary QuickLINK ([iMotions](https://imotions.com/hardware/eyetech-vt3)). Both are secondary. |
| Everything else | Licence, redistribution, coordinates, timestamps, privacy, cost: **UNVERIFIED.** The vendor site I reached listed only a tablet product. |

### Pupil Labs (Core, Neon)

| Question | Finding |
|---|---|
| Pupil Core software licence | FACT: "All source code written by Pupil Labs is open for use in compliance with the GNU Lesser General Public License (LGPL v3.0)." [GitHub](https://github.com/pupil-labs/pupil) INFERENCE: talking to Pupil Capture over a socket from an Apache-2.0 process does not link LGPL code into YazSes; a maintainer should still confirm. |
| Pupil Core delivery | FACT: ZeroMQ plus msgpack; "Pupil Remote" is REQ-REP, data is PUB-SUB; default Pupil Remote port 50020; examples connect to `127.0.0.1`/`localhost`. [Network API](https://docs.pupil-labs.com/core/developer/network-api/) Gaze field definitions, timestamp definition and the `norm_pos` origin were not on the page I retrieved: UNVERIFIED. Core's gaze is relative to its world camera, so a screen point needs a separate surface-mapping step (INFERENCE, UNVERIFIED). |
| Pupil Core OS | FACT: the repository has setup notes for Linux and for "macOS 12 Monterey and newer"; Windows was not mentioned on the page retrieved. |
| Neon delivery | FACT: "Gaze data is output in pixel space of the scene camera image", origin top left, target rate 200 Hz, produced "without requiring a calibration". [Data streams](https://docs.pupil-labs.com/neon/data-collection/data-streams/) FACT: the Python client `pupil-labs-realtime-api` 1.9.0 (31 July 2026) is "MIT License" and "is only available for Pupil Invisible and Neon, Pupil Core uses a different API". [PyPI](https://pypi.org/project/pupil-labs-realtime-api/) A search summary says the API streams to devices on the same local network. Timestamp semantics: UNVERIFIED for the current version. |
| Neon, INFERENCE | Neon is a head-worn device streaming over a **LAN** from a phone, and its gaze is in scene-camera pixels. A desktop screen point is not something it delivers directly. A LAN stream is an outbound network primitive: it needs an ADR-019 egress row and a loopback/LAN-only guard. |
| Privacy | FACT: the Neon page says post-hoc gaze is recomputed "in Pupil Cloud when needed", so a cloud product exists; whether the real-time path ever contacts it is UNVERIFIED. |
| Cost | UNVERIFIED (no price on the pages reached). |

### OS-level options

| Platform | Finding |
|---|---|
| **Windows** | FACT: "Windows.Devices.Input.Preview" is available from Windows 10 1803 (build 17134). The app must "declare the `gazeInput` capability in the app manifest", and Windows "prompts users with a consent dialog". `GazeInputSourcePreview.GetForCurrentView()` "must be called on the UI thread" and the user is "prompted only once, when the app is first run". [Gaze interactions](https://learn.microsoft.com/windows/uwp/ui-input/gaze-interactions), [GetForCurrentView](https://learn.microsoft.com/uwp/api/windows.devices.input.preview.gazeinputsourcepreview.getforcurrentview). FACT: `GazePointPreview` has `EyeGazePosition`, `HeadGazePosition`, `Timestamp`, `SourceDevice`, `HidInputReport`, and "the screen coordinates of the gaze point are in device-independent pixels (DIP) relative to, and constrained by, the application view (or gaze-enabled element)". [GazePointPreview](https://learn.microsoft.com/en-us/uwp/api/windows.devices.input.preview.gazepointpreview) FACT: the same page says eye data is "potentially sensitive personal data" and an app that "collects, stores, or transfers eye tracking data" must say so in its privacy statement. Supported hardware is the Eye Control list (Tobii 4C/EyeX/Dynavox, EyeTech TM5 Mini). **INFERENCE:** the API is windowed and view-relative, so a windowless Python daemon probably cannot get desktop-wide gaze from it; this would need an experiment on Windows hardware, which I did not and could not do. Timestamp type and units: UNVERIFIED. |
| **macOS** | I found no developer-facing gaze API. FACT (search summary of Apple support pages): iPhone and iPad have Eye Tracking from the front camera, with setup and control data "processed on device", and iPad can route an MFi eye tracker through AssistiveTouch. [iPhone](https://support.apple.com/guide/iphone/control-iphone-with-the-movement-of-your-eyes-iph66057d0f6/ios) Mac has Head Pointer, a head-movement feature (secondary sources only). Whether macOS has eye tracking, or exposes any of this to apps: **UNVERIFIED.** ARKit-class face APIs were not researched. |
| **Linux** | I found no OS-level eye-tracking API. Paths that exist: the Tobii Pro SDK (Ubuntu 22.04, `manylinux2014` wheel; proprietary), Pupil Core (Linux setup notes; LGPL), and unofficial community wrappers around Tobii's proprietary Stream Engine. **"libgazebo" returned no eye-tracking library in my searches;** that name appears to be a mix-up (UNVERIFIED), so the brief's "libgazebo" lead is unconfirmed. A search summary of a university project idea says a free USB driver for the Tobii 4C was proposed; I could not retrieve it and do not rely on it. |

### Cross-vendor matrix (what the evidence supports)

| Source | Coordinate frame delivered | Timestamp clock | Redistributable library verified? | Open-source licence verified? | Leaves the machine? |
|---|---|---|---|---|---|
| Tobii Pro SDK | normalized display area, 0..1, top-left | device clock and host clock, microseconds | wheels exist; terms UNVERIFIED | no (proprietary) | UNVERIFIED |
| Tobii Stream Engine | UNVERIFIED | UNVERIFIED | no, vendor DLL must be supplied by the user | no | UNVERIFIED |
| Gazepoint Open Gaze | UNVERIFIED | UNVERIFIED | SDK licence UNVERIFIED | no evidence | loopback socket (INFERENCE) |
| EyeTech | UNVERIFIED | UNVERIFIED | UNVERIFIED | no evidence | UNVERIFIED |
| Pupil Core | world camera (surface mapping needed, INFERENCE) | "Pupil time" | n/a, separate app | LGPL-3.0 (FACT) | loopback by default in examples |
| Pupil Neon | scene-camera pixels | UNVERIFIED | n/a, separate device | client MIT (FACT) | LAN stream (FACT per search summary) |
| Windows gaze API | view-relative DIP | `Timestamp` property, units UNVERIFIED | part of the OS | n/a | consent prompt; transfer is the app's duty |

## What the current seam gets wrong for a tracker

I read `src/yazses/gaze/` and `src/yazses/perception/`. There is **no `GazeSampleProvider` in code**;
the name appears only in `design/` ([ADR-v2-145](../adr/adr-v2-145-shared-camera-perception.md),
[README.md](README.md), [ROADMAP.md](ROADMAP.md)). The live seam is:

- `gaze/base.py: GazeBackend` — `name`, `estimate() -> (yaw, pitch) | None`, `close()`.
- `estimate_sample() -> GazeSample(x, y, confidence)` is **not in the Protocol**. `GazeTargeter._sample`
  finds it with `getattr`, and `eyeeval/gaze_field.py` calls it directly.
- `gaze/targeter.py` always resolves a window through `calibration.predict(yaw, pitch)`
  (`gaze/zones.py: resolve_window`); `CalibrationMap` is an affine fit from camera features to
  desktop pixels (`gaze/calibrate.py`).
- `core/daemon.py` returns no targeter at all when no calibration file exists ("not calibrated; run
  `yazses gaze calibrate`"), and the calibration CLI collects samples with `backend.estimate()`.
- `gaze/topology.py: CalibrationContext` records `camera_id`, `camera_width`, `camera_height`.
- `gaze/factory.py: _BACKENDS` is a closed table of `mediapipe` and `l2cs`.

Against what a tracker delivers, five gaps follow. They are design constraints, **not bugs**: with no
tracker backend, nothing misbehaves, so I am proposing no test and no code.

1. **Feature versus point.** The seam's sample is an eye-direction feature that needs a learned map.
   A dedicated tracker already reports a point on a display (Tobii Pro: normalized display area;
   Windows: DIP). Routing it through `CalibrationMap` would mean a fake identity "calibration" and
   storing a screen position in a field called `yaw`. It would work in a prototype and mislead readers.
2. **No timestamp on the sample.** Freshness exists only inside `SharedGazeBackend`
   (`MAX_SAMPLE_AGE_S`). Trackers stream continuously on their own clock (two clocks, for Tobii), so
   the staleness rule has to be part of the provider contract, not a private detail of one adapter.
   This is the same stale-signal hazard as R-06.
3. **Calibration gating is webcam-shaped.** The daemon will not start a targeter without the
   affine file, and `CalibrationContext` has no place for "tracker X bound to display Y".
4. **No device discovery or health.** The webcam path has a camera index and a failure reason;
   there is nothing for "tracker unplugged" or "vendor service not running".
5. **Duck-typed optional method.** `estimate_sample` being found by `getattr` means a provider can
   silently lose its confidence and be treated as 1.0 (the code says so for `l2cs`).

## Proposed minimal `GazeSampleProvider` (design only)

Vendor types never cross this boundary. Names are proposals for a future ADR, not accepted API.

```python
@dataclass(frozen=True)
class TrackerSample:
    x: float            # normalized, 0.0..1.0, origin top-left, y grows downward
    y: float
    timestamp_s: float  # time.monotonic() clock, taken/converted by the adapter
    confidence: float   # 0.0..1.0; 1.0/0.0 from a validity flag if that is all the vendor gives
    display_id: str     # which display the 0..1 square refers to

@runtime_checkable
class GazeSampleProvider(Protocol):
    @property
    def name(self) -> str: ...
    def start(self) -> None: ...                 # idempotent; the device is opened here, not at import
    def latest(self) -> TrackerSample | None: ... # newest fresh sample; never blocks beyond a stated bound
    def status(self) -> ProviderStatus: ...       # connected / reason; no coordinates in it
    def close(self) -> None: ...
```

**Coordinate contract.** A provider emits a point normalized over one named display, origin top-left.
Conversion to the canonical `desktop-logical-px` space is done by YazSes core from
`DisplayTopology`, not by the adapter, so ADR-v2-149's "one named canonical space, centralised
conversion" stays true. Adapters whose source is not display-normalized (Windows DIP, Pupil screen
mapping) convert inside the adapter and say so. A provider that cannot name its display emits nothing.

**Timestamp contract.** `timestamp_s` is on `time.monotonic()`, exactly as `perception/signals.py`
already specifies, so one freshness rule serves both sources. The adapter, not the core, owns clock
mapping (Tobii's two clocks, Pupil time). Device clock values are not exposed.

**Confidence.** In `[0, 1]` and defined per adapter. Binary validity maps to 1.0 or "no sample",
because the existing `[gaze] confidence_min` gate would otherwise compare a measured number with a
constant. A tracker's confidence is **not comparable** with the webcam's eye-agreement figure and must
not share a threshold unseen (INFERENCE).

**Calibration ownership.** Two honest cases:

- *Vendor-owned* (Tobii Eye Tracker Manager, Windows Eye Control, Pupil's own tools): YazSes stores
  no affine map. It stores only a context record, a generalised `CalibrationContext` whose
  `camera_id`-style field becomes a sensor id plus the display binding, so a display or sensor change
  invalidates it under ADR-v2-149's rules. This is an additive schema change needing its own ADR.
- *SDK-driven calibration* (Pro SDK and Gazepoint expose calibration APIs, UNVERIFIED in detail):
  **out of scope for v1.** Do not re-implement vendor calibration.

**Coexistence with the webcam provider.**

- A tracker is not a camera consumer (already stated in ADR-v2-145). It takes **no** lease on the
  shared perception source, so head pose and face switch keep running on the webcam while gaze comes
  from the tracker.
- Exactly one gaze source is active, chosen by explicit user configuration. **No fusion** in v1.
- If the tracker drops out, gaze answers `None` and routing keeps the focused window, which is what the
  targeter already does for a failed webcam. It must **not** silently fall back to webcam gaze: that is a
  different accuracy class, and [README.md](README.md) forbids blending the claims. Status must name
  the reason.
- `GazeBackend` stays valid for the webcam and `l2cs`. The migration path is an adapter that presents
  a provider as a `GazeBackend` for the targeter, which is how ADR-v2-145 already describes it.
- `eyeeval` needs a fake provider with scripted samples (pure, injected), and any tracker-specific
  evaluation must report derived metrics only.

## What a tracker provider must not do

- **No cloud.** No vendor account sign-in, licence activation, telemetry or "cloud" feature as a
  condition of use. Whether any SDK does this is UNVERIFIED, so each adapter needs a check before it
  merges. Anything that opens a socket needs an ADR-019 row, and the loopback-only guard pattern used
  for `llm_cleanup` applies; a LAN stream (Pupil Neon) is an escalation, not a freebie.
- **No raw stream storage.** No gaze coordinates, eye positions, pupil data, sample rates or device
  logs written to disk, to `log` output above debug, to crash reports or to issue attachments. Persisted
  data is limited to the calibration context (no samples). Windows' own guidance calls this data
  "potentially sensitive personal data" (FACT).
- **No data the core does not use.** Drop eye position in millimetres, pupil diameter, per-eye data and
  head pose at the adapter. Minimisation is cheaper than a later privacy review.
- **No vendor types in the core.** No import of a vendor module at top level (AGENTS.md rule 3), no
  vendor class in a signature, no vendor enum in config.
- **No bundled proprietary binaries** and no wheel from a proprietary licence in a default extra,
  until a maintainer has read the primary licence and obtained written confirmation.
- **No change to webcam accuracy claims**, no shared threshold, no shared calibration file.
- **Ships off by default** with a dormant `enabled = False` (rule 2); a new config key is L3 work.

## Open questions for a maintainer

1. Read the primary Tobii Pro SDK agreement and Stream Engine agreement in a browser; is a user-installed
   SDK called from an Apache-2.0 tool inside the field of use? (The research licence page suggests not
   for general public distribution, but that is a summary.)
2. Is Windows' view-relative gaze usable from a windowless daemon? Needs a Windows machine with a
   supported tracker.
3. Which tracker class does the project actually want to support first? The matrix above says
   Gazepoint (loopback socket) and Pupil Core (loopback ZeroMQ) are the cheapest to *reason* about, but
   neither's field names and timestamps are verified here.
4. Does the project want the `CalibrationContext` generalisation (sensor id) as its own ADR?

## Sources and access dates

All accessed 2026-10-15 unless stated. "Summary" means the retrieval tool's summary of the page.

| Source | Used for |
|---|---|
| https://pypi.org/project/tobii-research/ | wheels, version, licence field |
| https://www.developer.tobiipro.com/tobiiprosdk/whatsnew.html | OS and tracker support in 2.1 |
| https://www.tobii.com/products/integration/tobii-sdk-license | licence summary (not the full text) |
| https://go.tobii.com/tobii-pro-sdk-license-agreement | returned empty; full agreement UNVERIFIED |
| https://developer.tobiipro.com/commonconcepts/coordinatesystems.html | ADCS and UCS |
| https://developer.tobiipro.com/commonconcepts/timestamp-and-timing.html | device and system clocks |
| https://developer.tobiipro.com/tobii.research/python/reference/2.1.0.3-alpha-gd8b35e1b/classtobii__research_1_1GazeData.html | callback delivery |
| https://www.tobii.com/products/eye-trackers/screen-based/tobii-pro-spark | rate, accuracy, OS, price statement |
| https://developer.tobii.com/pc-gaming/ | Game Integration API; three licence types |
| https://github.com/labstreaminglayer/App-TobiiStreamEngine | DLL not bundled; compliance warning |
| https://docs.rs/tobii-sys | bindings MIT; header version |
| https://github.com/GazePlay/TobiiStreamEngineForJava | search summary only (Linux claim) |
| https://www.gazept.com/ , https://www.gazept.com/downloads/ | OS, API/SDK statement, downloads gated |
| https://psy1.psych.arizona.edu/~jforster/dmdx/help/dmdxhsendkeyword.htm | Open Gaze port and XML (secondary) |
| https://forum.cogsci.nl/discussion/comment/6206/ | ~60 Hz report (secondary) |
| https://www.zyteq.com.au/products/eye_gaze/eyetech-tm5-mini , https://imotions.com/hardware/eyetech-vt3 | EyeTech SDK statements (secondary) |
| https://github.com/pupil-labs/pupil | Pupil Core licence and OS notes |
| https://docs.pupil-labs.com/core/developer/network-api/ | Core transport |
| https://docs.pupil-labs.com/neon/data-collection/data-streams/ | Neon gaze frame and rate |
| https://pypi.org/project/pupil-labs-realtime-api/ | Neon client licence and scope |
| https://learn.microsoft.com/windows/uwp/ui-input/gaze-interactions | Windows API, capability, privacy |
| https://learn.microsoft.com/en-us/uwp/api/windows.devices.input.preview.gazepointpreview | GazePointPreview members and DIP remark |
| https://learn.microsoft.com/uwp/api/windows.devices.input.preview.gazeinputsourcepreview.getforcurrentview | UI-thread and consent |
| https://support.microsoft.com/help/4043921/windows-10-get-started-eye-control | Eye Control device list and versions |
| https://support.apple.com/guide/iphone/control-iphone-with-the-movement-of-your-eyes-iph66057d0f6/ios | iPhone Eye Tracking (search summary only) |

Nothing about this repository or its user was sent to any of these sites.
