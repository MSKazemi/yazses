"""Shared application service for high-level language profile changes.

The pure resolver in :mod:`yazses.language.plan` decides *what* a profile means.
This module owns the side-effect ordering shared by CLI and Settings:

stable snapshot -> resolve/validate -> prerequisite preflight -> optional install/
download -> optimistic atomic config commit.

It deliberately does not restart the daemon. Restart policy belongs to the caller
because the CLI can guard Meeting Mode finalization while the Settings window must
coordinate with its own worker/restart UI.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Literal

from yazses.config import Config, SttConfig
from yazses.language.plan import LanguagePlan, ResolveMode
from yazses.language.profiles import LanguageProfileError

ApplyCategory = Literal["", "invalid", "prerequisite", "transaction"]


@dataclass(frozen=True)
class LanguageRequirements:
    """Local artifacts required by a resolved candidate."""

    check_modules: tuple[str, ...]
    missing_imports: tuple[str, ...]
    packages: tuple[str, ...]
    blocked_reason: str | None
    model_cached: bool
    model: str


@dataclass(frozen=True)
class PreparedLanguageChange:
    """A stable config snapshot plus its fully validated profile plan."""

    config: Config
    revision: str
    plan: LanguagePlan
    candidate_stt: SttConfig
    requirements: LanguageRequirements


@dataclass(frozen=True)
class LanguageApplyResult:
    """Outcome of applying a profile without restarting the daemon."""

    ok: bool
    category: ApplyCategory = ""
    prepared: PreparedLanguageChange | None = None
    changed: bool = False
    prerequisite_changed: bool = False
    error: str = ""

    @property
    def restart_required(self) -> bool:
        return self.changed or self.prerequisite_changed


def stable_config_snapshot(
    path: Path,
    *,
    load_config_fn=None,
    revision_fn=None,
    attempts: int = 3,
) -> tuple[Config, str]:
    """Read config + revision without accepting a torn concurrent snapshot."""

    if load_config_fn is None:
        from yazses.config import load_config

        load_config_fn = load_config
    if revision_fn is None:
        from yazses.system.configedit import config_revision

        revision_fn = config_revision

    for _attempt in range(attempts):
        before = revision_fn(path)
        cfg = load_config_fn(path)
        after = revision_fn(path)
        if before == after:
            return cfg, after
    raise RuntimeError("Config kept changing while YazSes tried to read it; try again.")


def candidate_stt(cfg: Config, plan: LanguagePlan) -> SttConfig:
    """Apply only the plan's STT mutations in memory."""

    updates = {
        mutation.key: mutation.after
        for mutation in plan.mutations
        if mutation.section == "stt"
    }
    return replace(cfg.stt, **updates)


def inspect_language_requirements(
    cfg: Config,
    stt: SttConfig,
    *,
    missing_modules_fn=None,
    blocked_probe=None,
    cache_probe=None,
) -> LanguageRequirements:
    """Inspect local prerequisites without installing/downloading anything."""

    if missing_modules_fn is None:
        from yazses.system.deps import missing_modules

        missing_modules_fn = missing_modules
    if blocked_probe is None:
        from yazses.system.deps import install_blocked_reason

        blocked_probe = install_blocked_reason
    if cache_probe is None:
        from yazses.stt.download import is_cached

        cache_probe = is_cached

    check_modules: tuple[str, ...] = ()
    missing_imports: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    blocked_reason: str | None = None

    if (stt.chinese_script or "").strip():
        from yazses.system.features import find_feature

        feature = find_feature(cfg, "chinese-script")
        if feature is None:
            blocked_reason = "the chinese-script capability is missing from this build"
        else:
            check_modules = tuple(feature.check_modules)
            missing_imports = tuple(missing_modules_fn(check_modules))
            if missing_imports:
                packages = tuple(feature.pip_packages)
                blocked_reason = blocked_probe(packages)

    engine = (stt.engine or "faster-whisper").strip().lower()
    model = (stt.model or "base.en").strip() or "base.en"
    model_cached = True
    if engine == "faster-whisper":
        model_cached = bool(cache_probe(model))

    return LanguageRequirements(
        check_modules=check_modules,
        missing_imports=missing_imports,
        packages=packages,
        blocked_reason=blocked_reason,
        model_cached=model_cached,
        model=model,
    )


