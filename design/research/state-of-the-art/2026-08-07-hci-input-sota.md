# State of the Art: Gaze, EMG, BCI, and Multimodal Input (2025–2026)

**Date:** 2026-08-07 · **Tier:** `design/` — public engineering research
**Companion:** [local/offline STT engine SoA](2026-08-07-stt-engine-sota.md) ·
[voice-dictation market landscape](2026-08-07-competitor-landscape.md) ·
[ADR-v2-129: Killer Features 10x](../../adr/adr-v2-129-killer-features-10x.md) ·
[the v2 cognitive layer](../../v2-cognitive-layer/)

Feasibility ratings below are scoped to integration into a CPU-only, offline,
Linux-first Python daemon.

## 1. Webcam-based gaze tracking

- **License structure:** nearly every pretrained appearance-based gaze model carries
  non-commercial taint through its training data (Gaze360, ETH-XGaze CC BY-NC-SA,
  MPII), even where the code itself is MIT-licensed — L2CS-Net's published weights
  included. MediaPipe is the cleanly-licensed option among the ones surveyed. (The
  PyPI package named `l2cs` is unrelated to the L2CS-Net model — a naming trap worth
  flagging for anyone else evaluating this space.)
- **Realistic accuracy:** 1° of gaze angle corresponds to roughly 0.9–1.2 cm at
  50–70 cm viewing distance. Uncalibrated webcam gaze runs ~4° error; with
  person-specific calibration, ~2–3°; implicit calibration from mouse clicks reached
  2.9° (Sugano et al., IEEE 7050250); EyeMU measured 1.7 cm on-phone. Dedicated IR
  hardware (Tobii/Vision Pro) reaches ~1°. **Plain webcams support coarse zone/window
  targeting, not caret-level precision** — that is a property of the sensor, not an
  implementation gap. Progress in 2025–26 has been in CPU efficiency
  (MobileGaze ONNX/CPU), not in accuracy.
- **Calibration:** explicit 9-point calibration drifts within a session. The
  field's answer is implicit calibration from mouse clicks — a click is a strong
  proxy for where the eyes were looking ~100 ms earlier — reaching 2.9° with zero
  explicit calibration steps (SalGaze/vGaze/EyeO extend the idea).
- **Interaction research:** a CHI 2026 scoping review (103 studies) converges on a
  pattern: gaze grounds or disambiguates speech, and a second, cheap modality commits
  the action (Vision Pro's gaze+pinch, Talon's gaze+pop, MAGIC warping reporting
  +20.7% throughput). Google's Look to Speak demonstrates that coarse, three-way
  webcam gaze selection ships on-device today.
- **Commercial watch:** Beam Eye Tracker (Eyeware) shipped a Linux+macOS public beta
  on 2026-07-23, $29.99 one-time, with a PyPI `beam-eye-tracker` package — the first
  turnkey commercial webcam-gaze SDK with a Linux Python path.

Feasibility: **high** — implicit click-based calibration and gaze-grounded command
disambiguation (deixis) are CPU-trivial additions on top of an existing gaze pipeline.

## 2. Consumer/prosumer EMG

- **Meta Neural Band (Ctrl-Labs):** shipped 2025-09-30 bundled with the $799 Ray-Ban
  Display, US-only, with expansion paused as of 2026-01. Its developer toolkit
  exposes six fixed gestures with no raw EMG access and no Linux/Python path, which
  rules it out as a general-purpose trigger. The underlying science is notable
  (Nature 2025's generic neuromotor interface work reports >90% cross-user accuracy
  and 20.9 WPM handwriting-style decoding); released datasets and checkpoints are
  CC-BY-NC and tied to Meta's specific 16-channel/2 kHz hardware geometry. The paper
  does not report latency or false-activation rate.
