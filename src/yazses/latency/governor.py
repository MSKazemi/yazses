"""Load-aware decode-policy selection (pure) — ADR-v2-073.

Pick a decode policy (model, beam width, speculative on/off) from a CPU-load sample. Pure and
deterministic; the psutil read, the draft model, and the speculative-decode loop live elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecodePolicy:
    """The chosen decode policy: which ``model``, ``beam_size``, and whether to ``speculative``-decode."""
    model: str
    beam_size: int
    speculative: bool


@dataclass
class GovernorConfig:
    """Thresholds for :func:`pick_policy` (CPU percentages)."""
    base_model: str
    light_model: str = "tiny.en"
    draft_model: str = ""      # a distil draft; enables speculative decoding when idle
    high_load: float = 85.0    # at/above → light policy
    low_load: float = 40.0     # at/below (with a draft) → speculative
    #: The user's `[stt] beam_size`, verbatim -- `0` meaning "pass nothing and let
    #: the engine use its own default", which is what the shipped config says. The
    #: base policies must return *this*, not a width of their own, for two reasons
    #: that are really one. It is the user's setting, and a governor that silently
    #: replaces a documented key is worse than one that does nothing. And
    #: `EnginePool` is keyed on `(model, beam_size)` and told which key the daemon's
    #: already-loaded engine answers to; a base policy naming a different width
    #: misses that key and loads a **second copy of the model already in memory** --
    #: the exact thing pool.py's docstring says the design prevents.
    base_beam: int = 0


#: The light policy's beam width, and the one constant here decided by measurement.
#: It was 1 -- greedy -- on the reasonable-sounding argument that a policy for a
#: loaded machine should buy back every cycle it can. Measured on `tiny.en`, the
#: model this policy switches to, over 200 LibriSpeech utterances per split:
#:
#:     split        beam 1        beam 2        beam 5
#:     clean    5.53 / .0236  5.12 / .0241  4.95 / .0271     (WER % / RTF)
#:     other   12.42 / .0283 12.04 / .0295 11.82 / .0341
#:
#: Paired bootstrap over the same utterances, which is what can separate gaps this
#: narrow: beam 2 is **indistinguishable from beam 5** on both splits (p = 0.27
#: clean, p = 0.62 hard), while beam 1 loses significantly to beam 5 on clean audio
#: (+0.58 points, 95 % CI [+0.09, +1.14], p = 0.023). Beam 1 against beam 2 alone
#: does not reach significance on either split (p = 0.099, p = 0.41), so this is not
#: "1 is proven worse than 2" -- it is that 2 reaches the accuracy ceiling these
#: three widths show and 1 demonstrably does not.
#:
#: The price of that is 2.1 % more decode on clean audio and 4.2 % on hard, against
#: the 12-16 % beam 5 would cost over beam 2. And the beam was never where this
#: policy's saving came from: `base.en` at beam 5 decodes the hard split at RTF
#: 0.0426, so switching to `tiny.en` at beam 2 still costs 31 % less decode time.
#: Widening 1 -> 2 hands back a twelfth of that saving on hard audio and a
#: twenty-seventh on clean, to remove the one accuracy loss the grid actually
#: measured. That is the trade this policy exists to make.
#:
#: See paper/results/beam-governor-test-{clean,other}.json and their
#: `-significance` and `-significance-vs-beam2` companions.
LIGHT_BEAM = 2


def pick_policy(cpu_percent: float, config: GovernorConfig) -> DecodePolicy:
    """Select a :class:`DecodePolicy` for the current CPU load. Pure."""
    if cpu_percent >= config.high_load:
        return DecodePolicy(config.light_model, beam_size=LIGHT_BEAM, speculative=False)
    if cpu_percent <= config.low_load and config.draft_model:
        return DecodePolicy(config.base_model, beam_size=config.base_beam, speculative=True)
    return DecodePolicy(config.base_model, beam_size=config.base_beam, speculative=False)
