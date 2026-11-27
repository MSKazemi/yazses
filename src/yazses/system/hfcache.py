"""Try the Hugging Face cache before the network, for loaders that offer no switch.

`stt/faster_whisper.py` already loads cache-first, and the reason it must is measured:
on this project's own laptop, a **fully cached** `base.en` loaded in **1.9 s** with
`HF_HUB_OFFLINE=1` and **had not finished after 180 s** without it — 3 s of user CPU, so
it was blocked on I/O, not working. A hub round-trip to revalidate a snapshot has no
timeout, and a network that neither answers nor refuses (a captive portal, a blackholed
firewall rule, hub rate-limiting) turns "load a model that is already on disk" into a
hang with no error and nothing to read.

faster-whisper could be fixed in place because `WhisperModel` takes `local_files_only=`.
The three other model loaders in this project do not offer one:

* `voiceprint/ecapa.py` → `EncoderClassifier.from_hparams(...)` (speechbrain)
* `stt/parakeet.py` → `onnx_asr.load_model(...)`
* `recimport/pyannote_backend.py` → `Pipeline.from_pretrained(...)`

What they share is the layer underneath: all three fetch through `huggingface_hub`, which
blocks every request in :func:`huggingface_hub.utils._http.hf_request_event_hook` when
offline mode is on. So the switch this module needs is one the *hub* honours, not one each
library has to expose. That is `HF_HUB_OFFLINE`.

The flag is set two ways on purpose, because one of them alone is a silent no-op:

* the **environment variable**, which a not-yet-imported `huggingface_hub` reads at import
  (all three packages are lazy optional extras, so this is the ordinary case); and
* **`huggingface_hub.constants.HF_HUB_OFFLINE`**, only if that module is already in
  `sys.modules` — the constant is initialised from the environment *at import time*, so a
  package imported earlier in the process would never see the variable we just set. The
  enforcement point reads it back through `constants.is_offline_mode()` on every request,
  which is what makes flipping it after import work at all.

⚠ This is a **process-global** flag held across the load, so a concurrent hub download in
another thread would be refused while it is set. Model construction happens once, on a
startup path, and the alternative on that path is an unbounded hang; documented rather than
locked, because a lock here would serialise loads that are otherwise independent.

**A user who asked for offline mode gets offline mode.** :func:`load_cache_first` does not
retry online when `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` is already set — falling back to
a download would quietly defeat the setting whose entire purpose is to forbid one. That is
also what makes `HF_HUB_OFFLINE=1` a real test of whether a model is cached, which
`docs/how-to/air-gapped.md` tells people to rely on.

A caller that names its model (``kind`` and ``name``) also has the decision to download
made by :func:`yazses.models.registry.ensure_model` (ADR-035): "cached" is answered by the
cache-only load itself, and the online load runs only if the policy allows it. The speaker
encoder and the pyannote pipeline do this today, at ``auto``, which is the behaviour above.

No new outbound call is introduced here (ADR-019); this strictly removes one.
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from typing import Any, TypeVar

log = logging.getLogger(__name__)

_ENV = "HF_HUB_OFFLINE"
# huggingface_hub honours this as an alias, so a machine set up for `transformers`
# offline is already asking for the same thing.
_ALIAS = "TRANSFORMERS_OFFLINE"
# Matches `huggingface_hub.constants.ENV_VARS_TRUE_VALUES` — a guess here would mean
# disagreeing with the library about whether the user opted in.
_TRUE = {"1", "ON", "YES", "TRUE"}

T = TypeVar("T")


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().upper() in _TRUE


def offline_requested(env: dict | None = None) -> bool:
    """Whether offline mode was already asked for, by the environment or in-process."""
    source = os.environ if env is None else env
    if _truthy(source.get(_ENV)) or _truthy(source.get(_ALIAS)):
        return True
    constants = sys.modules.get("huggingface_hub.constants")
    return bool(getattr(constants, "HF_HUB_OFFLINE", False))


@contextmanager
def cache_first() -> Iterator[None]:
    """Forbid hub requests for the duration, then restore the previous state exactly.

    "Exactly" includes the difference between *unset* and *set to something falsy*: the
    hub distinguishes them (an explicit `HF_HUB_OFFLINE=0` is a user statement), and
    leaving `0` behind where there was nothing would be a change this made silently.
    """
    prior_env = os.environ.get(_ENV)
    os.environ[_ENV] = "1"
    # Deliberately `sys.modules`, never an import: importing huggingface_hub to set a
    # flag would pull the dependency into paths that do not use it.
    # `Any`: this is a module object fetched by name, so the checker cannot know it
    # carries the attribute -- and the whole point is that it might not.
    constants: Any = sys.modules.get("huggingface_hub.constants")
    was_imported = constants is not None
    prior_flag = getattr(constants, "HF_HUB_OFFLINE", None) if constants else None
    if constants is not None:
        constants.HF_HUB_OFFLINE = True
    try:
        yield
    finally:
        # Restore the environment first: the constant's correct value is derived
        # from it below.
        if prior_env is None:
            os.environ.pop(_ENV, None)
        else:
            os.environ[_ENV] = prior_env
        # Re-read `sys.modules` rather than reusing the reference captured above.
        # The captured one is `None` in the case this whole module exists to serve
        # -- the docstring's "not-yet-imported huggingface_hub", i.e. the lazy
        # optional extras -- because those import the hub for the first time
        # *inside* this window. It then initialises HF_HUB_OFFLINE from the
        # variable we just set, and restoring through the stale `None` reference
        # was a no-op, so the constant stayed True for the rest of the process.
        #
        # That silently disabled the network for everything after it, starting with
        # `load_cache_first`'s own retry-online fallback -- the half that makes a
        # FIRST run work. The observable failure was that `features enable
        # stt-parakeet` could never download its model: the cache miss was correct,
        # the retry was already offline, and `build_engine` fell back to
        # faster-whisper. Whisper hid it, because faster_whisper imports the hub at
        # module scope, so for the default engine the module is always already
        # present and the original restore path ran.
        constants = sys.modules.get("huggingface_hub.constants")
        if constants is not None:
            if was_imported:
                constants.HF_HUB_OFFLINE = prior_flag
            else:
                # Imported during the window, so it read our flag rather than the
                # user's. Recompute from the environment as the hub itself would.
                constants.HF_HUB_OFFLINE = _truthy(prior_env)


def load_cache_first(
    load: Callable[[], T],
    *,
    what: str,
    kind: str = "",
    name: str = "",
    policy: str = "auto",
    manual_hint: str = "",
) -> T:
    """Run ``load`` against the local cache; download only if that misses.

    The fallback is the half that keeps this from trading one failure for another: a model
    that genuinely is not on disk must still be fetched, exactly as before. A first run is
    unchanged; every run after it stops asking the network for permission to use a file it
    already has.

    With *kind* and *name* (a :mod:`yazses.models.registry` kind and a model name) the
    download is decided by ``ensure_model`` under *policy*: ``auto`` behaves exactly as
    above; ``ask`` and ``never`` load from the cache only and raise ``RuntimeError`` with
    the registry's message (which names *manual_hint*) when that misses. *policy* and
    *manual_hint* are ignored without *kind*.
    """
    if kind:
        return _load_under_policy(
            load, what=what, kind=kind, name=name, policy=policy, manual_hint=manual_hint
        )
    if offline_requested():
        return load()
    try:
        with cache_first():
            return load()
    except Exception as exc:
        _log_miss(what, exc)
    # Outside the `except` block on purpose: a failure here is about the network, and
    # chaining it to the cache miss buries the cause under "During handling of the above".
    return load()


def _log_miss(what: str, exc: Exception) -> None:
    # Not `log.warning`: on a normal machine this is the ordinary first run, and a
    # download that is about to succeed is not a problem to warn about.
    log.info(
        "%s is not in the local Hugging Face cache (%s) — downloading it once.", what, exc
    )


def _load_under_policy(
    load: Callable[[], T], *, what: str, kind: str, name: str, policy: str, manual_hint: str
) -> T:
    """:func:`load_cache_first` for a named model, decided by ``ensure_model``."""
    from yazses.models.registry import ensure_model

    offline = offline_requested()
    loaded: list[T] = []
    misses: list[Exception] = []

    def from_cache(_name: str) -> bool:
        try:
            # Offline was already asked for: leave the user's setting alone.
            with nullcontext() if offline else cache_first():
                loaded.append(load())
        except Exception as exc:  # noqa: BLE001 -- a miss; what follows is decided below
            misses.append(exc)
            return False
        return True

    def online(_name: str) -> None:
        if offline:
            raise misses[0]  # one attempt only, and its own error
        _log_miss(what, misses[0])
        loaded.append(load())

    result = ensure_model(
        kind, name, policy, is_cached=from_cache, download=online, manual_hint=manual_hint
    )
    result.raise_for_failure()
    if not loaded:  # `ask` / `never`: nothing was fetched
        raise RuntimeError(result.message)
    return loaded[0]
