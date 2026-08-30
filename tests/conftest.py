import importlib
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from yazses.system.proc import process_alive


@pytest.fixture
def sine_audio_3s():
    """3-second 440 Hz sine wave at 16 kHz."""
    sr = 16000
    t = np.linspace(0, 3.0, sr * 3, dtype=np.float32)
    return np.sin(2 * np.pi * 440 * t)


@pytest.fixture
def silent_audio_1s():
    return np.zeros(16000, dtype=np.float32)


@pytest.fixture(autouse=True)
def _no_test_may_pop_a_toast_on_the_users_desktop(monkeypatch):
    """A test must not reach the real `notify-send`.

    Four daemon-level tests -- the ones that drive a *deliberately failing* injection
    or capture -- reached `core/daemon.py::_report_failure`, which is doing exactly
    its job in popping a toast. None of them was written wrong: three predate
    `_report_failure` entirely, and adding it dropped a `notify()` into `except`
    blocks they had been exercising all along. The side effect arrived without a
    single test changing.

    What landed on the desktop was not a toast but a permanent process: the fault is
    unclassified, so the toast carries the [Prepare a bug report] button, so it runs
    with `--wait`, so `notify-send` blocks until someone clicks a pop-up that
    `--urgency critical` guarantees will never expire. Four leaked per suite run and
    stayed for the rest of the session.

    `notify.py` no longer orphans them (see `test_notify_does_not_orphan.py`), but a
    test suite that pops real pop-ups at all is still wrong -- it depends on, and
    interrupts, whoever is running it. Fixing the four call sites would be
    whack-a-mole in the same way the log-handler leak below was, so this closes it at
    the source instead. Anything genuinely testing the notifier passes `available=`
    explicitly and is unaffected.
    """
    monkeypatch.setattr(
        "yazses.system.notify.notifier_available", lambda *a, **k: False, raising=True
    )


@pytest.fixture(autouse=True)
def _no_test_may_pop_a_windows_message_box(monkeypatch):
    """A test must not reach the real `user32.MessageBoxW`.

    Same family as the toast fixture above, and worse in one respect: a toast that
    never expires is litter, while `MessageBoxW` is *synchronous*. It returns when
    somebody clicks it, and in an unattended run nobody ever does.

    `test_settings_failure_is_visible.py::test_alert_is_a_no_op_off_windows` read
    `sys.platform` off the host, so on Windows it took the branch its own name says
    it does not test and called the real box. Four Windows CI jobs printed that test
    name and then nothing for 2 h 30 m while their Linux and macOS siblings finished
    in ten. A hang is not a failure: CI produced no result at all, not a red one,
    which is why it went unnoticed across every Windows run the suite has ever had.

    The tripwire records instead of raising, and the failure is reported at teardown,
    because `wincon.alert` swallows every exception by design -- raising here would be
    caught, turned into `return False`, and the test would pass while the box was on
    screen. Off Windows there is no `ctypes.windll` and nothing to patch; the guard is
    dormant rather than absent, which is the correct shape for a Windows-only hazard.
    """
    if sys.platform != "win32":
        yield
        return

    import ctypes

    calls: list[tuple] = []

    def _record(*args):
        calls.append(args)
        return 1  # IDOK -- whatever the caller would have got from a click

    try:
        monkeypatch.setattr(ctypes.windll.user32, "MessageBoxW", _record)
    except Exception:  # noqa: BLE001 -- an unpatchable user32 must not fail the suite
        yield
        return

    yield

    assert not calls, (
        "this test reached the real user32.MessageBoxW, which blocks until a human "
        f"clicks it: {calls}. On an unattended Windows runner that is a permanent "
        "hang, and a hang produces no test result at all. Patch the call, or force "
        "`sys.platform` if the test is about the off-Windows branch."
    )


