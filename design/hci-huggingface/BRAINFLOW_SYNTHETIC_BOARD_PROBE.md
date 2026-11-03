# BrainFlow synthetic-board interface probe (G1 research-only)

**Date:** 2026-11-03  
**Issue:** [#696](https://github.com/MSKazemi/yazses/issues/696); companion research review [PR #821](https://github.com/MSKazemi/yazses/pull/821)  
**Scope:** independent BoardShim interface validation; **not** an EEG study, product feature, or approval to use human data.

## Purpose and precise distinction

The existing `scripts/hci_eegeog_replay.py` uses **Python-generated, seeded Gaussian noise and injected bursts**, not BrainFlow's `BoardShim` synthetic-board API. The new `scripts/hci_brainflow_synthetic_probe.py` tests only the latter: it starts BrainFlow's software-generated `SYNTHETIC_BOARD` (board ID `-1`) for at most five seconds and validates the returned channel matrix, board metadata, finite values, increasing timestamps, and cleanup. It reports **only derived metadata, counts and timestamp gaps**, never samples, names, hostnames, absolute timestamps, or biosignal recordings. No device is accessed, no network API is used by the script, no daemon or desktop action is called, and nothing is persisted.

BrainFlow's [data-format reference](https://brainflow.readthedocs.io/en/stable/DataFormatDesc.html) explicitly states that EEG, EMG, EOG channel getters can return *the same rows* for some boards. In the documented synthetic board, the three labels overlap substantially. **There are not three independent physiological channels just because there are three modality names.** A successful probe verifies BoardShim plumbing only, not artifact rejection, causal neural decoding, activation false-positive rate, or clinical performance.

## Reproduction and provenance

From the repository root, after consciously installing the **optional** BrainFlow dependency via the existing `emg-band` extra:

```sh
uv run --extra emg-band python scripts/hci_brainflow_synthetic_probe.py --seconds 2
uv run python -m pytest tests/test_hci_brainflow_synthetic_probe.py -q
```

The second command runs with a fake BoardShim and **does not require** BrainFlow or hardware. The first requires the installed BrainFlow package and its native shared libraries, but not a sensor. For a version-controlled reproducibility study, record `uv.lock`/Git commit, installed BrainFlow version, Python/OS/architecture, requested duration, emitted sample count, timestamp span and p95 gap. The probe emits all but the repository/lockfile revision; record those alongside the JSON output. **Do not claim identical bytes or identical sample counts between runs:** the BrainFlow synthetic stream runs on a clock and is not seeded by this probe.

**Upstream pin to evaluate** (not installed or executed here): BrainFlow `5.23.0`, listed on [PyPI](https://pypi.org/project/brainflow/5.23.0/) as released 2026-09-13; published wheel `brainflow-5.23.0-py3-none-any.whl` SHA-256 `76817574fcc05dbb6f02e775149f5e400a4b1ebbf757e72a407c0aee4e372be5`. Verify installed package version and hash when preparing an independent evaluation; this research addition does not change dependencies or lockfiles. BrainFlow examples, board support, and licensing: [Python examples](https://brainflow.readthedocs.io/en/stable/Examples.html), [supported boards](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html), [data format](https://brainflow.readthedocs.io/en/stable/DataFormatDesc.html), [MIT license](https://github.com/brainflow-dev/brainflow/blob/master/LICENSE).

## Test and acceptance matrix

| Check | Automated fake-board test | Needs actual BrainFlow synthetic board |
|---|---|---|
| Refuse board IDs other than `-1`, limit duration to 0.2–5 s | Yes | No |
| Session lifecycle: prepare → start → read → stop → release | Yes | **Yes** |
| Cleanup when read, start or stop fails | Yes | Optional fault injection, not performed |
| Board API metadata, row index validity, finite matrix | Yes | **Yes** |
| Strict timestamp ordering and p95 relative gap | Yes | **Yes** |
| Detect shared EEG/EOG and EEG/EMG index labels | Yes | **Yes** |
| No raw data, identity, or absolute timestamp in JSON | Yes | **Yes** |
| EEG physiological origin, real-world reliability, false activations/hour | **Cannot evaluate** | **Cannot evaluate** |

The executable's exit code is 0 only if the interface-level checks pass; 1 is a failed check, 2 is absent optional dependency or rejected invocation. A passing executable does **not** advance to a human pilot and does **not** change the project's accepted ADR-030 freeze.

## Actual execution evidence from this contribution

- **Mocked interface test:** 7 passed in an isolated Python environment on 2026-11-03, exercising no installed BrainFlow package. These tests validate control flow and report correctness only.
- **Syntax compilation:** succeeded in the same isolated environment.
- **Real BrainFlow `SYNTHETIC_BOARD` run:** **NOT PERFORMED** here because the Python environment has no `brainflow` installation and outbound package installation was unavailable. The `uv` project/full-suite and `ruff` CI gates were also not run in this environment. Treat G1 as **partially completed**, not experimentally validated.

## Follow-up gates

1. An independent contributor runs the actual BrainFlow `5.23.0` synthetic board locally on Linux, macOS or Windows, records a non-sensitive JSON result, version and repo SHA, and checks native library availability / errors.
2. Add a controlled playback-file benchmark (using *only* synthetic, verified-license fixtures) to test reproducible buffers, varied clocks, stale events and dropped samples. Do not merge the playback semantics into the live daemon.
3. Update the #696 evidence ledger only after the actual BoardShim run is reviewed. The existing generated event/classification experiment and new BoardShim probe test **different** things; neither is evidence of human neural intent.
4. For any later human study follow ADR-v2-150, #425/#427, the separate ethics/consent gate and the proposed ADR-v2-154 from PR #821. Do not recruit or collect biosignals under this probe.