def prepare_language_change(
    path: Path,
    requested: str,
    *,
    model: str | None = None,
    engine: str | None = None,
    mode: ResolveMode = "preserve",
    load_config_fn=None,
    revision_fn=None,
    missing_modules_fn=None,
    blocked_probe=None,
    cache_probe=None,
) -> PreparedLanguageChange:
    """Resolve and validate one profile against a stable config snapshot."""

    from yazses.language.plan import resolve_profile
    from yazses.language.status import derive_status

    cfg, revision = stable_config_snapshot(
        path,
        load_config_fn=load_config_fn,
        revision_fn=revision_fn,
    )
    plan = resolve_profile(
        requested,
        cfg,
        model=model,
        engine=engine,
        mode=mode,
    )
    stt = candidate_stt(cfg, plan)
    status = derive_status(stt)
    if not status.coherent or status.profile_match != plan.canonical_profile:
        detail = "; ".join(status.problems) or (
            f"candidate resolved to {status.profile_match!r}"
        )
        raise LanguageProfileError(
            f"Refusing an incoherent language candidate: {detail}"
        )

    requirements = inspect_language_requirements(
        cfg,
        stt,
        missing_modules_fn=missing_modules_fn,
        blocked_probe=blocked_probe,
        cache_probe=cache_probe,
    )
    return PreparedLanguageChange(
        config=cfg,
        revision=revision,
        plan=plan,
        candidate_stt=stt,
        requirements=requirements,
    )


