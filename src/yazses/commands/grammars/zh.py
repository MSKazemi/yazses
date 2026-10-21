"""Conservative Mandarin Tier-1 command grammar.

Only the safe edit/navigation subset is localized here. Terminal execution and
open-ended refactor commands stay English-only until they receive separate native
review and safety coverage. Every rule is anchored; unmatched Chinese prose is dictation.

Every phrase here is **provisional**: it was written from dictionaries and existing
Simplified/Traditional UI conventions, not confirmed by a native Mandarin reviewer.
:data:`PHRASE_REVIEW` records that per action and is the worklist for the native
review in #505 (CMD-08); a phrase family moves to ``native-reviewed`` only there.
"""
from __future__ import annotations

import re
import unicodedata

from yazses.commands.grammars.base import CommandGrammar, GrammarRule
from yazses.commands.types import IntentType

#: Unit digits 1-9. 两/兩 is deliberately absent: it is the counting form of 2
#: (两行, 两百) and is not used as a tens multiplier (*两十) or a units digit (*二十两).
_UNITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_ZEROS = frozenset({"零", "〇"})
_TWOS = frozenset({"两", "兩"})

#: Explicit, closed ranges. A count (undo N times, delete/select the last N) keeps
#: the 0-99 ceiling Mandarin P1 shipped with, so no destructive repeat grows; a line
#: number reaches 999 because source files routinely pass line 99.
MAX_COUNT = 99
MAX_LINE_NUMBER = 999

# Regex fragments are ASCII-explicit for digits ([0-9], never \d, which also
# matches Arabic-Indic and full-width digits) and encode exactly the forms the
# parser accepts; tests/test_mandarin_command_numerals.py proves the two agree on
# every string up to five characters over the numeral alphabet.
_U = "[一二三四五六七八九]"
_SINGLE = "[零〇一二两兩三四五六七八九]"
_TENS = rf"(?:{_U}?十{_U}?)"
_HUNDREDS = rf"(?:[一二两兩三四五六七八九]百(?:[零〇]{_U}|{_U}十{_U}?)?)"
#: 0-99: undo_n, delete_words, delete_lines, select_lines.
_COUNT = rf"(?:[0-9]{{1,2}}|{_TENS}|{_SINGLE})"
#: 0-999: go_to_line.
_LINE = rf"(?:[0-9]{{1,3}}|{_HUNDREDS}|{_TENS}|{_SINGLE})"
#: Navigation targets are one ASCII identifier/path token. An open-ended ``(.+)``
#: let ordinary prose such as "打开文件 config.toml 之后再修改端口" become a
#: go_to_file whose "name" was the rest of the sentence.
_NAME = r"\s*([A-Za-z0-9_./\-]+)"
#: A file may also carry Han characters (開啟檔案 設定.toml), but only as one
#: whitespace-free token after an explicit space and ending in an ASCII extension,
#: so "打开文件夹里的config.toml" (no space: 文件夹 is "folder") stays dictation.
_FILE_NAME = r"(?:\s*(?=[A-Za-z0-9_./\-]+$)|\s+(?=\S+\.[A-Za-z0-9]{1,16}$))(\S+)"

_OUTER_PUNCT = " \t\r\n.,!?;:\"'`…，。！？；：、“”‘’"


def _parse_tens(text: str, *, allow_bare_ten: bool) -> int | None:
    """Parse 十 / 十X / X十 / X十Y; ``allow_bare_ten`` permits the leading-十 forms."""

    if text.count("十") != 1:
        return None
    tens_text, ones_text = text.split("十", 1)
    if tens_text == "":
        if not allow_bare_ten:
            return None
        tens = 1
    elif len(tens_text) == 1 and tens_text in _UNITS:
        tens = _UNITS[tens_text]
    else:
        return None
    if ones_text == "":
        ones = 0
    elif len(ones_text) == 1 and ones_text in _UNITS:
        ones = _UNITS[ones_text]
    else:
        return None
    return tens * 10 + ones


def _parse_han(text: str) -> int | None:
    if text in _ZEROS:
        return 0
    if text in _TWOS:
        return 2
    if text in _UNITS:
        return _UNITS[text]
    if "百" not in text:
        return _parse_tens(text, allow_bare_ten=True)

    head, rest = text.split("百", 1)
    if len(head) != 1:
        return None  # 百 alone, 十百, 一千…: refuse rather than guess.
    hundreds = 2 if head in _TWOS else _UNITS.get(head)
    if hundreds is None:
        return None
    if rest == "":
        return hundreds * 100
    if len(rest) == 2 and rest[0] in _ZEROS and rest[1] in _UNITS:
        return hundreds * 100 + _UNITS[rest[1]]  # 一百零五
    # Inside a hundred the tens digit is spoken (一百一十), and the elided
    # colloquial forms 一百一 (=110) / 两百五 (=250) are refused, not guessed:
    # pending native review (#505) they stay dictation.
    tens = _parse_tens(rest, allow_bare_ten=False)
    if tens is None:
        return None
    return hundreds * 100 + tens


