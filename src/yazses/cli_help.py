"""Keep `[section]` names alive in `--help`.

`cli.py` builds its Typer app with ``rich_markup_mode="rich"``, so Rich parses the
help text for markup — and a config section written the way the documentation writes
it, ``[meeting]``, is indistinguishable from a style tag. Rich drops it. Twelve
commands told the user to set a key and did not say which section it lived in:

    Requires ` enabled = true` (`yazses features enable meeting`).

which is not a typo, it is a missing instruction. `[tts]`, `[learning]`, `[gaze]`,
`[overlay]`, `[voiceprint]`, `[recall]`, `[punch_in]` and `[meeting]` all vanished
this way, and the source they vanished from reads perfectly.

Escaping happens here, at the boundary, rather than in the source strings. Writing
``\\[meeting]`` in every docstring would put a rendering concern into the text and
leak the backslash into `docs/command-index.md` and the man page, both of which read
these strings raw and neither of which goes through Rich.

**The set of names is derived from `Config`, never listed here.** A hand-written list
covers the sections somebody remembered, and this repo has been bitten by that shape
often enough to have a rule about it. Deriving it also makes the escape exact: it can
only ever match a real section, so a genuine `[bold]` tag — `cli.py` uses three — is
untouched by construction rather than by a caveat.
"""
from __future__ import annotations

import dataclasses
import functools
from typing import Any


@functools.lru_cache(maxsize=1)
def config_section_names() -> frozenset[str]:
    """Every `[section]` a `config.toml` can contain, from the dataclass itself."""
    from yazses.config import Config

    names = set()
    for fld in dataclasses.fields(Config):
        names.add(fld.name)
        value = getattr(Config(), fld.name, None)
        if dataclasses.is_dataclass(value):
            for sub in dataclasses.fields(value):
                if dataclasses.is_dataclass(getattr(value, sub.name, None)):
                    names.add(f"{fld.name}.{sub.name}")
    return frozenset(names)


def escape_config_sections(text: str | None) -> str | None:
    """Backslash-escape `[section]` so Rich prints it instead of parsing it."""
    if not text:
        return text
    for name in config_section_names():
        token = f"[{name}]"
        if token in text:
            text = text.replace(token, f"\\{token}")
    return text


def _escape_params(func: Any) -> None:
    """Escape the `help=` of every `typer.Option`/`Argument` default on *func*.

    Reached through `__defaults__` rather than `inspect.signature`, because that is
    the object Typer itself reads: a signature copy would be escaped and discarded.
    """
    for default in getattr(func, "__defaults__", None) or ():
        help_text = getattr(default, "help", None)
        if isinstance(help_text, str):
            try:
                default.help = escape_config_sections(help_text)
            except (AttributeError, TypeError):  # frozen or exotic default
                pass


def apply(app: Any) -> None:
    """Escape section names throughout *app*, in place, including sub-apps.

    Called from `cli.main()` and nowhere else. `scripts/gen-docs.py` and
    `scripts/gen-man.py` import the app without going through `main()`, so the text
    they read stays unescaped -- which is what makes this a rendering fix rather than
    a change to the strings themselves.
    """
    info = getattr(app, "info", None)
    if info is not None:
        info.help = escape_config_sections(getattr(info, "help", None))

    for command in getattr(app, "registered_commands", ()):
        command.help = escape_config_sections(getattr(command, "help", None))
        callback = getattr(command, "callback", None)
        if callback is not None:
            if callback.__doc__:
                callback.__doc__ = escape_config_sections(callback.__doc__)
            _escape_params(callback)

    callback_info = getattr(app, "registered_callback", None)
    if callback_info is not None and getattr(callback_info, "callback", None):
        fn = callback_info.callback
        if fn.__doc__:
            fn.__doc__ = escape_config_sections(fn.__doc__)
        _escape_params(fn)

    for group in getattr(app, "registered_groups", ()):
        group.help = escape_config_sections(getattr(group, "help", None))
        sub = getattr(group, "typer_instance", None)
        if sub is not None:
            apply(sub)
