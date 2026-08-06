"""Daemon entry point. Thin wrapper around yazses.core.daemon.run()."""

from yazses.core.daemon import run

if __name__ == "__main__":
    run()
