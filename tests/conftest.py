import importlib
import logging
import os
from pathlib import Path

import numpy as np
import pytest


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
    """Is *pid* a live process? Signal 0 checks without delivering anything."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False
    return True


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
        "Point the platform paths at tmp_path and clear the `get_platform`/`get_paths` "
        "lru_caches, or mock the lifecycle backend. Two reasons XDG_CONFIG_HOME alone "
        "is not enough: the caches ignore it once warm, and platformdirs never reads "
        "it off Linux at all — set APPDATA/LOCALAPPDATA (Windows) and HOME (macOS) "
        "too, then assert `get_paths().config_dir` really is under tmp_path. See the "
        "`scratch` fixture in tests/test_features_core_is_not_unknown.py."
    )
