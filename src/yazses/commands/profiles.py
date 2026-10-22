"""Editor/app command profiles: which keys a spoken command sends in the focused app.

The grammar (`commands/grammar.py`) decides *what* was asked — "delete the last
line". The dispatcher (`commands/dispatch.py`) decides *which keys* that is, and its
built-in keymap is VS Code's. That is right for VS Code and for the editors that
copied its bindings, and wrong elsewhere: in a JetBrains IDE Ctrl+Shift+K is not
"delete line", and in Sublime Text F2 jumps to the next bookmark, so "rename this to
user_id" (F2, Ctrl+A, type the name) would select the whole file and type over it.

A profile is a small table of overrides on that keymap. The daemon picks one from
the focused application at the moment a command is dispatched, and hands its table
to the dispatcher. An override is either the keys to send instead or ``None``,
which means "this app has no safe binding": the command is refused — nothing is
sent and nothing is typed — rather than guessed.

Pure. The daemon passes the focused application's class string in; nothing here
reads the desktop, and nothing is stored.

OFF by default (`[commands] editor_profiles = false`). With it off the daemon never
builds a registry, and every application gets the default keymap exactly as before.

Every binding below is taken from the editor's own *default* Linux/Windows keymap.
None of them has been verified by injecting into a running editor yet; a user who
has remapped a key, or who uses the macOS keymap, gets the default's keys.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from yazses.config import CommandsConfig

DEFAULT_PROFILE = "default"

#: What `[commands] profile` means when it is not a profile name: follow the app.
AUTO = "auto"

#: One profile: action -> the key combos to send, or ``None`` to refuse the action.
#: An action the table does not name keeps the dispatcher's default keys.
Keymap = Mapping[str, tuple[str, ...] | None]

#: The built-in profiles. Action names are the dispatcher's (`dispatch.DEFAULT_KEYMAP`);
#: `tests/test_command_profiles.py` fails if one names an action that does not exist.
BUILTIN_PROFILES: dict[str, dict[str, tuple[str, ...] | None]] = {
    # The dispatcher's own keymap. Empty on purpose: nothing to override.
    DEFAULT_PROFILE: {},
    # The default keymap *is* VS Code's, so this is the default under its own name —
    # kept so a matched VS Code window reports what it matched, and so
    # `profile = "vscode"` is accepted.
    "vscode": {},
    # IntelliJ IDEA, PyCharm, WebStorm, CLion, GoLand, Rider, Android Studio, ...
    # (the default Windows/Linux keymap).
    "jetbrains": {
        "delete_lines": ("ctrl+y",),
        # File Structure popup: type to filter, the closest match to "go to symbol in file".
        "go_to_function": ("ctrl+F12",),
        "go_to_class": ("ctrl+n",),
        "go_to_file": ("ctrl+shift+n",),
        # In-place rename opens with the old name already selected, so typing replaces
        # it; Ctrl+A there would select the whole file instead.
        "rename_symbol": ("shift+F6",),
        "rename_select": (),
    },
    # Sublime Text. Delete line (Ctrl+Shift+K), go to line (Ctrl+G), go to file (Ctrl+P),
    # select line (Ctrl+L) and comment (Ctrl+/) already match the default keymap.
    "sublime": {
        # Goto Symbol in file.
        "go_to_function": ("ctrl+r",),
        "go_to_class": ("ctrl+r",),
        # No built-in rename. The default's F2 is "next bookmark", after which Ctrl+A
        # selects the whole buffer and the new name is typed over it.
        "rename_symbol": None,
    },
}

#: Substrings of the focused application's class, lower-cased, that pick a profile.
#: First match wins. X11 reports JetBrains IDEs as `jetbrains-<product>`, Sublime as
#: `sublime_text`, VS Code as `Code`; AT-SPI reports the application's name.
_APP_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("jetbrains", (
        "jetbrains", "intellij", "pycharm", "webstorm", "phpstorm", "clion", "goland",
        "rubymine", "datagrip", "rustrover", "android studio", "android-studio",
    )),
    ("sublime", ("sublime",)),
    ("vscode", ("vscodium", "codium", "code-oss", "visual studio code")),
)
#: Whole class names too short to match as a substring (`code` is inside `xcode`).
_APP_EXACT: dict[str, str] = {"code": "vscode"}

#: Logged once by the daemon the first time a command is dispatched with no app to go
#: on. Here, not in the daemon, so the wording is pinned by a test.
NO_FOCUSED_APP_REASON = (
    "Editor command profiles: the focused application could not be read, so spoken "
    "commands use the default (VS Code-style) keys. The only sources are AT-SPI and, "
    "on an X11 session, xdotool; macOS, Windows and a Wayland session without AT-SPI "
    "have none yet. Set [commands] profile to a profile name to choose one by hand."
)


def match_app(app_class: str) -> str | None:
    """The built-in profile for a focused application's class, or ``None``. Pure."""
    name = (app_class or "").strip().lower()
    if not name:
        return None
    if name in _APP_EXACT:
        return _APP_EXACT[name]
    for profile, keywords in _APP_KEYWORDS:
        if any(k in name for k in keywords):
            return profile
    return None