@pytest.fixture(autouse=True)
def _no_test_may_log_into_the_users_real_log():
    """A test must not leave a file handler on the root logger.

    `Daemon.run()` attaches a `RotatingFileHandler` pointing at the user's actual
    `~/.local/state/yazses/log/daemon.log` and never removes it. Any test that
    calls the real `run()` therefore redirects **every later test in the session**
    into that file: one full run wrote 44 KB of fake recorders, deliberately
    invalid backends and injected `OSError`s into the log `yazses logs` prints and
    `yazses report` bundles into bug reports.

    Nothing failed, because nothing was looking — the pollution is invisible from
    inside the suite and only shows up to whoever later reads the log to diagnose
    something real.

    Fixing the offending tests one at a time is whack-a-mole: two lived in the same
    file, and the second was only found after the first was fixed. So this fails at
    the source instead. The handler is removed as well as reported, so one careless
    test cannot take the rest of the session down with it.
    """
    root = logging.getLogger()
    before = set(map(id, root.handlers))
    yield
    leaked = [
        h for h in root.handlers
        if id(h) not in before and isinstance(h, logging.FileHandler)
    ]
    for handler in leaked:
        root.removeHandler(handler)
        handler.close()
    assert not leaked, (
        "this test left a file handler on the root logger, so everything logged "
        f"after it goes into {[getattr(h, 'baseFilename', '?') for h in leaked]} — "
        "mock `_configure_logging`, or point the platform's log_dir at tmp_path"
    )


def _resolve_watched_host_files() -> dict[str, Path]:
    """The real files to watch — resolved **once, at import**, and never again.

    Two traps, both of which this guard fell into before it worked:

    - It must not call `get_paths()`. That is `lru_cache`d, so an observer calling it
      would warm the cache with the real path before any fixture could redirect it,
      and the guard would *cause* the very leak it looks for.
    - It must not re-resolve per test. `PlatformDirs` reads `XDG_CONFIG_HOME` at call
      time, so a fixture that redirects it makes the before- and after-snapshots point
      at **different files** — which the naive version dutifully reported as "you
      modified the real config", on tests that had modified nothing.

    Resolving at import, before any test or fixture runs, is the only reading that is
    both real and stable.
    """
    from platformdirs import PlatformDirs

    dirs = PlatformDirs(appname="yazses", appauthor=False, ensure_exists=False)
    return {
        "config file": Path(dirs.user_config_dir) / "config.toml",
        "pid file": Path(dirs.user_data_dir) / "daemon.pid",
        # The personal dictionary joined the list after a test wrote it. It is the
        # third file in this program a person hand-edits and expects to stay theirs,
        # and unlike the corpus below nothing writes it in the background -- only
        # `yazses vocab`, by hand -- so watching it cannot cry wolf. It also has a
        # consequence the other two do not: every word in it is fed to Whisper as
        # `initial_prompt` on every burst, so a stray entry biases transcription
        # rather than merely sitting there.
        "vocabulary file": Path(dirs.user_config_dir) / "vocabulary.txt",
    }


_WATCHED_HOST_FILES = _resolve_watched_host_files()


def _read_pid_file() -> int | None:
    """The pid inside the real pid file, or None. Never raises."""
    try:
        return int(_WATCHED_HOST_FILES["pid file"].read_text(encoding="utf-8").strip())
    except (OSError, ValueError, KeyError):
        return None


#: Which daemon owned the pid file when the session began, resolved once at import for
#: the same reason the paths are. Used to tell "a test deleted this" from "the daemon
#: that owned it exited while the suite ran".
_DAEMON_PID_AT_IMPORT = _read_pid_file()


def _alive(pid: int | None) -> bool:
    """Is *pid* a live process?

    This used to spell it ``os.kill(pid, 0)``, which on Windows is ``TerminateProcess``:
    the guard's own "prove the probe is not trivially true" test asks whether *this*
    process is alive, and so killed the test runner — silently, with exit code 0, a
    little under halfway through the suite. See :mod:`yazses.system.proc`.
    """
    return process_alive(pid)