def parse_command_number(value: str, maximum: int = MAX_LINE_NUMBER) -> str | None:
    """Return a canonical decimal string for a bounded Mandarin command number.

    Accepts ASCII digits (after NFKC, so full-width digits too) and the standard
    Chinese forms 零/〇, 一…九, 两/兩 (standalone or as the hundreds multiplier),
    十, 十一…九十九, and X百 / X百零Y / X百Y十[Z]. Everything else — 千, 万,
    百 alone, elided forms, 两 as a tens or units digit, mixed Arabic/Han, or a
    value above ``maximum`` — returns ``None``. There is no fuzzy fallback.
    """

    text = unicodedata.normalize("NFKC", value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"[0-9]+", text):
        # No more digits than the range itself has: "005" is not a 0-99 count.
        if len(text) > len(str(maximum)):
            return None
        number: int | None = int(text)
    else:
        number = _parse_han(text)
    if number is None or not 0 <= number <= maximum:
        return None
    return str(number)


def parse_number_0_99(value: str) -> str | None:
    """Return a canonical decimal string for a bounded Mandarin count (0-99)."""

    return parse_command_number(value, MAX_COUNT)


def normalise(text: str) -> str:
    """NFKC plus outer punctuation removal; do not rewrite ordinary prose."""

    return unicodedata.normalize("NFKC", text or "").strip().strip(_OUTER_PUNCT).strip()


def normalise_arg(name: str, value: str) -> str | None:
    """Canonicalise a captured argument; ``None`` rejects the whole rule.

    A count the parser refuses must not reach dispatch as raw text, so a numeral
    the pattern captured but the parser does not accept fails closed to dictation.
    """

    if name != "n":
        return value.strip()
    return parse_command_number(value, MAX_LINE_NUMBER)


_rules: list[GrammarRule] = []


def _add(
    pattern: str,
    intent: IntentType,
    action: str,
    arg_names: tuple[str, ...] = (),
) -> None:
    _rules.append(GrammarRule(re.compile(pattern, re.IGNORECASE), intent, action, arg_names))


# EDIT — closed, whole-utterance phrases only.
_add(rf"^(?:撤[销銷]|復原)\s*({_COUNT})\s*次$", IntentType.EDIT, "undo_n", ("n",))
_add(r"^(?:撤[销銷](?:操作)?|復原)$", IntentType.EDIT, "undo")
_add(r"^(?:保存(?:文件)?|儲存(?:檔案)?|存檔)$", IntentType.EDIT, "save")
_add(r"^(?:复制|複製)$", IntentType.EDIT, "copy")
_add(r"^(?:剪切|剪下)$", IntentType.EDIT, "cut")
_add(r"^(?:粘贴|黏貼|贴上|貼上)$", IntentType.EDIT, "paste")

_add(
    r"^(?:删除|刪除)(?:最后|最後)(?:一)?(?:个|個)?(?:词|詞|单词|單詞)$",
    IntentType.EDIT,
    "delete_words",
)
_add(
    rf"^(?:删除|刪除)(?:最后|最後)\s*({_COUNT})\s*(?:个|個)?(?:词|詞|单词|單詞)$",
    IntentType.EDIT,
    "delete_words",
    ("n",),
)
_add(
    r"^(?:删除|刪除)(?:最后|最後)(?:一)?行$",
    IntentType.EDIT,
    "delete_lines",
)
_add(
    rf"^(?:删除|刪除)(?:最后|最後)\s*({_COUNT})\s*行$",
    IntentType.EDIT,
    "delete_lines",
    ("n",),
)
_add(
    r"^(?:注释|註釋|註解)(?:这一行|這一行|当前行|當前行)$",
    IntentType.EDIT,
    "comment",
)
_add(
    rf"^(?:选择|選擇|选取|選取)\s*({_COUNT})\s*行$",
    IntentType.EDIT,
    "select_lines",
    ("n",),
)
_add(
    r"^(?:选择|選擇|选取|選取)(?:到|至)(?:结尾|結尾|末尾)$",
    IntentType.EDIT,
    "select_to_end",
)
_add(r"^(?:全选|全選|全部选择|全部選擇)$", IntentType.EDIT, "select_all")

_add(r"^(?:按\s*)?(?:回车|回車|enter|return)\s*(?:键|鍵)?$", IntentType.EDIT, "press_enter")
_add(r"^(?:换行|換行|新的一行)$", IntentType.EDIT, "press_enter")
_add(r"^(?:按\s*)?(?:tab|制表)\s*(?:键|鍵)?$", IntentType.EDIT, "press_tab")
_add(r"^(?:按\s*)?(?:escape|esc)\s*(?:键|鍵)?$", IntentType.EDIT, "press_escape")
_add(r"^(?:按\s*)?(?:backspace|退格)\s*(?:键|鍵)?$", IntentType.EDIT, "press_backspace")