- **Buyable Linux/Python hardware, ranked by fit:** (1) MindRove Armband — 8ch at
  500 Hz, raw data, an official Linux+Python SDK, also supported by LibEMG; (2) Mudra
  Link ($199) — continuous pressure 0–100% with sub-10 ms latency claims, but its
  host application is macOS/Windows only; (3) OpenBCI Cyton/Ganglion with BrainFlow
  (MIT-licensed), fully open and offline; (4) second-hand Myo devices via `pyomyo`;
  (5) DIY MyoWare 2.0 (~$50) or BioAmp EXG Pill (CERN-OHL) — sensors that map
  naturally onto a serial-protocol activation backend.
- **What's decodable today:** discrete gesture classification is a solved problem
  (92–96% accuracy; zero-shot cross-user generalization is the 2024–26 advance,
  e.g. ReactEMG at 92%). Continuous squeeze-force regression is comparatively
  underused despite strong results (grip-force regression r=0.97). Because EMG typing
  tops out around 20.9 WPM against ~150 WPM for speech, **EMG's most defensible role
  in a dictation product is as a trigger, not as a text-entry channel.**
  Squeeze-onset latency of 35–125 ms (threshold/TKEO/GMM methods) is well under the
  perceptible-delay threshold. The metric that is *not* published anywhere surveyed
  here, and is the one that would actually gate a design decision, is
  false-activation rate.
- **Software:** LibEMG (`pip install libemg`; supports Myo/MindRove/SiFi/OYMotion)
  and BrainFlow (MIT) are the standard offline Linux stacks for this hardware class.

Feasibility: **medium-high** — device breadth and graded-pressure semantics are
achievable in pure Python, fully offline.

## 3. Consumer BCI/EEG

- The most credible offline option is Muse 2/S/Athena — raw EEG over plain BLE, no
  account required, via `muselsl` or BrainFlow ≥5.22.0 (2026-05). Neurosity Crown
  claims cloud dependence (a BrainFlow-based local workaround exists); Emotiv's raw
  EEG access is behind a paid license; Galea is a ~$25k enterprise headset; Neurable
  has no public SDK; PiEEG (~$350) is the open DIY path.
- Switch-grade signals from consumer EEG are muscle/eye artifacts, not decoded
  intent: blink detection reaches ~99.5% accuracy at ~1.3 s latency with 0.10 false
  positives/minute (roughly 50 phantom activations across a workday in the worst
  case); jaw-clench detection reaches ~90% but is confounded by the act of
  talking — which rules it out for a dictation product specifically. SSVEP needs
  occipital electrode placement and a continuously flashing visual stimulus;
  motor-imagery approaches need 3–10 training sessions and fail outright for an
  estimated 15–30% of users.
- A dedicated EMG electrode strictly dominates EEG-artifact detection on signal
  quality, latency, and false-positive rate for this use case. If EEG were ever
  added, the honest framing is a double-blink/jaw-clench accessibility switch via
  Muse+BrainFlow — not a headline capability.

Feasibility: **low** for anything beyond an accessibility-switch role.

## 4. Multimodal fusion and silent speech

- **Voice+gaze deixis** — resolving "this"/"that" against where the user is looking
  — traces from Bolt's "Put-That-There" (1980) through GazePointAR (CHI 2024),
  G-VOILA, GazeGPT, and SemanticScanpath (2025). All use late fusion: the gaze target
  is serialized alongside the transcript rather than fused at the model level.
  Quantified payoff: +26.5% coreference accuracy on demonstratives (arXiv
  2509.08689). EyeSayCorrect (IUI 2022) built desktop gaze+speech editing before the
  field's attention moved to AR glasses; as of this survey, no open-source desktop
  gaze-zone-plus-ASR deixis system was found.
- **Silent speech:** AlterEgo was spun out in 2025 with no announced ship date; the
  open sEMG-to-speech research line (Gaddy & Klein) sits around 68% WER on
  open-vocabulary decoding — research-grade, not product-grade. Lip
  reading/audio-visual ASR (Auto-AVSR, Whisper-Flamingo) performs strongly but every
  surveyed pretrained checkpoint carries a non-commercial license and none run
  CPU-real-time.