def _pid_file_change_is_the_real_daemon(before: tuple, after: tuple) -> bool:
    """Did the machine's own daemon move the pid file, rather than a test?

    The incident this guard was written for is precise: ``Daemon._shutdown()`` called
    the real ``lifecycle.clear_pid()`` and deleted the pid file **out from under a
    running daemon**. The liveness of the owning process is exactly what separates
    that from the ordinary thing that happened on 2026-08-21 — the owner stopped his
    daemon nine seconds after dictating, mid-suite, and the test that happened to be
    running was reported as having "modified the real pid file".

    That false positive is not cosmetic. This fixture asserts in *teardown*, so pytest
    renders it as an ERROR rather than a FAILED, on an arbitrary innocent test that
    passes in isolation — and the docstring below already refuses to watch the data
    directory for exactly this reason: "a guard that fails because the owner dictated
    something would be turned off within a day". A guard protecting against a real past
    incident cannot afford to cry wolf.

    Benign in exactly two shapes, and nothing else:

    * the file is **gone** and the daemon that owned it at session start is dead — a
      clean exit takes its pid file with it;
    * the file is **present** and names a live process that is not this one — the owner
      started or restarted a daemon while the suite ran.

    A test writing the file writes ``os.getpid()``, which is this process, so it still
    fails. Residual hole, named rather than hidden: a test that deletes an already
    stale pid file (no daemon running at all) reads as benign. It touches the host and
    ought not to, but it cannot harm a daemon, which is what this guard is for.
    """
    existed_before, exists_after = before[0], after[0]
    if existed_before and not exists_after:
        return _DAEMON_PID_AT_IMPORT is not None and not _alive(_DAEMON_PID_AT_IMPORT)
    if exists_after:
        pid = _read_pid_file()
        return pid is not None and pid != os.getpid() and _alive(pid)
    return False


def _host_state() -> dict[str, tuple]:
    """`(exists, mtime_ns, size)` for the two real files the suite was caught writing."""
    watched = _WATCHED_HOST_FILES
    state = {}
    for label, path in watched.items():
        try:
            st = path.stat()
            state[label] = (True, st.st_mtime_ns, st.st_size)
        except OSError:
            state[label] = (False, 0, 0)
    return state


@pytest.fixture
def sandbox_paths(tmp_path, monkeypatch):
    """Point every YazSes directory at *tmp_path*, on every OS, without touching env.

    The previous version of this sandbox set `XDG_CONFIG_HOME`, then `APPDATA`,
    `LOCALAPPDATA`, `HOME` and `USERPROFILE` as well when the first proved to be a
    Linux answer to a cross-platform question. **That still does not work on Windows,**
    and the second attempt was never run on a Windows machine before it shipped:
    executed on Windows Server 2022 it stops the leak and then fails the sandbox
    assertion for every test, because platformdirs resolves the Windows folders through
    the OS rather than through the environment. Setting an environment variable is not a
    thing you can do to it.

    So this patches the seam instead of the environment. `build_paths()` is the single
    function each platform backend uses to produce its `Paths`, and `get_platform()`
    calls it, so replacing it puts every consumer inside the sandbox -- including the
    modules that did `from yazses.platform import get_platform` at import time and hold
    their own binding, which is what defeats patching the factory.

    Both `lru_cache`s are cleared on the way in and on the way out: whichever test
    resolved them first otherwise pins one answer for the whole session, which is how
    the original escape was order-dependent and therefore invisible.
    """
    import yazses.platform.factory as factory
    from yazses.platform.base import Paths

    root = tmp_path / "yazses-sandbox"
    sandboxed = Paths(
        config_dir=root / "config",
        state_dir=root / "state",
        cache_dir=root / "cache",
        log_dir=root / "log",
        data_dir=root / "data",
    )
    # Every backend, not just this OS's: cheap, and a test that swaps `sys.platform`
    # would otherwise fall through to the real resolver for the OS it swapped to.
    #
    # Both the defining module *and* the package that imported the name: each
    # `platform/<os>/__init__.py` does `from ...paths import build_paths` at import
    # time and calls its own binding, so patching only `paths` leaves the caller
    # pointing at the original function. That is the same `from X import Y` trap that
    # makes patching `factory.get_platform` useless, one layer down.
    for mod in ("linux", "macos", "windows", "bsd"):
        for name in (f"yazses.platform.{mod}.paths", f"yazses.platform.{mod}"):
            try:
                module = importlib.import_module(name)
            except Exception:  # noqa: BLE001 - a backend that will not import cannot leak
                continue
            if hasattr(module, "build_paths"):
                monkeypatch.setattr(module, "build_paths", lambda _s=sandboxed: _s)

    factory.reset_platform_cache()

    # Prove it, rather than trust it. This assertion is the reason the Windows failure
    # was found at all, so it stays -- a sandbox nobody checks is the original defect.
    resolved = factory.get_paths().config_dir
    assert root in resolved.parents or resolved == root, (
        f"the sandbox did not take: config_dir resolved to {resolved}, outside {root}. "
        f"A test that writes config would edit the real machine."
    )

    yield sandboxed

    factory.reset_platform_cache()  # the next test must not inherit this tmp_path


