# Drivers — the shell that actually ran the measurement window

Forty-nine scripts recovered from the two rented Azure boxes (`x86-*` from one,
`x86b-*` from the other) before they were released. They fetch the corpora, provision
the machines, cross-check the scorer and queue the sweeps. The Python probes in
[`../`](../README.md) are the instruments; these are the hands.

**They are archived, not maintained.** Paths are `$HOME`-relative to a machine that no
longer exists, several are superseded by a later numbered version of themselves
(`run_ami.sh` → `run_ami2.sh` → `run_ami16.sh`), and none takes arguments. Read them to
find out what was actually run; do not expect to run them unchanged.

They are here because a result whose *procedure* is gone is not reproducible, and
because three of them are load-bearing for numbers that are published:

| Script | Why it matters |
|---|---|
| `x86-validate_scorer.sh` | Cross-checks this repo's DER against **NIST `md-eval-22.pl`** and **`pyannote.metrics`** on the same hypothesis RTTMs. Every DER figure in `docs/benchmarks.md` rests on the repo's own scorer agreeing with the two reference implementations, and this is the only record that the comparison was made. |
| `x86-fetch_ami16.sh` | Names the exact AMI test split (16 meetings, one per room ×4), the `Mix-Headset` channel, and the `only_words` RTTMs from `pyannote/AMI-diarization-setup` — which reference annotation was used is the single largest source of disagreement between published AMI DERs. |
| `x86-prep_vox.sh`, `x86-fetch_vox*.sh` | The VoxConverse **dev** split and its RTTMs from `joonson/voxconverse`. |
| `*-bootstrap.sh` | The apt list both boxes were built with, deliberately mirroring `.github/workflows/test.yml` so a difference between a VM result and a CI result is the architecture and not the machine. |

The corpora themselves are not committed — AMI and VoxConverse licences do not permit
redistribution. These scripts are how to obtain them.

## Redaction

`$HOME` and `user` were substituted for the real home directory and login name before
committing, the same rule `tests/test_benchmark_results_are_archived.py` enforces on the
results and the logs. Nothing else was changed: no script was tidied, reordered or
back-edited, because a driver rewritten after the fact is not a record of what ran.

Verified before committing: no credential, token or IP address appears in any of them.
The Azure TTS corpus was built by `../../make_corpus.py`, which reads its key from the
environment and never stored one here.
