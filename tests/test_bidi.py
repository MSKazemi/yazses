"""Display-only bidi isolation of user text in English UI sentences (FA-07, #516).

`yazses.bidi` decides when a quoted run needs FSI..PDI and builds the display copy.
These vectors are the issue's list -- Persian only, mixed, digits, URL/email/path,
ZWNJ, punctuation, multiline, emoji -- plus the two ways a quoted string could break
out of its isolate (a stray PDI, an override). The call-site tests hold the other
half of the contract: the *display* copy is isolated, the stored/injected value is
not, so no isolate can reach the clipboard, a config file or the focused window.

Invisible characters are spelled with ``\\N{...}`` names, never typed raw, so a
reader of this file can see every code point it asserts on.
"""

from __future__ import annotations

import ast
import unicodedata
from pathlib import Path

import pytest

from yazses.bidi import (
    FSI,
    PDI,
    has_rtl,
    quote_user_text,
    strip_explicit_controls,
    wrap_user_text,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "yazses"

ZWNJ = "\N{ZERO WIDTH NON-JOINER}"
RLO = "\N{RIGHT-TO-LEFT OVERRIDE}"
PDF = "\N{POP DIRECTIONAL FORMATTING}"
LRI = "\N{LEFT-TO-RIGHT ISOLATE}"
RLM = "\N{RIGHT-TO-LEFT MARK}"

#: Text the isolate must leave alone: nothing right-to-left in it.
UNCHANGED = [
    "",
    "Built-in Microphone",
    "Realtek(R) Audio (USB) 2",
    "https://example.com/a?b=c",
    "name@example.com",
    "/home/user/project",
    r"C:\Users\me\notes.txt",
    "1234",
    "\N{EXTENDED ARABIC-INDIC DIGIT ONE}\N{EXTENDED ARABIC-INDIC DIGIT TWO}",  # Persian digits are EN
    "VS Code 3.13!",
    "\N{GRINNING FACE} ok",
    "line one\nline two",
]

#: (input, expected display copy) -- every right-to-left run isolated exactly once.
WRAPPED = [
    ("سلام دنیا", f"{FSI}سلام دنیا{PDI}"),
    ("سلام!", f"{FSI}سلام!{PDI}"),
    ("من از VS Code استفاده می" + ZWNJ + "کنم.",
     f"{FSI}من از VS Code استفاده می{ZWNJ}کنم.{PDI}"),
    ("VS Code سلام", f"{FSI}VS Code سلام{PDI}"),
    ("ایمیل من name@example.com است.", f"{FSI}ایمیل من name@example.com است.{PDI}"),
    ("فایل در /home/user/project قرار دارد.", f"{FSI}فایل در /home/user/project قرار دارد.{PDI}"),
    ("نسخه Python 3.13 را نصب کن.", f"{FSI}نسخه Python 3.13 را نصب کن.{PDI}"),
    ("میکروفون (داخلی)", f"{FSI}میکروفون (داخلی){PDI}"),
    ("سلام \N{GRINNING FACE}", f"{FSI}سلام \N{GRINNING FACE}{PDI}"),
    # Arabic-Indic digits are bidi class AN: they reorder inside an LTR sentence too.
    ("\N{ARABIC-INDIC DIGIT THREE}-\N{ARABIC-INDIC DIGIT FOUR}",
     f"{FSI}\N{ARABIC-INDIC DIGIT THREE}-\N{ARABIC-INDIC DIGIT FOUR}{PDI}"),
    ("שלום", f"{FSI}שלום{PDI}"),  # Hebrew (class R), not only Arabic script (AL)
]


@pytest.mark.parametrize("text", UNCHANGED)
def test_text_with_no_rtl_is_returned_byte_for_byte(text):
    assert wrap_user_text(text) == text
    assert FSI not in wrap_user_text(text)


@pytest.mark.parametrize(("text", "expected"), WRAPPED)
def test_rtl_text_is_isolated_once_and_otherwise_untouched(text, expected):
    assert wrap_user_text(text) == expected


@pytest.mark.parametrize("text", [t for t, _ in WRAPPED] + UNCHANGED)
def test_removing_the_isolates_gives_back_the_logical_string(text):
    """Never reversed, never reordered: the display copy is the text plus two marks."""
    shown = wrap_user_text(text)
    assert shown.replace(FSI, "").replace(PDI, "") == text


@pytest.mark.parametrize("text", [t for t, _ in WRAPPED] + UNCHANGED)
def test_wrapping_is_idempotent(text):
    once = wrap_user_text(text)
    assert wrap_user_text(once) == once


def test_zwnj_survives_as_a_character():
    word = "می" + ZWNJ + "کنم"
    assert ZWNJ in wrap_user_text(word)


def test_multiline_text_is_isolated_per_paragraph():
    """A paragraph separator ends every isolate (UAX #9 P1), so one pair cannot span two."""
    text = "خط اول\nline two\r\nخط سوم"
    assert wrap_user_text(text) == f"{FSI}خط اول{PDI}\nline two\r\n{FSI}خط سوم{PDI}"


def test_a_stray_pdi_in_the_text_cannot_close_our_isolate_early():
    shown = wrap_user_text("سلام" + PDI + " evil")
    assert shown == f"{FSI}سلام evil{PDI}"
    assert shown.count(PDI) == 1


def test_an_override_in_the_text_is_dropped_from_the_display_copy():
    """An RLO..PDF pair renders a name as its mirror -- the spec's §6 hidden-override case."""
    assert wrap_user_text(f"{RLO}txt.exe{PDF}") == "txt.exe"
    assert wrap_user_text(f"فایل {RLO}txt.exe{PDF}") == f"{FSI}فایل txt.exe{PDI}"
    assert wrap_user_text(f"{LRI}سلام") == f"{FSI}سلام{PDI}"


def test_marks_are_ordinary_characters_and_survive():
    assert strip_explicit_controls(f"a{RLM}b{ZWNJ}c") == f"a{RLM}b{ZWNJ}c"


def test_a_non_string_is_formatted_first():
    assert wrap_user_text(0.004) == "0.004"
    assert wrap_user_text(None) == "None"


def test_has_rtl_reads_bidi_classes_not_scripts():
    assert has_rtl("سلام")
    assert has_rtl("\N{ARABIC-INDIC DIGIT ONE}")
    assert not has_rtl("\N{EXTENDED ARABIC-INDIC DIGIT ONE}")  # Persian digit: class EN
    assert not has_rtl("hello 123 \N{GRINNING FACE}")


# ---- quote_user_text: the `!r` replacement ---------------------------------------


@pytest.mark.parametrize("value", ["intro", "it's", 0.004, 3, True, "a\nb"])
def test_quote_is_exactly_repr_for_english_and_non_strings(value):
    assert quote_user_text(value) == repr(value)


def test_quote_keeps_zwnj_as_a_letter_instead_of_escaping_it():
    word = "می" + ZWNJ + "کنم"
    assert "\\u200c" in repr(word)  # the defect: repr spells ZWNJ out
    shown = quote_user_text(word)
    assert shown == f"'{FSI}{word}{PDI}'"
    assert "\\u200c" not in shown


def test_quote_puts_the_sentence_quotes_outside_the_isolate():
    assert quote_user_text("سلام!") == f"'{FSI}سلام!{PDI}'"


# ---- the call sites: display copy isolated, stored value raw ----------------------


def test_tray_tooltip_and_menu_isolate_a_persian_device_name():
    from yazses.audio.devices import InputDevice
    from yazses.tray.menu import build_menu_model, icon_spec

    name = "میکروفون (داخلی)"
    _color, tooltip = icon_spec({"state": "idle", "input_device": name})
    assert f"Mic: {FSI}{name}{PDI}\n" in tooltip

    device = InputDevice(index=3, name=name, channels=1, is_default=True)
    model = build_menu_model({"input_device": name}, [device], pinned="")
    assert model.mic_line == f"Mic: {FSI}{name}{PDI}"
    row = model.devices[1]
    assert row.label == f"{FSI}{name}{PDI} (OS default)"
    assert row.device == name  # what a click pins: raw


def test_tray_tooltip_is_unchanged_for_an_english_device():
    from yazses.tray.menu import icon_spec

    _color, tooltip = icon_spec({"state": "idle", "input_device": "USB Mic"})
    assert "Mic: USB Mic\n" in tooltip


def test_settings_microphone_rows_isolate_labels_and_keep_raw_values():
    from types import SimpleNamespace

    from yazses.settingsui.controls import mic_choices

    name = "میکروفون (داخلی)"
    rows = mic_choices([SimpleNamespace(name=name)], default_name=name, pinned=name)
    assert rows[0].label == f"Follow the system default (currently {FSI}{name}{PDI})"
    assert rows[0].value == ""
    assert rows[1].label == f"{FSI}{name}{PDI} ● ★"
    assert rows[1].value == name  # written to [audio] device: raw
    assert rows[1].is_default and rows[1].is_pinned


def test_settings_save_message_isolates_persian_and_writes_the_raw_value():
    from yazses.settingsui.controls import apply_setting

    written: list[object] = []
    value = "یزسس، می" + ZWNJ + "کنم"
    ok, message = apply_setting(
        "stt", "initial_prompt", value,
        write=lambda s, k, v: written.append(v) or True,
    )
    assert ok
    assert written == [value]  # the config gets the raw text, no isolate
    assert f"= '{FSI}{value}{PDI}'. Restart" in message
    assert "\\u200c" not in message


def test_settings_filter_status_isolates_a_persian_query():
    from yazses.settingsui.search import describe_filter

    assert describe_filter(0, 10, "  سلام! ") == (
        f"No capability matches '{FSI}سلام!{PDI}'. Try a shorter word."
    )
    assert describe_filter(0, 10, "zzz") == "No capability matches 'zzz'. Try a shorter word."


def test_bookmark_messages_isolate_the_label_and_store_it_raw():
    from yazses.bookmarks.caret import Caret
    from yazses.bookmarks.service import BookmarkService

    class Backend:
        def __init__(self):
            self.at = Caret("gedit:notes.txt", 7)

        def caret(self):
            return self.at

        def move_to(self, caret):
            self.at = caret
            return True

    svc = BookmarkService(Backend)
    label = "مقدمه!"
    assert svc.add(label) == f"Bookmarked '{FSI}{label}{PDI}'."
    assert svc.goto(label) == f"Jumped to '{FSI}{label}{PDI}'."
    assert svc.add("intro") == "Bookmarked 'intro'."


def test_the_window_focus_toast_isolates_the_spoken_name(mocker):
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    class NoWindows:
        def list_windows(self):
            return []

        def focus(self, window_id):
            return False

        def perform(self, action):
            return False

    sent = mocker.patch("yazses.system.notify.notify")
    daemon = Daemon(config=Config(), platform=get_platform())
    daemon._window_backend = NoWindows()
    event: dict = {}
    assert daemon._try_window_focus("focus تلگرام", event) is True
    assert event["discard_reason"] == "window_focus_no_match"
    title, body = sent.call_args.args
    assert title == "No window matched"
    assert f"for '{FSI}تلگرام{PDI}'." in body


# ---- the isolate never reaches what is typed, copied or saved ---------------------

#: Modules whose output is the user's text itself: the injector, the clipboard, the
#: post-processing chain, config writes and transcript files. An isolate in any of
#: them would be typed into the user's document or saved into their files.
CONTENT_PATHS = (
    "inject",
    "postprocess",
    "cliphistory",
    "recimport",
    "meeting",
    "system/clipboard.py",
    "system/configedit.py",
)


def _imports_bidi(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "yazses.bidi":
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "yazses" and any(
            alias.name == "bidi" for alias in node.names
        ):
            return True
        if isinstance(node, ast.Import) and any(a.name == "yazses.bidi" for a in node.names):
            return True
    return False


def _content_files() -> list[Path]:
    files: list[Path] = []
    for rel in CONTENT_PATHS:
        target = SRC / rel
        files.extend(sorted(target.rglob("*.py")) if target.is_dir() else [target])
    return files


def test_the_content_path_list_names_real_files():
    """A guard over an empty set is green for nothing: every entry must exist."""
    for rel in CONTENT_PATHS:
        assert (SRC / rel).exists(), f"{rel} moved; update CONTENT_PATHS"
    assert len(_content_files()) > 20


def test_no_content_path_imports_the_display_helper():
    offenders = [p.relative_to(SRC).as_posix() for p in _content_files() if _imports_bidi(p)]
    assert not offenders, (
        "yazses.bidi builds DISPLAY copies; these modules emit the user's text itself "
        f"(typed, copied or saved), where an isolate would leak: {offenders}"
    )


def test_the_import_detector_sees_every_spelling(tmp_path):
    """Red for the guard above: each import form must be caught."""
    for source in ("from yazses.bidi import wrap_user_text\n",
                   "from yazses import bidi\n",
                   "import yazses.bidi\n",
                   "def f():\n    from yazses.bidi import FSI\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(source, encoding="utf-8")
        assert _imports_bidi(probe), source
    clean = tmp_path / "clean.py"
    clean.write_text("from yazses.postprocess.persian_text import strip_bidi_controls\n",
                     encoding="utf-8")
    assert not _imports_bidi(clean)


def test_the_helper_source_spells_its_controls_as_escapes():
    """An invisible control typed raw into source is unreviewable (CVE-2021-42574)."""
    text = (SRC / "bidi.py").read_text(encoding="utf-8")
    raw = [hex(ord(c)) for c in text if unicodedata.category(c) == "Cf"]
    assert not raw, f"spell these as \\u escapes: {raw}"