@pytest.fixture(autouse=True)
def _no_test_may_read_the_users_real_config(tmp_path_factory, monkeypatch):
    """A test must not read the machine it runs on either.

    The write guard below is only half the relationship. `load_config(None)` means
    *the defaults* everywhere in this suite -- several call sites say so in a comment
    (`# defaults: macros.enabled is False`) -- and it actually meant *whatever is in
    the developer's own `~/.config/yazses/config.toml`*, which the daemon's own
    first-run seeding writes.

    It cost a release gate. `test_doctor_names_every_prompt_source` asserts that with
    no configuration the STT-prompt row reads "app name only"; it passed for months,
    then failed twice in one afternoon on an unchanged tree, because starting the
    daemon on this laptop had seeded `[context] enabled = true` between two runs. The
    failure is worse than the flake: the suite's meaning silently depends on the
    machine, so a test can pass here and fail in CI, or -- much worse -- pass in CI
    while asserting nothing about the case it names.

    Pointing at a path inside a session-scoped tmp dir rather than at `Path.home()`:
    a nonexistent file is exactly the "no config" case, `load_config` is total and
    returns dataclass defaults for it, and unlike `HOME`/`XDG_CONFIG_HOME` it works
    the same on Windows and macOS, where `Path.home()` does not read those at all.
    """
    empty = tmp_path_factory.mktemp("no-user-config") / "config.toml"
    monkeypatch.setattr("yazses.config.default_config_path", lambda: empty)
    yield


@pytest.fixture(autouse=True)
def _no_test_may_write_the_users_real_config():
    """A test must not reach out of the sandbox and edit the machine it runs on.

    Two did, and both were invisible from inside the suite:

    - `features enable timeline --no-install` through `CliRunner` wrote
      `[timeline] enabled = true` into the developer's own `config.toml`. The test
      *has* a `scratch` fixture setting `XDG_CONFIG_HOME`, and it does not work:
      `get_platform()`/`get_paths()` are `lru_cache(maxsize=1)`, so whichever test
      resolved them first fixes the real path for the whole session. Run that file
      alone and it is clean; run it after anything else and it edits your config.
      Order-dependence is why nobody saw it.
    - `Daemon._shutdown()` called the real `lifecycle.clear_pid()` and **deleted**
      `~/.local/share/yazses/daemon.pid` out from under a running daemon.

    Same family as the log-handler leak above, and found the same way — by reading
    the developer's own machine afterwards rather than by any assertion failing.

    Only these two paths are watched. The data directory as a whole is deliberately
    **not**: a daemon running while the suite runs writes the corpus and the
    update-check file, and a guard that fails because the owner dictated something
    would be turned off within a day.
    """
    before = _host_state()
    yield
    after = _host_state()
    changed = [k for k in before if before[k] != after[k]]
    if "pid file" in changed and _pid_file_change_is_the_real_daemon(
        before["pid file"], after["pid file"]
    ):
        changed.remove("pid file")
    assert not changed, (
        f"this test modified the real {' and '.join(changed)} on this machine. "
        "Take the `sandbox_paths` fixture above, or mock the lifecycle backend. Do "
        "not reach for environment variables: setting XDG_CONFIG_HOME fixes nothing "
        "once the `get_platform`/`get_paths` lru_caches are warm, and adding "
        "APPDATA/LOCALAPPDATA/HOME on top does not help either — platformdirs "
        "resolves the Windows folders through the OS and never reads them, which is "
        "why the vocabulary CLI tests passed on Linux while writing the runner's own "
        "dictionary on both Windows legs. `sandbox_paths` patches `build_paths()`, "
        "the seam every backend goes through, and asserts the redirection took."
    )