@dataclass(frozen=True)
class ProfileChoice:
    """The profile chosen for one command, and why.

    ``reason`` is ``"pinned"`` (`[commands] profile` names one), ``"matched"`` (the
    focused app was recognised), ``"no_match"`` (an app was read and is not one a
    profile exists for) or ``"no_app"`` (no application could be read at all).
    """

    name: str
    keymap: Keymap
    reason: str


@dataclass
class ProfileRegistry:
    #: Exact application class -> profile name. Checked before the built-in matcher.
    profiles: dict[str, str] = field(default_factory=dict)
    keymaps: dict[str, dict[str, tuple[str, ...] | None]] = field(
        default_factory=lambda: dict(BUILTIN_PROFILES)
    )
    #: Set when `[commands] profile` names a profile: every app then gets that one.
    pinned: str | None = None
    #: What was wrong with the configuration, for the daemon to log.
    problems: list[str] = field(default_factory=list)

    @property
    def needs_focused_app(self) -> bool:
        """Whether a choice depends on the focused app (so the daemon must read it)."""
        return self.pinned is None

    def resolve(self, profile_hint: str) -> str:
        """Return the profile name to use for ``profile_hint``. Falls back to 'default'."""
        if self.pinned is not None:
            return self.pinned
        if profile_hint in self.profiles:
            return self.profiles[profile_hint]
        return match_app(profile_hint) or DEFAULT_PROFILE

    def keymap(self, name: str) -> Keymap:
        """The overrides for profile ``name``; empty (the default keys) when unknown."""
        return MappingProxyType(self.keymaps.get(name, {}))

    def choose(self, app_class: str) -> ProfileChoice:
        """The profile for a command dispatched while ``app_class`` has focus."""
        if self.pinned is not None:
            return ProfileChoice(self.pinned, self.keymap(self.pinned), "pinned")
        if not (app_class or "").strip():
            return ProfileChoice(DEFAULT_PROFILE, self.keymap(DEFAULT_PROFILE), "no_app")
        name = self.resolve(app_class)
        reason = "no_match" if name == DEFAULT_PROFILE else "matched"
        return ProfileChoice(name, self.keymap(name), reason)


def load_profiles(config: CommandsConfig) -> ProfileRegistry:
    """Build a ProfileRegistry from CommandsConfig.

    `[commands] profile = "auto"` (the default) follows the focused application. A
    profile name pins that profile for every application. Any other value is reported
    in ``problems`` and pins the default keymap — the keys every install sent before
    profiles existed — rather than guessing which editor was meant.

    Does not read `editor_profiles`: the daemon decides whether to build a registry at
    all, so this stays a plain function of the values it is given.
    """
    registry = ProfileRegistry()
    wanted = (config.profile or "").strip().lower()
    if wanted in ("", AUTO):
        return registry
    if wanted in registry.keymaps:
        registry.pinned = wanted
        return registry
    registry.pinned = DEFAULT_PROFILE
    known = ", ".join([AUTO, *sorted(registry.keymaps)])
    registry.problems.append(
        f"[commands] profile {config.profile!r} is not a known profile ({known}); "
        "spoken commands use the default keys"
    )
    return registry