- **Whispered speech is a notable sleeper result:** off-the-shelf Whisper runs
  ~18.8% WER on whispered speech versus 2–6% for voiced speech, but a per-user
  fine-tune drops that to 0.38% — speaker-dependent whispered ASR is effectively a
  solved problem. DualVoice (UIST 2022, Rekimoto) demonstrated the resulting design
  pattern: whispered speech routes to commands, normal voice routes to literal text,
  on a plain microphone. Distinguishing whispered from voiced speech is CPU-trivial —
  whisper has no fundamental frequency, so an autocorrelation-based voicing check
  (80–450 Hz) combined with zero-crossing rate and energy is sufficient.

Feasibility: **high** for gaze-grounded deixis and whisper/voice detection (both
zero new dependencies on an existing gaze/audio pipeline); **low** for lip reading;
**not viable at present** for silent-speech sEMG.

## 5. Accessibility

- Talon offers a free tier that runs on-device, but its eye-tracking mode needs
  Tobii hardware, and the project states plainly that Wayland support is not
  planned. Commercial AAC eye-gaze systems (TD Pilot ~$10k, TD I-Series ~$20k) are
  Windows/iPad-only, and insurance approval delays access further.
- The Linux/Wayland accessibility-input landscape has several abandoned or broken
  tools: eViacam has been unmaintained since ~2019, Google's Project Gameface was
  archived in 2025-09, mousetweaks' dwell-click is broken on Wayland, and GNOME's
  Newton still cannot synthesize mouse events there. Dragon-dependent users migrating
  off Windows have essentially one free-software peer, Numen.
- The resulting gap an offline, open-source Linux tool could address: Wayland-capable
  voice control, a maintained webcam head/face mouse (no actively maintained
  competitor found), dwell-click via `libei`, and a free alternative to the
  $10–20k Windows-locked AAC price point. Advocacy groups such as Team Gleason have
  publicly called for cheaper open communication technology.

## Summary of buildable directions identified

1. **Deixis resolution** — resolving "close this"/"put it there" against the gaze
   zone or window already tracked at hold-start. No new dependencies once a gaze
   pipeline exists; no open-source desktop equivalent was found.
2. **Implicit gaze calibration from mouse clicks** — incremental refinement of an
   affine calibration map from ordinary clicks (2.9° reported in the literature).
3. **A whispered-speech command channel** — a numpy-only fundamental-frequency gate;
   a whispered burst routes to commands, voiced speech dictates (the DualVoice
   pattern). No dictation product surveyed has this.
4. **EMG device breadth and squeeze-pressure semantics** — BrainFlow/LibEMG adapters
   behind a pluggable backend interface; a light squeeze for talk, a hard squeeze for
   command; publishing a measured false-activation rate rather than assuming one.
5. **A hands-free accessibility profile** — dwell-to-talk on gaze zones plus
   head-nod/jaw-open/brow-raise switches from an already-running face-landmark model,
   with `uinput`/`libei` injection for Wayland compatibility. No actively maintained
   competitor was found on Linux for this combination.

**Explicitly not recommended, given the evidence above:** consumer EEG as anything
beyond an accessibility switch, lip-reading/AVSR, silent-speech sEMG, and the Meta
Neural Band as an integration target. Worth continuing to watch: a Linux SDK from
Beam Eye Tracker, and a Linux host application for Mudra Link.

### What this study fed into

This study, together with [the STT engine SoA](2026-08-07-stt-engine-sota.md), was
direct research input to [ADR-v2-129](../../adr/adr-v2-129-killer-features-10x.md),
which shipped gaze deixis, the sotto-voce whispered-command channel, and the
pluggable activation-source seam that the EMG backend now uses. See
[the v2 cognitive layer](../../v2-cognitive-layer/) for the design notes on what was
built from this, and `design/adr/` for the individual ADRs (search "gaze", "EMG", or
"sotto-voce").