def sounddevice_or_skip(*, allow_module_level: bool = False):
    """The real sounddevice module, or a skip that says why.

    `pytest.importorskip("sounddevice")` is not enough. sounddevice runs
    `Pa_Initialize()` during the import itself, and on a host with no usable audio
    system that raises

        sounddevice.PortAudioError: Error initializing PortAudio:
        Internal PortAudio error [PaErrorCode -9986]

    which is not an ImportError, so `importorskip` lets it through as a collection
    error and pytest then abandons the whole run. Measured on a Windows Server 2022
    VM with no audio device: that is exactly what happened, and the suite reported
    "2 errors during collection" instead of its 13675 results.

    The same shape as `_ctranslate2_or_skip` in
    tests/test_settings_decode_controls.py: a compiled or device-backed dependency
    can fail at *load* rather than at resolution, and a test file that merely needs
    it should skip rather than take the run down with it.
    """
    try:
        import sounddevice
    except Exception as exc:  # noqa: BLE001 -- PortAudioError, OSError, ImportError
        pytest.skip(
            f"sounddevice is unusable on this host ({type(exc).__name__}: {exc})",
            allow_module_level=allow_module_level,
        )
    return sounddevice


# --- process-global state a test must hand back -------------------------------
#
# Both guards below exist because the suite's result depended on the order pytest
# happened to collect files in. Running it reverse-ordered turned seven passing
# tests red -- four because `YAZSES_INJECTOR` was still set from an earlier file,
# three because the CLI's help strings had been rewritten in place. CI only ever
# runs one order, so neither was visible, and both polluting files had a fixture
# whose author believed it handled exactly this.
#
# A test that changes the outcome of another test is not a guard, it is a coin
# flip -- `test_cli_help_keeps_config_sections.py` already says so in its own
# fixture. These make the property hold for the whole suite rather than one file.

_INJECTOR_ENV = ("YAZSES_INJECTOR", "YAZSES_INJECT_FALLBACK")


@pytest.fixture(autouse=True)
def _no_test_may_leak_the_injector_env():
    """`inject.auto.apply_injection_config` writes these two variables into the
    process environment, by design -- they are how `[injection] backend` reaches a
    zero-argument `injector_factory`. In one process per run that is correct; in a
    shared test process the next test inherits the setting.

    `monkeypatch.delenv(name, raising=False)` does **not** protect against it. When
    the variable is absent -- the normal case -- `delitem` records nothing to undo,
    so the fixture is inert and whatever the test sets afterwards survives teardown.
    Two files relied on exactly that.
    """
    before = {name: os.environ.get(name) for name in _INJECTOR_ENV}
    yield
    leaked = {
        name: os.environ.get(name)
        for name in _INJECTOR_ENV
        if os.environ.get(name) != before[name]
    }
    for name, value in before.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    assert not leaked, (
        f"this test left {leaked} in the environment. `get_injector()` reads them, "
        "so every later test that asks for an injector gets this one's answer -- "
        "`test_auto_inject.py` built a ClipboardInjector where it asserted xdotool. "
        "Save and restore them explicitly; `monkeypatch.delenv(..., raising=False)` "
        "records nothing to undo when the variable was not already set."
    )


def _help_witness():
    """The one command function whose docstring names a config section, resolved once.

    `cli_help.apply` rewrites every docstring in the app in a single pass, so one
    witness detects it and the guard below stays O(1) -- it runs on all ~14 500
    tests, and scanning every command against every section name on each of them
    cost the suite a third of its runtime.

    Resolved by search rather than hardcoded: naming a command here would make the
    guard silently blind the day that command is renamed or its help reworded.
    """
    import yazses.cli as cli_mod
    from yazses.cli_help import config_section_names

    known = config_section_names()
    for command in getattr(cli_mod.app, "registered_commands", ()):
        fn = getattr(command, "callback", None)
        doc = getattr(fn, "__doc__", None) or ""
        if any(f"[{name}]" in doc for name in known):
            return fn, doc
    return None, None


