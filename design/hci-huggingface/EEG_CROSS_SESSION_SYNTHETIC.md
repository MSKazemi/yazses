# Synthetic cross-session EEG evaluation harness (spec)

> **All numbers here are synthetic, not human EEG.** Every signal comes from an authored
> generator in `scripts/hci_eeg_cross_session_synthetic.py`. Nothing on this page is evidence
> that YazSes can decode brain activity. ADR-030 rules out a production EEG interface, and
> nothing here changes that.

**Status:** research draft. The script and its tests were written on 2026-11-06 and first
run the same day. The "expected outputs" below were hypotheses written before that run;
the [first-run results](#first-run-results-2026-11-06) record which held. **H2 was
refuted.**

## Why this exists

The closed predecessor, #696 (closed 2026-11-03), produced a synthetic motor-imagery stress
replay. Its results page records that this replay did **not** test cross-session or
participant-disjoint evaluation:

- `design/hci-huggingface/EEG_MI_SYNTHETIC_STRESS_RESULTS.md:141` says seeds 0-9 against
  10-19 is "not a cross-session or participant-disjoint split";
- `:157` lists "cross-session independent data" as not run;
- `:174` gives the next step: freeze a participant- or session-disjoint split, never split
  overlapping windows of one recording across train and test, and fit preprocessing,
  calibration and model on training data only.

This harness turns `:174` into code that can be tested before any real dataset is
touched. Its job is to show that the **evaluation pipeline** cannot leak. Classification
accuracy is not the point. No open issue tracks this follow-up (`:180`). Reopening #696 or
opening a new issue is a maintainer decision.

## What the script does

| Part | Function | Contract |
|---|---|---|
| Generator | `generate(seed, n_subjects, n_sessions)` | Pure and seeded (`numpy.random.default_rng`). Each subject has an authored mu amplitude, mu frequency and imagery suppression ratio. The last subject is an authored **non-responder** with suppression 0.97. Each session gets its own gain (log-normal, σ 0.35), mu-amplitude drift (σ 0.20) and noise level. Each block gets an amplitude jitter (σ 0.25), which correlates the windows inside it. Blocks are 4 s and alternate rest and imagery, 12 per session. Windows are 1 s with a 0.25 s hop and never cross a block boundary. |
| Features | `bandpower_features` | Log mean Hann-windowed power in 8-13 Hz and 16-26 Hz on C3 and C4, giving 4 features. |
| Normalisation | `fit_standardizer` | z-score whose mean and scale come **only from the rows passed in**. `evaluate` passes only that fold's training rows. |
| Classifiers | `fit_lda`, `predict_1nn` | Two-class LDA with 0.10 trace shrinkage. Its posterior comes from the equal-covariance logit. 1-nearest-neighbour serves as the high-capacity classifier that window-overlap leakage misleads. numpy only, with no scikit-learn. |
| Splits | `split_by_subject`, `split_by_session` | Leave-one-subject-out, and leave-one-session-index-out pooled over subjects. |
| Negative control | `split_leaky_windows` | Random window-level 3-fold split. Marked `negative_control: true` in the report. |
| Leak audit | `overlapping_window_pairs` | Counts train/test pairs from the same (subject, session) recording that share any sample. |
| Per-subject failure | `evaluate` | Balanced accuracy per subject. Any subject below 0.60 goes in `failed_subjects`. |
| Activation replay | `replay_activations`, `activation_metrics` | Causal rule: posterior ≥ 0.70 for 2 consecutive windows, with a 2 s refractory period. A fire on a rest window counts as a false activation. The replay reports false activations per hour of synthetic rest exposure, the exposure in seconds and an exact one-sided 95% Poisson upper bound (`poisson_upper_bound`). |
| Report | `run`, `main` | JSON with `synthetic: true`, a notice, limitations, every authored parameter, rounded metrics and a `report_sha256` over the canonical JSON. `--out` writes UTF-8 with LF line endings. |

## Expected outputs (hypotheses, not results)

These are predictions from the generator's construction. None has been observed.

1. **H1. Disjoint splits do not overlap.** `overlapping_train_test_window_pairs` is 0 for
   `subject_disjoint` and `session_disjoint`, and greater than 0 for `leaky_window_split`.
   This holds by construction and is pinned by tests.
2. **H2. The leaky split inflates accuracy.** For 1-NN, leaky balanced accuracy minus
   session-disjoint balanced accuracy is at least 0.05 at seed 0. The expected cause is
   that a test window's nearest neighbour is a 75%-overlapping window from the same block.
   For LDA, which has 4 features and few parameters, the inflation is expected to be small.
   That would itself be worth reporting: leakage hurts high-capacity models most. This is
   pinned on seed 0 only. If it fails, check the generator (block jitter, overlap) before
   assuming the classifier is wrong.
3. **H3. The authored non-responder fails.** Under the subject-disjoint LDA, the
   non-responder's balanced accuracy is near 0.5, and it appears in `failed_subjects`.
4. **H4. Session gain drift lowers session-disjoint accuracy.** Session-disjoint LDA
   accuracy is expected to sit below the leaky split. Training normalisation does not
   remove another session's gain shift. The size of the drop is not predicted.
5. **H5. The false-activation rate is uncertain.** At the defaults every one of the
   18 recordings (6 subjects × 3 sessions) is held out once, so the synthetic rest exposure
   is 18 × 6 rest blocks × 4 s = 432 s, or 7.2 minutes. Even with zero false fires, the
   exact 95% upper bound is therefore about 25 per hour (3.0 × 3600 / 432). The point rate is not
   a safety estimate.
6. **H6. The report is deterministic.** `run(0) == run(0)` within one process.
   `report_sha256` is **not** pinned across platforms, because FFT and BLAS rounding can
   differ in the last bits before the 6-decimal rounding.

## How to validate

```sh
uv run python -m pytest tests/test_night_r04_eeg_cross_session.py -v
uv run ruff check scripts/hci_eeg_cross_session_synthetic.py tests/test_night_r04_eeg_cross_session.py
uv run python scripts/hci_eeg_cross_session_synthetic.py --seed 0 --out /tmp/eeg-xs-0.json
```

Record H1-H6 as confirmed or refuted on this page, with the observed numbers and the date.
Do not tune the generator to make H2 pass. A tuned generator would make H2 hold by design
and show nothing.

## First-run results (2026-11-06)

Synthetic numbers only. Linux x86_64, CPython 3.12.3, numpy 2.4.6, `--seed 0` at the
defaults (6 subjects × 3 sessions, 2808 windows), unless a row says otherwise.

| Hypothesis | Outcome | Observed |
|---|---|---|
| H1 | Confirmed | Overlapping train/test window pairs: 0 for `subject_disjoint`, 0 for `session_disjoint`, 9526 for `leaky_window_split`. |
| H2 | **Refuted** | 1-NN inflation (leaky − session-disjoint balanced accuracy) is 0.852564 − 0.828348 = **0.024217**, below the predicted 0.05. LDA inflation is 0.006054. Across seeds 0-5 the 1-NN inflation was positive every time (0.024 to 0.092) but reached 0.05 in only 3 of 6 seeds (1, 2, 3). The leak is real but smaller than predicted at these settings. The generator was not tuned; the test now pins only the direction (inflation > 0 at seed 0). |
| H3 | Confirmed | Subject-disjoint LDA balanced accuracy for the non-responder (subject 5) is 0.500, and it is the only entry in `failed_subjects`. The other subjects range 0.878 to 0.994. Subject 5 was the only failed subject in seeds 0-5. |
| H4 | Confirmed, effect tiny | Session-disjoint LDA 0.872863 vs leaky 0.878917. At seed 3 the order reversed (LDA inflation −0.001781), so this is not a robust drop. |
| H5 | Confirmed | Rest exposure 432 s. Session-disjoint LDA replay: 2 false activations, 16.7 per hour, 95% upper bound 52.5 per hour. Subject-disjoint: 1, 8.3 per hour, upper bound 39.5 per hour. Hits: 88 of 108 imagery blocks in both. |
| H6 | Confirmed within one process | `run(0) == run(0)` holds (test passes). `report_sha256` remains unpinned across platforms. |

## Non-goals

- No real EEG, devices, BrainFlow boards or ThinkGear runtime. #827 (ThinkGear G0) is open,
  and nothing here depends on it.
- No dataset download, network access or new dependency. numpy is already a base dependency.
- No model, threshold or calibration intended to transfer to people. No accuracy claim.
- No YazSes runtime integration, config key, CLI command or IPC method, under the ADR-030
  freeze.
- No calibrated confidence. The LDA posterior is only as calibrated as the equal-covariance
  assumption, and the generator violates that assumption on purpose across sessions.
- No artifacts, unknown mental states or head motion. Those stay with
  `scripts/hci_eeg_mi_synthetic.py` and `scripts/hci_eegeog_replay.py`.

## License and ethics review checklist for any later public dataset

Nothing has been downloaded. Before **anyone** fetches a public dataset (for example a
PhysioNet motor-imagery recording or a MOABB-indexed dataset), a reviewer completes this
list in writing:

- [ ] Dataset landing page cited (not a file URL), with version, DOI and date read.
      Candidates to check: PhysioNet EEG Motor Movement/Imagery,
      <https://physionet.org/content/eegmmidb/1.0.0/>, and the MOABB dataset catalogue,
      <https://moabb.neurotechx.com/docs/datasets.html>. Neither page was re-read on
      2026-11-06. The reviewer must verify the licence terms from the landing page and must
      not rely on this page.
- [ ] Licence permits research use, derived features and publication of aggregate
      results. Record attribution and share-alike terms, and any credentialed or
      data-use-agreement requirement.
- [ ] Every MOABB dataset is covered **individually**. MOABB is an index and loader, and
      each underlying dataset carries its own licence and consent terms.
- [ ] Participant consent covers secondary analysis of this kind. No re-identification
      attempts. No linking to other data.
- [ ] Session structure is documented: which recordings share a participant and which
      share a day. Without this, a session-disjoint split cannot be built.
- [ ] Raw data stays outside the repository. AGENTS.md rule 11 keeps private tiers private,
      and no participant data goes to third-party tools.
- [ ] The split is frozen and committed **before** any model is fitted. The H1 overlap
      audit is re-run on the real metadata.
- [ ] Human-subject work stays separately gated (#425/#427/#814, per
      `EEG_MI_SYNTHETIC_STRESS_RESULTS.md:178`).

## Provenance

- Predecessor: #696, state CLOSED, closedAt 2026-11-03T23:11:48Z (read-only
  `gh issue view`, 2026-11-06).
- Related prior scripts: `scripts/hci_eeg_mi_synthetic.py` (single-recording MI stress
  replay) and `scripts/hci_eegeog_replay.py`.
- Base commit: `main` at 8a72bbc6.