# NAVIGATE — explicit cursor/navigation wording avoids command-like words in prose.
_add(
    rf"^(?:转到|轉到|跳到|前往)\s*第?\s*({_LINE})\s*行$",
    IntentType.NAVIGATE,
    "go_to_line",
    ("n",),
)
_add(r"^(?:上一页|上一頁|向上翻页|向上翻頁)$", IntentType.NAVIGATE, "page_up")
_add(r"^(?:下一页|下一頁|向下翻页|向下翻頁)$", IntentType.NAVIGATE, "page_down")
_add(
    r"^(?:(?:转到|轉到|跳到|前往))?(?:行首|这一行开头|這一行開頭)$",
    IntentType.NAVIGATE,
    "line_home",
)
_add(
    r"^(?:(?:转到|轉到|跳到|前往))?(?:行尾|这一行结尾|這一行結尾)$",
    IntentType.NAVIGATE,
    "line_end",
)
_add(r"^(?:光标|游标|游標)(?:向上|上移)$", IntentType.NAVIGATE, "arrow_up")
_add(r"^(?:光标|游标|游標)(?:向下|下移)$", IntentType.NAVIGATE, "arrow_down")
_add(r"^(?:光标|游标|游標)(?:向左|左移)$", IntentType.NAVIGATE, "arrow_left")
_add(r"^(?:光标|游标|游標)(?:向右|右移)$", IntentType.NAVIGATE, "arrow_right")
_add(
    rf"^(?:转到|轉到|跳到|查找)(?:函数|函數|函式){_NAME}$",
    IntentType.NAVIGATE,
    "go_to_function",
    ("name",),
)
_add(
    rf"^(?:转到|轉到|跳到|查找)(?:类|類|類別){_NAME}$",
    IntentType.NAVIGATE,
    "go_to_class",
    ("name",),
)
_add(
    rf"^(?:打开|打開|开启|開啟)(?:文件|檔案){_FILE_NAME}$",
    IntentType.NAVIGATE,
    "go_to_file",
    ("name",),
)


MANDARIN_GRAMMAR = CommandGrammar(
    language="zh",
    rules=tuple(_rules),
    normalise=normalise,
    normalise_arg=normalise_arg,
)

SAFE_CORE_ACTIONS = tuple(dict.fromkeys(rule.action for rule in MANDARIN_GRAMMAR.rules))

#: Actions that remove text. Each is reachable only through the literal, checkable
#: prefix 删除最后 / 刪除最後 ("delete the last") followed by a counted unit (词/行),
#: with the count capped at :data:`MAX_COUNT`. A bare 删除, 删除这一行, 全部删除 or
#: 删除所有内容 is dictation. tests/test_mandarin_command_safety.py enforces this.
DESTRUCTIVE_ACTIONS = frozenset({"delete_words", "delete_lines"})
DESTRUCTIVE_TRIGGER_PREFIX = "^(?:删除|刪除)(?:最后|最後)"

REVIEW_PROVISIONAL = "provisional"
REVIEW_NATIVE = "native-reviewed"
REVIEW_STATES = (REVIEW_PROVISIONAL, REVIEW_NATIVE)

#: Native-review state of each shipped phrase family (#505, CMD-08). Explicit per
#: action, so a newly added action cannot ship without a declared state. Nothing has
#: been natively reviewed yet; do not flip an entry without that review's record.
PHRASE_REVIEW: dict[str, str] = {
    "undo_n": REVIEW_PROVISIONAL,
    "undo": REVIEW_PROVISIONAL,
    "save": REVIEW_PROVISIONAL,
    "copy": REVIEW_PROVISIONAL,
    "cut": REVIEW_PROVISIONAL,
    "paste": REVIEW_PROVISIONAL,
    "delete_words": REVIEW_PROVISIONAL,
    "delete_lines": REVIEW_PROVISIONAL,
    "comment": REVIEW_PROVISIONAL,
    "select_lines": REVIEW_PROVISIONAL,
    "select_to_end": REVIEW_PROVISIONAL,
    "select_all": REVIEW_PROVISIONAL,
    "press_enter": REVIEW_PROVISIONAL,
    "press_tab": REVIEW_PROVISIONAL,
    "press_escape": REVIEW_PROVISIONAL,
    "press_backspace": REVIEW_PROVISIONAL,
    "go_to_line": REVIEW_PROVISIONAL,
    "page_up": REVIEW_PROVISIONAL,
    "page_down": REVIEW_PROVISIONAL,
    "line_home": REVIEW_PROVISIONAL,
    "line_end": REVIEW_PROVISIONAL,
    "arrow_up": REVIEW_PROVISIONAL,
    "arrow_down": REVIEW_PROVISIONAL,
    "arrow_left": REVIEW_PROVISIONAL,
    "arrow_right": REVIEW_PROVISIONAL,
    "go_to_function": REVIEW_PROVISIONAL,
    "go_to_class": REVIEW_PROVISIONAL,
    "go_to_file": REVIEW_PROVISIONAL,
}

#: The numeral forms are provisional too. Open questions for the native reviewer:
#: whether the elided 一百一 (110) / 两百五 (250) should be accepted (today: refused,
#: stays dictation) and whether 一十 standalone is natural (today: accepted as 10).
NUMERAL_REVIEW = REVIEW_PROVISIONAL