def _help_slots(app):
    """Every (object, attribute) pair `cli_help.apply` writes to, sub-apps included."""
    slots = [(app.info, "help")]
    for command in getattr(app, "registered_commands", ()):
        slots.append((command, "help"))
        fn = getattr(command, "callback", None)
        if fn is not None:
            slots.append((fn, "__doc__"))
            slots += [(d, "help") for d in (fn.__defaults__ or ()) if hasattr(d, "help")]
    info = getattr(app, "registered_callback", None)
    if info is not None and getattr(info, "callback", None):
        fn = info.callback
        slots.append((fn, "__doc__"))
        slots += [(d, "help") for d in (fn.__defaults__ or ()) if hasattr(d, "help")]
    for group in getattr(app, "registered_groups", ()):
        slots.append((group, "help"))
        sub = getattr(group, "typer_instance", None)
        if sub is not None:
            slots += _help_slots(sub)
    return slots


@pytest.fixture(scope="session")
def _cli_help_witness():
    """(function, pristine docstring) -- resolved once for the whole session."""
    return _help_witness()


@pytest.fixture(scope="session")
def _pristine_cli_help():
    """The unescaped help text, captured once before any test can rewrite it.

    Session-scoped so the walk happens a single time; the per-test guard below
    compares one cheap sentinel and only touches this when it has actually moved.
    """
    import yazses.cli as cli_mod

    return [(obj, attr, getattr(obj, attr, None)) for obj, attr in _help_slots(cli_mod.app)]


@pytest.fixture(autouse=True)
def _no_test_may_rewrite_the_cli_help_strings(_pristine_cli_help, _cli_help_witness):
    """`cli.main()` calls `cli_help.apply`, which escapes `[section]` in place on the
    module-level command functions -- and its own docstring states the contract that
    makes that safe: "called from `cli.main()` and nowhere else", so the generators
    that read the same strings raw see them unescaped.

    That contract holds in production, where each invocation is a fresh process. It
    cannot hold in a test session, where `main()` and `scripts/gen-docs.py` share
    one. `test_platform_bsd_and_fallback.py` calls `main()` to prove the console
    script prints a sentence instead of a traceback, and every later test saw
    escaped help: `test_gen_docs.py`, `test_gen_man.py` and
    `test_cli_help_keeps_config_sections.py` all failed on it.

    Restores before failing, so one offending test cannot cascade into the rest of
    the run -- the cascade is what made this expensive to diagnose.
    """
    witness, pristine = _cli_help_witness
    yield
    if witness is None or witness.__doc__ == pristine:
        return
    for obj, attr, value in _pristine_cli_help:
        try:
            setattr(obj, attr, value)
        except (AttributeError, TypeError):
            pass
    raise AssertionError(
        f"this test rewrote the CLI help strings in place ({witness.__name__}'s "
        "docstring changed). "
        "They are module-level singletons shared with the whole run, so "
        "the doc and man-page generators -- which read them raw, by design -- then "
        "diff against the committed files and fail. The originals have been put "
        "back; if the test must call `cli.main()`, snapshot and restore them itself."
    )


@pytest.fixture
def cli_help_restored(_pristine_cli_help):
    """Opt-in restore for a test that legitimately has to call `cli.main()`.

    Not autouse: walking the app is worth doing once per session, not 14 000 times.
    Requesting it is the declaration that this test rewrites the shared help text on
    purpose. Its teardown runs *before* the autouse guard's check -- pytest finalises
    function-scoped fixtures in reverse setup order and autouse ones are set up
    first -- so a test that asks for it puts the strings back and passes.
    """
    yield
    for obj, attr, value in _pristine_cli_help:
        try:
            setattr(obj, attr, value)
        except (AttributeError, TypeError):
            pass
