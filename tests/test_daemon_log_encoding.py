"""``daemon.log`` is UTF-8 on every OS, not the locale's code page."""

from __future__ import annotations

import logging

from yazses.system.private_log import PrivateRotatingFileHandler


def test_the_daemon_log_is_utf8_whatever_the_locale(tmp_path):
    """The stock handler takes the locale encoding, cp1252 on a Western Windows, and
    drops every record it cannot encode."""
    target = tmp_path / "daemon.log"
    handler = PrivateRotatingFileHandler(target, maxBytes=1_000_000, backupCount=1)
    try:
        assert handler.encoding == "utf-8"
        handler.emit(logging.makeLogRecord({"msg": "C:\\Users\\محسن 麦克风 \udcff"}))
    finally:
        handler.close()

    text = target.read_text(encoding="utf-8")
    assert "محسن 麦克风" in text
    assert "\\udcff" in text
