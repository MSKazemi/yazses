import logging

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
