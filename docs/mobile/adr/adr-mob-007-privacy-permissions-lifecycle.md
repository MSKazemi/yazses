# ADR-MOB-007 — Android privacy budget: permission minimalism, one networked module, CI-enforced

**Status:** Accepted (2026-08-07) · design only, no code yet
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-011]] (the parent policy), [[adr-mob-003]] (no accessibility grant),
[[adr-mob-004]] (no ambient capture), [[adr-mob-006]] (the only network use),
[[adr-mob-009]] (store declarations)

---

## Context

[[adr-011]] is the project's constitutional document: zero telemetry, offline by default,
no cloud fallback, no ambient capture, local-only logs, CI-enforced. It was written for a
desktop daemon. Android changes the enforcement surface in ways that need to be made
explicit before contributors start adding dependencies:

- An Android app's privacy posture is largely determined by its **manifest** and by the
  **transitive dependencies** of its modules — an SDK three levels down can add `INTERNET`
  and phone-home behaviour that no reviewer notices in a diff.
- A keyboard is the single most sensitive app class on the platform. The system itself
  warns the user that a keyboard "may be able to collect all the text you type", and users
  are right to be suspicious. Trust here must be *demonstrable*, not asserted.
- Android 14+ requires typed foreground services, and `RECORD_AUDIO` is a while-in-use
  permission: a `microphone` FGS cannot be started from the background, and Android 15+
  applies time limits to several FGS types. Long-running capture (Meeting Mode) must be
  designed against these rules, and the rules move with target SDK.
- Both stores require a data-safety / privacy declaration even for apps that collect
  nothing, and those declarations must match the binary.

## Decision

**A. Permission budget (the manifest is a reviewed artefact).**

| Permission | Where | Why |
|---|---|---|
| `RECORD_AUDIO` | `:platform:audio` | the product. Declared beside the code that opens the microphone rather than in `:app`, so it travels with that code and the manifest gate reports it if it ever moves. Manifest merging puts it in the app either way. |
| `INTERNET` | **`:model` only** | model download ([[adr-mob-006]]) |
| `POST_NOTIFICATIONS` | `:app` | Meeting Mode ongoing notification, download status |
| `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_MICROPHONE` | `:feature:meeting` | long capture |
| `SYSTEM_ALERT_WINDOW` | `:feature:bubble` (opt-in variant) | floating mic ([[adr-mob-003]] §5) |

Everything else is **forbidden without a superseding ADR** — explicitly including
`READ_EXTERNAL_STORAGE`/`READ_MEDIA_*` (use SAF), `ACCESS_NETWORK_STATE` outside `:model`,
`BIND_ACCESSIBILITY_SERVICE`, contacts, phone state, location, and `QUERY_ALL_PACKAGES`.
A PR that adds a manifest permission must change this table in the same PR.

**B. Network containment.** `INTERNET` is declared only in `:model`'s manifest, and only
`:model` may depend on an HTTP client. A Gradle dependency-analysis check fails the build
if any other module (transitively) pulls in OkHttp/Retrofit/Ktor-client or declares a
network permission. The dictation path — `:core:audio` → `:core:vad` → `:core:stt` →
`:core:postprocess` → `:feature:ime` — has no reachable network code, and that is a
build-enforced property rather than a promise.

**C. CI privacy gate** (the Android analogue of [[adr-011]] §10, and of the desktop's
`privacy-gate` job):
1. **Manifest diff gate** — the merged manifest is dumped and compared against a checked-in
   golden file; any new permission, exported component, or `usesCleartextTraffic` change
   fails until the golden file and the table above are updated in the same PR.
2. **Dependency allow-list** — the full transitive dependency graph is compared against a
   checked-in allow-list; new artefacts require review. No analytics/crash SDK may ever
   enter it.
3. **Airplane-mode instrumentation test** — a full dictation round trip (audio fixture →
   text delivered to a test `InputConnection`) runs with networking disabled on the
   emulator and must pass.
4. **No-logging-of-content check** — a lint rule forbidding transcript text or raw audio in
   any log statement. Diagnostics are metadata only (durations, sizes, states), matching
   the desktop's `yazses logs`.

**D. Lifecycle and capture rules.**
- Hold-to-talk needs no foreground service: the IME window is visible, so the app is
  in-use ([[adr-mob-004]]).
- Meeting Mode runs a `microphone`-typed foreground service **started from a visible,
  user-initiated action** (Quick Settings tile, shortcut, or in-app button), with a
  permanent notification carrying elapsed time and a stop action. Android 15+ FGS
  time-limit behaviour for this type is an **open risk with a dedicated spike issue**: the
  design requirement is that reaching a system limit *finalises and saves the meeting*
  (the desktop's `max_minutes` auto-stop behaviour) and never loses recorded audio.
- Capture stops immediately on: mic permission revoked, another app taking the mic
  (`AudioManager` focus/recording callbacks), a password field gaining focus, or the
  session cap being reached.
- **The microphone indicator is never suppressed** and no attempt is made to work around
  privacy indicators, hidden-API restrictions, or battery-optimisation prompts beyond
  documented, user-visible settings.

**E. Data at rest.** Transcripts are not persisted at all in wave 1 unless the user is in
Meeting Mode or file-import, both of which write to app-private storage the user can see
and delete. If and when the desktop's learning corpus (`adr-012`) is ported, it arrives
**off by default with the same encryption-at-rest requirement**, as its own ADR. Nothing
is written to shared storage without SAF and an explicit user pick. Backups exclude models,
transcripts and any future corpus.

**F. Store declarations must match the binary** ([[adr-mob-009]]): "no data collected, no
data shared", with the model download described accurately as a user-initiated file
download to a third-party host.

## Consequences

- A contributor cannot accidentally weaken the privacy posture: the manifest gate and the
  dependency allow-list turn [[adr-011]] from a document into a build failure.
- Meeting Mode is the only genuinely hard lifecycle problem in the app, and it is scoped
  and risk-flagged rather than assumed to work.
- Some conveniences are permanently unavailable (crash reporting, remote config, A/B
  tests). Bug reports follow the desktop model: a local, user-reviewed report the user
  attaches by hand (`yazses report` is the desktop analogue).
- The app can make an unusually strong, checkable statement — *revoke network access and it
  still works* — which is the single best answer to "why not just use Gboard's offline
  voice typing".

## Rejected

- **`INTERNET` in `:app` "for convenience".** Destroys the containment property, which is
  the whole point.
- **Crash reporting, even self-hosted (e.g. an ACRA endpoint), even opt-in, in wave 1.**
  [[adr-011]] §1 is unambiguous; a local, user-reviewed crash log is the substitute. An
  opt-in local-file crash log is acceptable; anything that transmits is not.
- **Google Play Services / Firebase for anything** (including push, config or App Check) —
  also disqualifying for F-Droid.
- **Requesting all permissions up front at first launch.** Each is requested at the moment
  it is first needed, with an in-context explanation.
