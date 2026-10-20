"""Conservative Mandarin Tier-1 command grammar.

Only the safe edit/navigation subset is localized here. Terminal execution and
open-ended refactor commands stay English-only until they receive separate native
review and safety coverage. Every rule is anchored; unmatched Chinese prose is dictation.
"""
from __future__ import annotations

import re
import unicodedata

from yazses.commands.grammars.base import CommandGrammar, GrammarRule
from yazses.commands.types import IntentType

_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_NUM = (
    r"(?:[0-9]{1,2}|[零〇一二两兩三四五六七八九]|"
    r"[一二两兩三四五六七八九]?十[一二两兩三四五六七八九]?)"
)
_OUTER_PUNCT = " \t\r\n.,!?;:\"'`…，。！？；：、“”‘’"


def parse_number_0_99(value: str) -> str | None:
    """Return a canonical decimal string for a bounded Mandarin count."""

    text = unicodedata.normalize("NFKC", value or "").strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        return str(number) if 0 <= number <= 99 else None

    if text in _DIGITS:
        return str(_DIGITS[text])

    text = text.replace("两", "二").replace("兩", "二")
    if text.count("十") != 1:
        return None

    tens_text, ones_text = text.split("十", 1)
    if tens_text == "":
        tens = 1
    elif len(tens_text) == 1 and tens_text in _DIGITS and _DIGITS[tens_text] != 0:
        tens = _DIGITS[tens_text]
    else:
        return None

    if ones_text == "":
        ones = 0
    elif len(ones_text) == 1 and ones_text in _DIGITS:
        ones = _DIGITS[ones_text]
    else:
        return None

    number = tens * 10 + ones
    return str(number) if 0 <= number <= 99 else None


def normalise(text: str) -> str:
    """NFKC plus outer punctuation removal; do not rewrite ordinary prose."""

    return unicodedata.normalize("NFKC", text or "").strip().strip(_OUTER_PUNCT).strip()


def normalise_arg(name: str, value: str) -> str:
    if name != "n":
        return value.strip()
    parsed = parse_number_0_99(value)
    return parsed if parsed is not None else value.strip()


_rules: list[GrammarRule] = []


def _add(
    pattern: str,
    intent: IntentType,
    action: str,
    arg_names: tuple[str, ...] = (),
) -> None:
    _rules.append(GrammarRule(re.compile(pattern, re.IGNORECASE), intent, action, arg_names))


# EDIT — closed, whole-utterance phrases only.
_add(rf"^(?:撤[销銷]|復原)\s*({_NUM})\s*次$", IntentType.EDIT, "undo_n", ("n",))
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
    rf"^(?:删除|刪除)(?:最后|最後)\s*({_NUM})\s*(?:个|個)?(?:词|詞|单词|單詞)$",
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
    rf"^(?:删除|刪除)(?:最后|最後)\s*({_NUM})\s*行$",
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
    rf"^(?:选择|選擇|选取|選取)\s*({_NUM})\s*行$",
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
    rf"^(?:转到|轉到|跳到|前往)\s*第?\s*({_NUM})\s*行$",
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
    r"^(?:转到|轉到|跳到|查找)(?:函数|函數|函式)\s+(.+)$",
    IntentType.NAVIGATE,
    "go_to_function",
    ("name",),
)
_add(
    r"^(?:转到|轉到|跳到|查找)(?:类|類|類別)\s+(.+)$",
    IntentType.NAVIGATE,
    "go_to_class",
    ("name",),
)
_add(
    r"^(?:打开|打開|开启|開啟)(?:文件|檔案)\s+(.+)$",
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