def apply_language_change(
    path: Path,
    requested: str,
    *,
    model: str | None = None,
    engine: str | None = None,
    mode: ResolveMode = "preserve",
    allow_install: bool = True,
    allow_download: bool = True,
    echo: Callable[[str], None] = print,
    before_side_effect: Callable[[PreparedLanguageChange], None] | None = None,
    load_config_fn=None,
    revision_fn=None,
    missing_modules_fn=None,
    blocked_probe=None,
    cache_probe=None,
    installer=None,
    downloader=None,
    commit_fn=None,
) -> LanguageApplyResult:
    """Apply a language profile with prerequisites before one atomic config commit.

    A concurrent config edit never receives a stale plan: the commit is guarded by
    the snapshot revision and one conflict triggers a full re-read/re-resolve. Package
    and model downloads may remain after a later config conflict; the original config
    still remains untouched.
    """

    if revision_fn is None:
        from yazses.system.configedit import config_revision

        revision_fn = config_revision
    if missing_modules_fn is None:
        from yazses.system.deps import missing_modules

        missing_modules_fn = missing_modules
    if blocked_probe is None:
        from yazses.system.deps import install_blocked_reason

        blocked_probe = install_blocked_reason
    if cache_probe is None:
        from yazses.stt.download import is_cached

        cache_probe = is_cached
    if installer is None:
        from yazses.system.deps import install_packages

        installer = install_packages
    if downloader is None:
        from yazses.stt.download import download_stt_model

        downloader = download_stt_model
    if commit_fn is None:
        from yazses.system.configedit import set_config_keys_atomic

        commit_fn = set_config_keys_atomic

    prerequisite_changed = False
    last_prepared: PreparedLanguageChange | None = None

    for attempt in range(2):
        try:
            prepared = prepare_language_change(
                path,
                requested,
                model=model,
                engine=engine,
                mode=mode,
                load_config_fn=load_config_fn,
                revision_fn=revision_fn,
                missing_modules_fn=missing_modules_fn,
                blocked_probe=blocked_probe,
                cache_probe=cache_probe,
            )
        except LanguageProfileError as exc:
            return LanguageApplyResult(
                ok=False,
                category="invalid",
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to caller, never hidden
            return LanguageApplyResult(
                ok=False,
                category="transaction",
                error=f"Could not read/plan the language change: {exc}",
            )

        last_prepared = prepared
        req = prepared.requirements

        if req.blocked_reason:
            return LanguageApplyResult(
                ok=False,
                category="prerequisite",
                prepared=prepared,
                prerequisite_changed=prerequisite_changed,
                error=req.blocked_reason,
            )
        if req.missing_imports and not allow_install:
            return LanguageApplyResult(
                ok=False,
                category="prerequisite",
                prepared=prepared,
                prerequisite_changed=prerequisite_changed,
                error=(
                    "Required Chinese script dependency is missing and installation "
                    "was disabled."
                ),
            )
        if not req.model_cached and not allow_download:
            return LanguageApplyResult(
                ok=False,
                category="prerequisite",
                prepared=prepared,
                prerequisite_changed=prerequisite_changed,
                error=(
                    f"Speech model {req.model!r} is not cached and downloads were disabled."
                ),
            )

        needs_work = bool(
            prepared.plan.mutations
            or req.missing_imports
            or not req.model_cached
            or prerequisite_changed
        )
        if not needs_work:
            if revision_fn(path) != prepared.revision:
                if attempt == 0:
                    continue
                return LanguageApplyResult(
                    ok=False,
                    category="transaction",
                    prepared=prepared,
                    error="Config changed repeatedly; no stale language plan was accepted.",
                )
            return LanguageApplyResult(ok=True, prepared=prepared)

        if before_side_effect is not None:
            before_side_effect(prepared)

        if req.missing_imports:
            echo("Installing Chinese script dependency: " + " ".join(req.packages))
            try:
                installed = bool(installer(req.packages, echo=echo))
            except Exception as exc:  # noqa: BLE001 - installer errors are user-facing
                installed = False
                install_error = str(exc)
            else:
                install_error = ""
            if not installed:
                detail = f" ({install_error})" if install_error else ""
                return LanguageApplyResult(
                    ok=False,
                    category="prerequisite",
                    prepared=prepared,
                    prerequisite_changed=prerequisite_changed,
                    error=f"Dependency installation failed{detail}.",
                )
            still_missing = tuple(missing_modules_fn(req.check_modules))
            if still_missing:
                return LanguageApplyResult(
                    ok=False,
                    category="prerequisite",
                    prepared=prepared,
                    prerequisite_changed=prerequisite_changed,
                    error=(
                        "Dependency installer returned but these modules are still "
                        "unavailable: " + ", ".join(still_missing)
                    ),
                )
            prerequisite_changed = True

        if not req.model_cached:
            echo(f"Downloading speech model {req.model}…")
            try:
                downloader(req.model, echo=echo)
            except Exception as exc:  # noqa: BLE001 - converted to stable user error
                try:
                    from yazses.stt.errors import model_unavailable_message

                    detail = model_unavailable_message(req.model, exc)
                except Exception:
                    detail = f"{type(exc).__name__}: {exc}"
                return LanguageApplyResult(
                    ok=False,
                    category="prerequisite",
                    prepared=prepared,
                    prerequisite_changed=prerequisite_changed,
                    error=detail,
                )
            if not cache_probe(req.model):
                return LanguageApplyResult(
                    ok=False,
                    category="prerequisite",
                    prepared=prepared,
                    prerequisite_changed=prerequisite_changed,
                    error=(
                        f"Speech model {req.model!r} was downloaded but is still not "
                        "visible in the configured cache."
                    ),
                )
            prerequisite_changed = True

        if prepared.plan.mutations:
            from yazses.system.configedit import (
                ConfigChange,
                ConfigEditBusyError,
                ConfigEditConflictError,
            )

            changes = tuple(
                ConfigChange(m.section, m.key, m.after)
                for m in prepared.plan.mutations
            )
            try:
                commit_fn(
                    path,
                    changes,
                    expected_revision=prepared.revision,
                )
            except ConfigEditConflictError:
                if attempt == 0:
                    echo(
                        "Config changed while prerequisites were prepared; "
                        "re-reading and re-resolving before any write."
                    )
                    continue
                return LanguageApplyResult(
                    ok=False,
                    category="transaction",
                    prepared=prepared,
                    prerequisite_changed=prerequisite_changed,
                    error=(
                        "Config changed repeatedly; no stale language plan was committed."
                    ),
                )
            except ConfigEditBusyError as exc:
                return LanguageApplyResult(
                    ok=False,
                    category="transaction",
                    prepared=prepared,
                    prerequisite_changed=prerequisite_changed,
                    error=str(exc),
                )
            except Exception as exc:  # noqa: BLE001 - atomic writer error is surfaced
                return LanguageApplyResult(
                    ok=False,
                    category="transaction",
                    prepared=prepared,
                    prerequisite_changed=prerequisite_changed,
                    error=f"Could not commit language config atomically: {exc}",
                )
        elif revision_fn(path) != prepared.revision:
            if attempt == 0:
                echo("Config changed while prerequisites were prepared; re-resolving.")
                continue
            return LanguageApplyResult(
                ok=False,
                category="transaction",
                prepared=prepared,
                prerequisite_changed=prerequisite_changed,
                error="Config changed repeatedly; no stale language plan was accepted.",
            )

        return LanguageApplyResult(
            ok=True,
            prepared=prepared,
            changed=bool(prepared.plan.mutations),
            prerequisite_changed=prerequisite_changed,
        )

    return LanguageApplyResult(
        ok=False,
        category="transaction",
        prepared=last_prepared,
        prerequisite_changed=prerequisite_changed,
        error="Could not apply the language change safely.",
    )
