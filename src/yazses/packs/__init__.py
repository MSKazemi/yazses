"""Feature add-on packs for frozen installs (ADR-028).

A frozen Windows install has no interpreter to ``pip install`` into, so a heavy feature's
libraries arrive as an *add-on pack*: a ZIP built by the same release job as the
installer, pinned to that exact base build, listed with its SHA-256 in an index built
into the installed app, and mounted at process start by a PyInstaller runtime hook.

The house split applies. Every module here except :mod:`~yazses.packs.fetch`,
:mod:`~yazses.packs.install` and the I/O half of :mod:`~yazses.packs.context` is pure,
and nothing under ``packs/`` branches on ``sys.platform``: the OS facts come through the
``PackRuntime`` Protocol in ``platform/base.py`` (AGENTS.md rule 6).

Importing this package imports nothing else, so the runtime hook stays cheap.
"""
