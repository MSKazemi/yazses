# ThinkGear first-device report: template

> **This is a blank template, not a result.** Every `«fill: …»` cell is an instruction. None of them
> is a measurement. A copy with any `«fill` marker left in it is not a finished report. Make a dated
> copy (for example `YYYY-MM-DD-thinkgear-first-device-report.md`), fill it from the local session
> sheet of the [day-one bench runbook](thinkgear-day-one-bench-runbook.md), and delete this box.

| Field | Value |
|---|---|
| **Study** | [#832](https://github.com/MSKazemi/yazses/issues/832) (BIO-TG-05), one subject, one unit. Feeds the claims decision in [#833](https://github.com/MSKazemi/yazses/issues/833). |
| **Method** | [Biosignal validation protocol](../specs/biosignal-validation-protocol.md), sequenced by the [bench runbook](thinkgear-day-one-bench-runbook.md) |
| **Report date** | «fill: date written» |
| **Unit received / sessions run** | «fill: date received» / «fill: first and last session dates» |
| **Outcome** | «fill: exactly one of `PASS (limited feasibility)`, `FAIL`, `INCONCLUSIVE`, `BLOCKED`, as defined in #832» |

The report covers the three measures committed in public:

1. data-stream stability;
2. the double-blink detection rate;
3. false triggers during one hour of everyday use.

It gives raw numbers for each, and the method behind each number. The same structure is used
whether the result is good, bad or blocked.

## 1. What was tested

Hardware is described in words. **Never** put the Bluetooth address, a pairing code, the user name,
a serial port path from a private machine, a photograph or any personal detail in this table.

| Item | Value |
|---|---|
| Product and model string (as printed on the unit or box) | «fill» |
| Hardware revision / firmware (or "not observable") | «fill» |
| Electrode | «fill: e.g. one dry forehead electrode; ear-clip reference fitted yes/no» |
| Placement in words | «fill» |
| Transport | «fill: Bluetooth SPP bound with `rfcomm` / other / none found» |
| Host-side baud in the source spec | «fill: 57600 default, or what was used and why» |
| Linux distribution, kernel, BlueZ version | «fill» |
| Bluetooth adapter (model only) | «fill» |
| Power during sessions | «fill: laptop on battery / on mains; headset battery state» |
| YazSes version and commit | «fill: `yazses --version` line and `git rev-parse --short HEAD`» |
| Open ThinkGear hardening issues at that commit | «fill: state of #828, #829, #830, #831» |
| Frozen `[biosignal]` section | «fill: paste it verbatim» |
| `mains_hz` | «fill» |
| Calibration profile age at each scored session | «fill: from `yazses biosignal profile`» |
| Configurations | «fill: how many. A reseat with a fresh calibration counts as a new one. Keep the rows below per configuration.» |

## 2. Session conditions

One row per session, scored or not.

| Session | Date | Configuration | Kind (bench / field-test / everyday / live) | Room and activity, in words | Deviations from the runbook |
|---|---|---|---|---|---|
| «fill» | «fill» | «fill» | «fill» | «fill» | «fill» |

## 3. Measure 1: data-stream stability

### 3.1 Raw link (runbook hypotheses H1 to H7)

| Hypothesis | Held? | What was observed (exact text where there is text) |
|---|---|---|
| H1 discoverable with stock BlueZ, no vendor app | «fill: yes / no» | «fill» |
| H2 pairs with a standard agent | «fill» | «fill» |
| H3 Serial Port UUID advertised | «fill» | «fill: the UUIDs listed» |
| H4 `rfcomm` available | «fill» | «fill: the package that provided it» |
| H5 RFCOMM channel | «fill» | «fill: the channel that worked, and what was tried» |
| H6 TTY permissions | «fill» | «fill» |
| H7 raw at the default baud | «fill» | «fill» |

If H1 to H5 failed, the remaining sections record **not run**, and the outcome is `BLOCKED: raw
transport unavailable`.

### 3.2 Packet integrity and throughput

These numbers come from `tally.py` (runbook section 5.1). Run it once worn and once not worn. Copy
its output lines as printed.

| Run | `elapsed_s` | `raw_samples_per_s` | `longest_silence_s` | `packets_ok` | `bad_checksum` | `bad_length` | `malformed` | `skipped_bytes` | `rejected_fraction` |
|---|---|---|---|---|---|---|---|---|---|
| worn, still | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» |
| not worn | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» |

How to read this table:

- **Packet reject rate:** `rejected_fraction` = (`bad_checksum` + `bad_length` + `malformed`) / (all packets). ThinkGear packets carry no sequence number. So the number of **samples** lost to a rejected packet is **unknown**, and it is reported as unknown, not estimated (ADR-v2-155, decision 5).
- **Throughput:** the nominal rate is 512/s. A nominal constant is not a measurement. Only `raw_samples_per_s` and `check-source`'s `rate_arrival` are measurements.

### 3.3 Source-contract check

From `yazses biosignal check-source thinkgear:<port> --seconds 30` (and its `--json` file):

| Run | Summary line (verbatim) | Clauses not `PASS` (name and detail) | `no_stall` detail | `rate_arrival` detail |
|---|---|---|---|---|
| «fill» | «fill» | «fill» | «fill» | «fill» |

### 3.4 Stalls

| Source of evidence | Count | Over what duration | Command |
|---|---|---|---|
| `check-source` `no_stall` failures | «fill» | «fill» | runbook 5.2 |
| `Events HELD` lines in the monitor logs | «fill» | «fill» | `grep -c "Events HELD" <log>` |
| Runs that ended with "stopped streaming" or "not available" | «fill» | «fill» | read the end line of each log |

### 3.5 Contact quality, as time fractions

There are two different contact signals. Report them separately, and never merge them.

| Signal | Bins | Fraction | Method and caveat |
|---|---|---|---|
| Headset `POOR_SIGNAL` reports, worn | zero / 1–199 / 200 / 201–255 | «fill: count in each bin, and each count over the total» | `tally.py` counts. The reports come about once a second, so a share of reports only **approximates** a share of time. |
| Headset `POOR_SIGNAL` reports, not worn | same | «fill» | This is the falsification check. If removing the headset does not move reports away from zero, contact health is unobservable, which is a stop condition. |
| Waveform quality gate, per field-test phase | usable / degraded / excluded seconds | «fill: `usable_s`, `degraded_s`, `excluded_s` and `quality_fraction` from each JSON» | Computed by YazSes from the waveform, not by the headset. On the commit tested it ignores `POOR_SIGNAL` (#829). |

### 3.6 Provocations (runbook Stage D)

| Action | Did quality go `bad` or the integrity gate close? | Any `double_blink` while provoked? | Recovery observed |
|---|---|---|---|
| Forehead electrode lifted for about 10 s | «fill» | «fill: any yes is a safety finding» | «fill» |
| Ear clip lifted | «fill» | «fill» | «fill» |
| Headset off, then on | «fill» | «fill» | «fill» |

## 4. Measure 2: deliberate double-blink detection rate

The source is the `gesture_double_blink` phase of the field-test JSON files. Pool them with
`FieldTestAggregate`, which adds the counts and recomputes the bounds. Pool **one configuration at a
time** (protocol, "Aggregation", rule 3). Save this as `~/tg-pilot/pool.py`:

```python
import json
import sys

from yazses.biosignal.evaluate import _poisson_upper
from yazses.biosignal.fieldtest import FieldTestAggregate, report_from_dict
from yazses.biosignal.fprate import wilson_interval

reports = []
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as handle:
        reports.append(report_from_dict(json.load(handle)))
pooled = FieldTestAggregate(reports).report()
print(f"sessions={pooled.sessions} verdict={pooled.verdict.value}")
for p in pooled.phases:
    if p.expects_intent:
        lo, hi = wilson_interval(p.hits, p.cues_scored)
        print(f"{p.name}: status={p.status} hits={p.hits} scored={p.cues_scored} "
              f"voided={p.cues_voided} extra={p.extra_activations} "
              f"wilson95=[{lo:.3f}, {hi:.3f}]")
    else:
        hours = p.usable_s / 3600
        upper = _poisson_upper(p.phantom_activations, hours)
        approx = p.phantom_upper_per_hour
        print(f"{p.name}: status={p.status} usable_s={p.usable_s} excluded_s={p.excluded_s} "
              f"phantoms={p.phantom_activations} "
              f"exact_upper95_per_h={'-' if upper is None else f'{upper:.2f}'} "
              f"approx_upper95_per_h={'-' if approx is None else f'{approx:.2f}'}")
```

```sh
uv run python ~/tg-pilot/pool.py ~/tg-pilot/ft-*-s*.json      # the files of ONE configuration
```

`report_from_dict` recomputes every derived number from the stored counts, so a file cannot disagree
with itself. The aggregate cannot detect duplicates, so list each file once.

| Configuration | Sessions | Hits | Scored cues | Voided cues | Extra activations | Hit rate | 95% Wilson interval | Median cue-to-event s (from each report; includes reaction time) |
|---|---|---|---|---|---|---|---|---|
| «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill: hits over scored» | «fill: `wilson95` from `pool.py`» | «fill» |

To check a single interval by hand, `fprate.wilson_interval` is the same function `pool.py` calls:

```sh
uv run python -c "import sys; from yazses.biosignal.fprate import wilson_interval as w; print([round(x, 3) for x in w(int(sys.argv[1]), int(sys.argv[2]))])" HITS SCORED
```

How to read the interval:

- Read the **lower** end. ADR-v2-152 gate A2 asks for a lower bound of at least 0.80 for the double blink. With no misses, that needs 16 scored cues, and one session scores at most 8.
- Meeting that bound with one subject is still **not** A2. A2 is pooled over the participants of gate A0.
- The tool's own `usable` verdict judges the point estimate. It is not this gate.

## 5. Measure 3: false triggers during one hour of everyday use

### 5.1 The everyday hour (runbook Stage G, `monitor`, nothing acted on)

| Item | Value | Where it comes from |
|---|---|---|
| Activities during the hour, in words | «fill» | session sheet |
| Deliberate double blinks during the hour | «fill: should be none; if any, how many, and how they were excluded» | session sheet |
| False triggers `k` | «fill» | the `double_blink` row of `Detections:` (**not** the `Measured:` rate, which includes single blinks) |
| Usable exposure `h` | «fill: minutes from the `Measured: … over N min` line, and the same in hours» | ungated ledger time. The waveform gate and the integrity gate remove time from it; `POOR_SIGNAL` does not (#829). |
| Wall-clock duration | «fill» | log start and end |
| `Events HELD` lines | «fill» | `grep -c` |
| Phantoms per usable hour | «fill: k over h» | arithmetic |
| One-sided 95% upper bound, exact Poisson | «fill» | the command below |

```sh
uv run python -c "import sys; from yazses.biosignal.evaluate import _poisson_upper as u; print(round(u(int(sys.argv[1]), float(sys.argv[2])), 2))" K HOURS
```

`_poisson_upper` is a private helper of `yazses.biosignal.evaluate`, and no CLI exposes it. It is the
exact limit for counts up to 1000. For zero events it gives 2.9957 events over the exposure, not the
rule-of-three 3.

### 5.2 Field-test no-intent phases (protocol "Phantom activations")

Fill one block per configuration, from `pool.py`. "Exact upper" is the exact Poisson limit.
"Approximate upper" is the Wilson-Hilferty bound the field-test prints. Report both, and read the
exact one. The phase list matches the protocol.

| Phase | Status | Usable s | Excluded s | Phantoms | Per usable hour | Exact upper 95% /h | Approximate upper 95% /h |
|---|---|---|---|---|---|---|---|
| `rest` | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» |
| `speech` | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» |
| `chew` | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» |
| `hands_busy` | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» |
| `movement` | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» | «fill» |

Gate A1 of ADR-v2-152 needs an upper bound of at most 6 per hour in `rest`, `hands_busy`, `speech`
and `chew`. With no phantom seen, that takes about half an hour of pooled usable signal in each of
those phases. Say plainly how far short of that this pilot is. The weighted workday figure is an
assumed activity mix, not data: quote it only beside the per-phase rows, if at all.

## 6. Calibration (gate A3 fields)

| Configuration | Attempts | Wall-clock time to a written profile | Succeeded? | Exact failure text, if any |
|---|---|---|---|---|
| «fill» | «fill» | «fill» | «fill» | «fill» |

## 7. Safety: stuck-mic count and the stress subset

**Live activation status:** «fill: one of `run on commit …, after #829 merged`, or `not exercised:
blocked on #829`».

| Stress case (protocol "Stress tests") | Injected on hardware? | Activation from an untrusted window? | Daemon survived? | Notes |
|---|---|---|---|---|
| Electrode lift-off | «fill» | «fill» | «fill» | «fill» |
| Electrode pop (tap) | «fill» | «fill» | «fill» | «fill» |
| Mains burst (appliance) | «fill» | «fill» | «fill» | «fill» |
| Headset power-off mid-session | «fill» | «fill» | «fill» | «fill» |
| Daemon `SIGKILL` and restart | «fill» | «fill» | «fill» | «fill» |
| Global pause and resume | «fill» | «fill» | «fill» | «fill» |
| Laptop suspend and resume | «fill» | «fill» | «fill» | «fill» |

| Stuck-mic events (protocol definition) | Over what live exposure | How observed |
|---|---|---|
| «fill» | «fill» | «fill» |

The default mapping sends a double blink as a one-shot `undo` intent. No microphone hold is opened,
so the hold-release path is barely exercised in this configuration. A zero here is weak evidence,
and the report says so. A single stuck-mic event is a failure, not a data point.

Live ledger, if it was run: «fill: the `yazses biosignal report` line».

## 8. Failures and limitations

List every failure, with its exact error text. Then keep the standing limitations that apply, and
delete only the ones that were demonstrably removed on the commit tested (cite the issue that
removed each).

- «fill: failures, in order of occurrence»
- **One subject, one unit, one or few configurations.** This is not a population estimate, and it is not ADR-v2-152 A0 (five participants, two configurations).
- **No contact-health veto on the commit tested** (#828, #829): `POOR_SIGNAL` was recorded but did not gate events.
- **The field-test had no integrity guard** (#830): its usable exposure was not reduced by stream-integrity faults.
- **Lost samples are unknowable:** ThinkGear has no sequence numbers or sensor timestamps.
- **The µV scale is nominal**, with no per-headset gain calibration, and the spec has no `uv_scale` option.
- **Cue latency includes reaction time.** It is not detector latency.
- **Detector thresholds were not retuned on scored data.** If any retune happened between rounds, say what changed and why, and which later round evaluated it.
- **The everyday hour describes one person's one hour**, with the activities as listed above.

## 9. Claim boundary

Keep exactly one of these two sentences, and delete the other. No sentence in this report may go
further than the one kept.

- **Tested with one unit/configuration under described conditions; experimental.** «fill: only if a local raw link was observed, the contact signal responded to removal, the stream checks passed, and no safety failure occurred. Then name the exact model string, commit and distribution.»
- **Not qualified / inconclusive.** «fill: which gate or stop condition, from runbook section 12, and the evidence for it»

What this report never says, whatever the numbers:

- that the switch "works", is "accurate" or is "reliable" without the bound and the exposure beside it;
- anything about other units, firmware, people or operating systems;
- anything medical, or anything about thought, attention or emotion;
- that ADR-v2-152 is Accepted, or that the experimental label can go.

The default stays off (AGENTS.md rule 2).

## 10. Evidence and privacy checklist (gate A6)

- [ ] The field-test JSON files were read before sharing. They contain counts, whole-second durations, phase labels and cue latencies only, with no signal, thresholds, profile or event timestamps.
- [ ] No raw recording, profile, monitor log, screenshot of the signal, photograph, Bluetooth address, pairing code, user name or personal detail is attached or quoted.
- [ ] Every number above can be traced to a command in this template or in the runbook, and the commit it ran on is stated.
- [ ] Negative and inconclusive results are reported as plainly as positive ones.
- [ ] The maintainer's support or no-support decision is recorded in #833, not here.
