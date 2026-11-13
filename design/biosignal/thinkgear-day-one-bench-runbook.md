# ThinkGear first-device bench runbook: day one on Linux

| Field | Value |
|---|---|
| **Status** | Proposed runbook. No physical unit has been paired, worn or measured. Every Bluetooth and serial step below is a hypothesis to check on the real unit. |
| **Date** | 2026-11-13 |
| **Code baseline** | `main` at `4a83e484`, `yazses 2.51.0` |
| **Hardware study** | [#832](https://github.com/MSKazemi/yazses/issues/832) (BIO-TG-05). Claims decision: [#833](https://github.com/MSKazemi/yazses/issues/833). Epic: [#826](https://github.com/MSKazemi/yazses/issues/826). |
| **Canonical method** | [Biosignal validation protocol](../specs/biosignal-validation-protocol.md). This runbook only sequences it for one ThinkGear unit. Where they disagree, the protocol wins. This runbook does not amend it. |
| **Safety contract** | [ADR-v2-155](../adr/adr-v2-155-thinkgear-transport-safety.md) (Proposed), [qualification spec](../specs/thinkgear-hardware-qualification.md) section 6, [ADR-v2-152](../adr/adr-v2-152-biosignal-artifact-switches.md) kill criteria |
| **Report** | Fill in [the first-device report template](thinkgear-first-device-report-template.md) |
| **Roadmap** | [First-device roadmap](2026-11-03-first-device-roadmap.md), gate G3 |

## 0. What this is and is not

This runbook is the ordered list of steps a person runs on a Linux machine the day a single
ThinkGear/TGAM headset arrives. The unit is a forehead dry electrode with an ear-clip reference,
sold as a BrainLink-class product. The steps produce the inputs for the committed written report,
which has three measures:

1. **Data-stream stability:** whether raw `0x80` samples arrive steadily, how often packets are rejected, how often the stream stalls, and what fraction of time the headset itself reports good contact.
2. **Deliberate double-blink detection rate:** hits over scored cues, with a Wilson interval.
3. **False triggers during one hour of everyday use:** a count, the usable exposure, and an exact one-sided Poisson upper bound.

The test has one subject (the maintainer). It is an engineering feasibility pilot under #832. It is
**not** a clinical study, not a usability study, and not evidence for ADR-v2-152's Tier 1 gates,
which require at least five participants on two configurations. The report is published whatever
the result: good, bad, blocked or inconclusive.

## 1. The state of `main` that shapes this day (checked 2026-11-13)

Three parts of the ADR-v2-155 hardening are still open on `main`. They change what a day-one run
can show:

| Open item | What it means today | Observed how |
|---|---|---|
| [#828](https://github.com/MSKazemi/yazses/issues/828) / [#829](https://github.com/MSKazemi/yazses/issues/829): contact-health veto | `POOR_SIGNAL` (code `0x02`) is parsed and kept as `ThinkGearSource.poor_signal`, but **no gate acts on it**. A headset reporting `200` (no skin contact) is gated only if the waveform also looks bad. | Code read: `src/yazses/biosignal/thinkgear.py` `read()`. Emulated: a byte stream reporting `POOR_SIGNAL=200` for 5 s on a pseudo-terminal still showed `quality good` in `monitor` during that window. |
| [#830](https://github.com/MSKazemi/yazses/issues/830): field-test parity | `field-test` feeds the raw source directly. `monitor` and the daemon wrap it in `IntegrityGuard` / `IntegrityGate`, but `field-test` does not, so a field-test's usable exposure is not reduced by stream-integrity faults. | Code read: `run_field_test` in `src/yazses/biosignal/cli_impl.py`. |
| [#831](https://github.com/MSKazemi/yazses/issues/831): ThinkGear diagnostics | No `yazses` command prints `POOR_SIGNAL` values or the parser's rejected-packet counters. `check-source` passed (17 pass, 1 skip, 0 fail) on an emulated stream that reported no contact for 7 of its 10 s. | Emulated run, section 5. |

Consequences for today:

- Day one is **observation only**: Stages A to G. Nothing is typed or acted on.
- Stage H (live activation) waits for #829. The reason: a lifted electrode would not stop a live switch, unless the waveform happens to look bad as well.
- Contact quality is counted by a short local script (section 5.1) until #831 adds a command for it.

## 2. Before the unit arrives

1. Update a checkout of `main` and install the serial extra into its environment:

   ```sh
   git pull --ff-only
   uv sync --extra emg
   uv run --extra emg yazses --version
   ```

   Write down the exact version line and `git rev-parse --short HEAD`.
   An installed copy works too: install `yazses[emg]` as in
   [the switch guide](../../docs/how-to/biosignal-switch.md#install-what-it-needs), and drop the `uv run --extra emg` prefix from every command below.
2. Re-check the flags. Run `uv run --extra emg yazses biosignal <command> --help` for each command in section 14. A flag in this runbook that `--help` no longer shows is a finding: record it, and do not guess a replacement.
3. Create a private working folder **outside the repository**, for example `~/tg-pilot/`. Make it owner-only (`chmod 700`). Everything this runbook writes goes there. Nothing in it is committed.
4. Copy the session sheet (section 11) into that folder, and fill in the fields you know before the unit arrives.
5. Set the configuration (section 4.3). Keep `enabled = false` for the whole of day one.

## 3. Stage A: Bluetooth discovery and pairing (every step is a hypothesis)

The NeuroSky protocol document says the byte stream "may be UART, serial COM, USB, bluetooth, file,
or any other mechanism which can stream bytes". It names no Bluetooth profile. The vendor's product
page advertises Bluetooth. Neither proves that the unit exposes a Serial Port Profile (SPP) channel
that Linux can bind ([evidence review](../research/2026-11-03-thinkgear-first-device-evidence.md)).
So treat each step below as an experiment, and record what actually happened.

| # | Hypothesis | Command | Falsified if |
|---|---|---|---|
| H1 | The powered-on unit is discoverable from a stock BlueZ stack, with no vendor app and no account. | `bluetoothctl`, then at its prompt: `power on`, `agent on`, `default-agent`, `scan on`. Wait for a new device name. Then `scan off`. | The unit never shows up, or only shows up to a phone app. |
| H2 | It pairs with a standard agent. | `pair <address>`, then `trust <address>` | Pairing is refused, or it needs a code that is not in the product's own documentation. Do not guess codes in a loop. |
| H3 | It advertises a Serial Port service. | `info <address>`: look in the UUID list for Serial Port (16-bit service class `0x1101`, see [Bluetooth Assigned Numbers](https://www.bluetooth.com/specifications/assigned-numbers/) and the [SPP specification](https://www.bluetooth.com/specifications/specs/serial-port-profile-1-2/)) | No Serial Port UUID is listed. Record the UUIDs that **are** listed, then stop at the `raw transport unavailable` outcome (section 12). |

The `bluetoothctl` commands are those of BlueZ 5.82
([bluetoothctl(1), Debian trixie](https://manpages.debian.org/trixie/bluez/bluetoothctl.1.en.html)):
`power` "Set controller power", `pair` "Pair with device", `trust` "Trust device", and `info`
"Device information". Record the BlueZ version (`bluetoothctl --version`), the kernel version
(`uname -r`) and the distribution. The device address goes on the **local** sheet only. It is never
written into the report, an issue or a commit.

## 4. Stage B: RFCOMM serial binding and baud rate (hypotheses)

### 4.1 Bind

[rfcomm(1)](https://manpages.debian.org/experimental/bluez/rfcomm.1.en.html) says `bind` "does not
establish a connection to the remote device, it only creates the binding. The connection will be
established right after an application tries to open the RFCOMM device. If no channel number is
specified, it uses the channel number 1." Linux exposes an RFCOMM binding as a TTY such as
`/dev/rfcomm0` ([kernel device list](https://docs.kernel.org/6.16/admin-guide/devices.html)).

| # | Hypothesis | Command | Falsified if |
|---|---|---|---|
| H4 | The distribution ships the `rfcomm` tool. Some distributions moved it into a separate "deprecated tools" package. | `command -v rfcomm` | Not found. Install it from the distribution's own BlueZ packaging, and record the package name. No third-party binaries. |
| H5 | The SPP service is on RFCOMM channel 1. | `sudo rfcomm bind 0 <address> 1`, then `rfcomm show 0` | Opening `/dev/rfcomm0` fails in section 5, or yields no bytes. Release with `sudo rfcomm release 0`. Find the channel from the service record rather than trying channels at random, and record what you tried. |
| H6 | The user running YazSes can open the TTY. | `ls -l /dev/rfcomm0` | Permission denied. Record the owning group, and fix it with the distribution's own mechanism (often a serial group). Never `chmod 666` a device node. |

### 4.2 Baud rate

The protocol document says 16-bit raw output "requires 57,600 baud and above". It also says modules
on firmware 1.7.13 and earlier "always start at 9600 baud". YazSes opens the port at 57600 by default
(`THINKGEAR_BAUD`). On an RFCOMM virtual TTY the host-side baud setting is usually not what sets the
headset's internal UART rate. The source module records this as **not verified** from a NeuroSky
document.

- **H7:** at the default 57600, `raw_samples_per_s` in section 5.1 is close to 512, and the rejected fraction is near zero.
- **Falsified if** raw samples are absent, or the rejected fraction is high. Then run the same check once with `thinkgear:/dev/rfcomm0:baud=9600`, and record both results. Do not keep cycling through baud rates.

### 4.3 Configuration

These are the spec forms that `parse_thinkgear_spec` accepts. They were checked by calling it on
2026-11-13:

| Spec | Parsed to |
|---|---|
| `thinkgear:/dev/rfcomm0` | `{'port': '/dev/rfcomm0'}` (57600 baud, channel `Fp1`) |
| `thinkgear:/dev/rfcomm0:baud=57600` | `{'port': '/dev/rfcomm0', 'baudrate': 57600}` |
| `thinkgear:/dev/rfcomm0:baud=57600,name=Fp1` | adds `'channel_name': 'Fp1'` |
| `thinkgear:` | `ValueError`: no serial port |
| `thinkgear:/dev/rfcomm0:uv_scale=1` | `ValueError`: unknown option. Only `baud` and `name` exist, so the nominal NeuroSky µV scale is always used. |

Put this in `config.toml`. The [configuration reference](../../docs/configuration.md#biosignal) is the
authority for the keys.

```toml
[biosignal]
enabled = false                 # day one is observation only; see Stage H
source = "thinkgear:/dev/rfcomm0"
mains_hz = 50                   # 60 in the Americas; record which
emg = false                     # no muscle channel on this headset (see below)
double_blink = true
jaw_clench = false
```

`emg = true` is the shipped default. If it stays on, `field-test` cues a squeeze phase that a
forehead EEG channel can never satisfy, and that phase drags the verdict down. Freeze this section
before the first scored session, and copy it verbatim onto the session sheet.

## 5. Stage C: is there a raw link, and is it healthy?

Run these in order. **Only one program may hold the port at a time**, so never run two of them at once.

### 5.1 Contact-report and packet tally (stopgap for #831)

No `yazses` command reports `POOR_SIGNAL` or parser rejections today, so this script uses the
public parser to count them. It prints counts only: no samples, no amplitudes and no timestamps.
Save it as `~/tg-pilot/tally.py`:

```python
import sys
import time

from yazses.biosignal.thinkgear import THINKGEAR_BAUD, ThinkGearParser, import_serial

port, seconds = sys.argv[1], float(sys.argv[2])
ser = import_serial().Serial(port, THINKGEAR_BAUD, timeout=0)
parser = ThinkGearParser()
reports = {"zero": 0, "1_to_199": 0, "200_no_contact": 0, "201_to_255": 0}
start = last_data = time.monotonic()
longest_silence = 0.0
try:
    while (now := time.monotonic()) - start < seconds:
        data = ser.read(4096)
        if not data:
            longest_silence = max(longest_silence, now - last_data)
            time.sleep(0.005)
            continue
        last_data = now
        for packet in parser.feed(data):
            q = packet.poor_signal
            if q is None:
                continue
            key = ("zero" if q == 0 else "200_no_contact" if q == 200
                   else "1_to_199" if q < 200 else "201_to_255")
            reports[key] += 1
finally:
    ser.close()
elapsed = time.monotonic() - start
st = parser.stats
total = sum(reports.values())
print(f"elapsed_s={elapsed:.1f} raw_samples={st.raw_samples} "
      f"raw_samples_per_s={st.raw_samples / elapsed:.1f} longest_silence_s={longest_silence:.2f}")
print(f"packets_ok={st.packets} bad_checksum={st.bad_checksum} bad_length={st.bad_length} "
      f"malformed={st.malformed} skipped_bytes={st.skipped_bytes}")
print(f"rejected_fraction={st.rejected_packets / max(st.packets + st.rejected_packets, 1):.5f}")
print("poor_signal_reports " + " ".join(f"{k}={v}" for k, v in reports.items()) + f" total={total}")
```

```sh
uv run --extra emg python ~/tg-pilot/tally.py /dev/rfcomm0 60      # headset worn, seated, still
uv run --extra emg python ~/tg-pilot/tally.py /dev/rfcomm0 60      # headset lying on the desk, not worn
```

The script was checked against a pseudo-terminal fed synthetic ThinkGear packets (512 raw/s, one
`POOR_SIGNAL` per second, `200` for 5 of 20 s). It printed `raw_samples_per_s=511.9` and
`poor_signal_reports zero=15 1_to_199=0 200_no_contact=5 201_to_255=0 total=20`. That shows the
script counts what it is fed. It says nothing about a real unit.

Record all four lines for both runs. The not-worn run is the falsification check for the contact
signal. If it does not report `200` (or at least nonzero) most of the time, the headset's contact
report cannot be trusted. That is a stop condition (section 12). `POOR_SIGNAL` is "typically output
every second", so the share of reports in each bin is an **approximation** of the share of time.
The report must say so.

### 5.2 Doctor, then the source-contract check

```sh
uv run --extra emg yazses biosignal doctor --source thinkgear:/dev/rfcomm0
uv run --extra emg yazses biosignal check-source thinkgear:/dev/rfcomm0 --seconds 30
uv run --extra emg yazses biosignal check-source thinkgear:/dev/rfcomm0 --seconds 30 --json > ~/tg-pilot/check-source-1.json
```

`doctor` does not open the device. On the emulated stream it printed `this check does not open the
device; yazses biosignal check-source thinkgear:… does` and ended with a `Verdict:` line. Record that
line. `check-source` takes the source as a **positional** argument, not `--source`. Record its
summary line and every clause that is not `PASS`, especially `no_stall` (the longest silence) and
`rate_arrival` (samples per second arriving against the declared 512 Hz). A failing clause stops the
day per protocol precondition 2: record it as the result.

`check-source` passing proves the stream keeps the block contract for 30 s. It does **not** prove
contact (section 1) or a usable gesture.

## 6. Stage D: watch it, then provoke it (observation only)

```sh
uv run --extra emg yazses biosignal monitor --source thinkgear:/dev/rfcomm0 --blink --no-emg --no-clench --seconds 300 --interval 1 | tee ~/tg-pilot/monitor-d1.log
```

During the five minutes, follow a fixed script and note on the sheet the wall-clock minute of each action:

1. Sit still for 60 s.
2. Make about five deliberate double blinks, spaced out.
3. **Lift-off:** lift the forehead electrode for about 10 s, then reseat it.
4. Do the same with the ear clip, if fitted.
5. **Range or power loss:** switch the headset off for about 10 s, then on again.

What to record from the log:

- Whether each lift-off produced `Signal quality: bad` or an `Events HELD: the stream-integrity gate is closed` line. Today it may produce neither, because of the #829 gap. **Any `double_blink` line printed while an electrode was lifted is a safety finding.**
- What happened on power loss. Did the command end with `Stopped (...)` and a reason? Did the stream come back without restarting the command? (On the emulator, a vanished port ended `field-test` with `stopped streaming ([Errno 5] Input/output error)`.)
- The `Detections:` table and the `Measured:` line at the end.

The log holds per-event times relative to the start. It stays in the private folder and is never
attached anywhere.

## 7. Stage E: calibrate

```sh
uv run --extra emg yazses biosignal calibrate --source thinkgear:/dev/rfcomm0 --blink --no-clench
uv run --extra emg yazses biosignal profile
```

Record three things (gate A3 of ADR-v2-152):

- the wall-clock time from starting `calibrate` to a written profile, electrode seating included;
- the number of attempts (on the emulator, the blink step gave up after 3 failed tries and exited 1);
- success or failure.

`profile` prints the board, the channels and the age, never thresholds. A failed calibration is a
result in its own right, so record it.

## 8. Stage F: field-test sessions on a frozen configuration

Freeze the configuration (section 4.3), the profile and the code revision. Then run the standard
session:

```sh
uv run --extra emg yazses biosignal field-test --out ~/tg-pilot/ft-<date>-s1.json
```

- **Use the standard length (`--minutes` omitted), or `--minutes 8` up to `--minutes 120`.** On `4a83e484`, `--minutes 1.5` and `--minutes 5` printed `This build cannot change the length of the test; running the standard one.` and fell back to the module default protocol. That default cues **all three** gestures, including the switches you turned off. Scaling only works from about 8 minutes upward. Whatever happens, record the phase list the run actually printed.
- Every session scores at most **8** double-blink cues, whatever `--minutes` says: the cue count is fixed and no flag changes it. Reaching the 16 scored cues that ADR-v2-152's 80% floor needs (with no miss) takes at least two complete sessions. Plan for more.
- Never overwrite a file: `--out` refuses an existing path. Use one file per session.
- Repeat on a different day and after reseating the electrode. A reseat with a fresh calibration counts as a **new configuration**, so keep its files apart.
- Do not change thresholds, the budget or the mapping between scored sessions of one round (see the protocol's "Tuning rounds").
- Because of the #830 gap, the usable exposure in these files is not reduced by stream-integrity faults. Section 5 and Stage D are the cross-check, and the report states the gap.

## 9. Stage G: one hour of everyday use (the committed false-trigger measure)

The protocol's no-intent phases are prompted activities. The committed measure is ordinary work.
`monitor` runs the same pipeline with the integrity gate and acts on nothing, so it measures this
without risk:

```sh
uv run --extra emg yazses biosignal monitor --source thinkgear:/dev/rfcomm0 --blink --no-emg --no-clench --seconds 3600 --interval 60 | tee ~/tg-pilot/everyday-<date>.log
```

Rules:

- During this hour, make **no deliberate double blinks**. Every `double_blink` detection is then, by construction, a false trigger. Do ordinary desk work (typing, reading, calls, drinking, looking around), and write on the sheet what was actually done.
- **The false-trigger count** is the `double_blink` row of the `Detections:` table, **not** the `Measured: … activations/h` line. That line counts every activating kind in the ledger, and single `blink` events are among them.
- **The exposure** is the duration at the end of the `Measured:` line (`over N min`). It is the ledger's ungated time: the waveform quality gate and the stream-integrity gate both remove time from it, but `POOR_SIGNAL` does not (the #829 gap). It prints in whole minutes from 90 s up to two hours. Also record the wall-clock duration and the number of `Events HELD` lines (`grep -c "Events HELD" everyday-<date>.log`).
- The headline bound is the exact Poisson one, computed as in the report template. One hour with zero false triggers bounds the rate at about 3 per hour (exactly 2.9957 events / 1 h), not at zero.

## 10. Stage H: live activation and the stress subset (held until #829 merges)

Do not set `enabled = true` until the contact veto (#829) is merged and the code revision is
recorded. If the six-week window closes first, the report says **live safety not exercised:
blocked on #829**. A gap reported honestly is better than a live run without the veto.

When it is allowed:

1. Keep a hardware keyboard and the normal hotkey in reach. Point focus at a scratch text editor, because a double blink maps to `undo` by default (`intent_map = { double_blink = "undo" }`).
2. Set `enabled = true` (and `[handsfree_safety]` if the global pause is to be tested), then run `uv run --extra emg yazses restart`.
3. Run the protocol stress cases that apply to a one-channel blink headset. Inject each once, on hardware:
   - electrode lift-off;
   - electrode tap (pop);
   - a mains appliance switched on nearby;
   - headset power-off mid-session (the stand-in for "USB unplug");
   - `kill -9` of the daemon, then `yazses start`;
   - `yazses handsfree pause`, then `resume`;
   - laptop suspend and resume.

   For each case record two things: did any action fire from an untrusted window, and did the daemon survive?
4. Count **stuck-mic events** as the protocol defines them. With the default mapping a double blink issues a one-shot intent and opens no hold, so this configuration cannot exercise the hold path much. The report must say that a zero here is weak evidence.
5. Afterwards: `uv run --extra emg yazses biosignal report` shows the live ledger. Record its line.

Any stuck-mic event, or any action from an untrusted window, fails the stress run (protocol, "Stress tests").

## 11. What to record (the local session sheet)

These stay in `~/tg-pilot/` and never leave the machine:

- **Hardware.** Product name and model string as printed on the unit or its box, revision, firmware if any tool shows it, electrode type, ear-clip use, and the placement in words.
- **Bluetooth.** The device address and any pairing code. These are **local only**: never in the report.
- **Host.** Distribution, kernel, BlueZ version, the Bluetooth adapter (model only), and laptop on battery or mains.
- **Software.** YazSes version line, `git rev-parse --short HEAD`, the frozen `[biosignal]` section, and the profile age from `profile`.
- **Per session.** Date, start time, room in words (e.g. "desk, mains laptop charger nearby"), what was done, and every deviation from the script.
- **Outputs.** The section 5.1 tally lines, the `check-source` JSON, the monitor and everyday logs, and the field-test JSON files.
- **Calibration.** Attempts, wall-clock time to profile, and success.
- **Failures.** Exact error text, as copied. Do not paraphrase it.

Only the filled-in [report template](thinkgear-first-device-report-template.md) is published, and
optionally the field-test JSON files after the participant has read them (protocol, "Reporting back").

## 12. Stop and kill criteria

Stop the device path, record the outcome, and write the report anyway, when any of these happens.
The first four are ADR-v2-155's "Revisit / kill" clause. The fifth is ADR-v2-152 kill criterion 3.
The last is the protocol's stress-test failure rule.

| Trigger | Outcome to record |
|---|---|
| The host cannot read raw `0x80` values without a cloud service, an account or a vendor app (H1 to H5 falsified) | `raw transport unavailable`: **not qualified / blocked** |
| Contact health cannot be observed with enough freshness: no `0x02` reports, or reports that do not change when the headset is removed (section 5.1) | **not qualified**: contact health unobservable |
| The firmware gives no dependable raw stream: `check-source` failures that recur across reseats, a persistent high rejected fraction, or repeated stalls | **not qualified**: unreliable stream |
| Any recurring stuck-action scenario after a fix | **fail**: stop. Do not keep guarding it. |
| A stuck-mic event that recurs after its fix and traces to the hardware path, for example a stream that looks healthy while it delivers stale data | **fail**: the source type is removed (ADR-v2-152 kill 3) |
| Any stuck-mic event, or any activation from an untrusted window, in the Stage H stress list | **fail** for that code revision. A fix restarts the whole list. |

Any of these is logged as a reproducible limitation. Never bypass the safety gate to get past one,
and never substitute a synthetic or emulated measurement for a real one. Changing these rules needs a
dated ADR amendment, not an edit to this runbook.

## 13. Privacy

- The raw signal, any `record` file, the calibration profile, the monitor logs (they carry per-event times), the device address and any pairing code all **stay on this machine**. Upload none of them to an issue, a pull request, a chat, or a cloud coding agent ([AGENTS.md](../../AGENTS.md), "Account, permission, and cost safety").
- What may be published: the filled-in report template (aggregate counts, durations, intervals and hardware in words) and, after they have been read, the field-test JSON files. Those files hold counts, whole-second durations, phase labels and cue-to-event latencies, and no signal (protocol, "Reporting back without raw signal").
- No photographs of the unit on a person, and no screenshots of the live signal.
- YazSes makes no network call at any step here. Pairing is a local Bluetooth action between the laptop and the headset.

## 14. Commands verified for this runbook

Each command below was run with `--help` on 2026-11-13 at `4a83e484` (exit 0). Only the flags it
printed are used above. `check-source`, `doctor`, `monitor`, `calibrate` and `field-test` were also
run against a pseudo-terminal fed synthetic ThinkGear packets. That checked their parsing and output
format only, not their behaviour on hardware.

| Command | Flags it showed |
|---|---|
| `yazses biosignal doctor` | `--boards`, `--source` |
| `yazses biosignal check-source [source]` | positional `source`; `--seconds`/`-s` (default 5.0; the code accepts values above 0 and up to 600); `--json` |
| `yazses biosignal monitor` | `--source`, `--seconds` (0 = until Ctrl-C), `--interval` (0.1 to 60), `--emg/--no-emg`, `--blink/--no-blink`, `--clench/--no-clench` |
| `yazses biosignal calibrate` | `--source`, `--blink/--no-blink`, `--clench/--no-clench`, `--yes`/`-y` |
| `yazses biosignal field-test` | `--source`, `--minutes` (0 to 120), `--json`, `--out`/`-o`. It has no detector-override flags: the switches come from `[biosignal]`. |
| `yazses biosignal profile` | `--json` |
| `yazses biosignal report` | `--json` |
| `yazses biosignal record` | `--out`/`-o` (required), `--source`, `--seconds` (1 to 86400), `--force`, `--seed`, `--truth-out`, `--json` |
| `yazses handsfree pause` / `resume` / `status` | none beyond `--help` |
| `yazses restart` / `start` / `stop` | `--force` (restart, stop); `--no-autostart` (start) |

### Gaps the protocol needs and the CLI does not have

These are findings to carry into the report and into #831 and #833. None of them is fixed here.

1. **No command reports `POOR_SIGNAL` or parser rejections** (section 5.1 works around it).
2. **`POOR_SIGNAL` does not gate events** (#828, #829).
3. **`field-test` has no integrity guard** (#830).
4. **`field-test --minutes` below about 8 silently falls back** to the full default protocol, including cues for switches that are off.
5. **The cue count is fixed at 8 per gesture phase**, with no CLI option to change it. There is also no protocol-file option, which the protocol already lists as open question 1.
6. **No CLI merges several field-test JSON files.** `FieldTestAggregate` exists only in Python.
7. **No CLI gives an exact Poisson bound on a hand count.** The exact limit is the private `yazses.biosignal.evaluate._poisson_upper`. The field-test's own printed bound is the Wilson-Hilferty approximation at z = 1.645: 89.1/h for zero events in 120 s, against an exact 89.9/h.
8. **The `monitor --source` help text lists only `synthetic | file: | brainflow:`.** A `thinkgear:` spec is accepted anyway.

## 15. References

- NeuroSky, [ThinkGear Communications Protocol](https://developer.neurosky.com/docs/doku.php?id=thinkgear_communications_protocol): framing, `0x02` POOR_SIGNAL, `0x80` raw at 512 Hz, baud requirements.
- NeuroSky support, [How to convert raw values to voltage](https://support.neurosky.com/kb/science/how-to-convert-raw-values-to-voltage): the nominal µV scale and its stated gain uncertainty.
- BlueZ, [bluetoothctl(1)](https://manpages.debian.org/trixie/bluez/bluetoothctl.1.en.html) (bluez 5.82, Debian trixie) and [rfcomm(1)](https://manpages.debian.org/experimental/bluez/rfcomm.1.en.html).
- Linux kernel, [devices list](https://docs.kernel.org/6.16/admin-guide/devices.html): RFCOMM TTY devices.
- Bluetooth SIG, [Serial Port Profile 1.2](https://www.bluetooth.com/specifications/specs/serial-port-profile-1-2/) and [Assigned Numbers](https://www.bluetooth.com/specifications/assigned-numbers/).
- In this repository: the [validation protocol](../specs/biosignal-validation-protocol.md), [ADR-v2-152](../adr/adr-v2-152-biosignal-artifact-switches.md), [ADR-v2-153](../adr/adr-v2-153-biosignal-false-positive-governor.md), [ADR-v2-155](../adr/adr-v2-155-thinkgear-transport-safety.md), the [qualification spec](../specs/thinkgear-hardware-qualification.md), the [evidence review](../research/2026-11-03-thinkgear-first-device-evidence.md), the [hands-free measurement proposal](../research/2026-11-06-hands-free-measurement-protocol.md) (P2, unintended actions per usable exposure hour), and the [hardware guide](../../docs/how-to/biosignal-hardware.md).

**Verification note:** written from a code reading at `4a83e484`, `--help` output, and runs against an
emulated byte stream. No physical headset, no Bluetooth pairing and no human session were part of
writing it.
