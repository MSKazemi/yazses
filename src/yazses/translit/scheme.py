"""Table-driven transliteration + scheme gate (pure) — ADR-v2-116.

Map romanized input to a native script by longest-match table lookup, and gate on all-ASCII text.
Pure and deterministic; the built-in table is Finglish → Persian.
"""
from __future__ import annotations

# Finglish (romanized Persian) → Persian script. Longest keys matched first.
_FINGLISH = {
    "kh": "خ", "gh": "ق", "ch": "چ", "sh": "ش", "zh": "ژ", "aa": "آ", "oo": "و",
    "ou": "و", "ee": "ی",
    "a": "ا", "b": "ب", "p": "پ", "t": "ت", "s": "س", "j": "ج", "h": "ه", "d": "د",
    "r": "ر", "z": "ز", "f": "ف", "q": "ق", "k": "ک", "g": "گ", "l": "ل", "m": "م",
    "n": "ن", "v": "و", "o": "و", "u": "و", "e": "ه", "i": "ی", "y": "ی", "w": "و",
}
_SCHEMES = {"finglish": _FINGLISH}
_MAX_KEY = 2


def transliterate(latin: str, scheme: str = "finglish") -> str:
    """Transliterate romanized ``latin`` to a native script by longest-match table lookup. Pure."""
    table = _SCHEMES.get(scheme)
    if table is None:
        return latin or ""
    s = latin or ""
    out = []
    i = 0
    while i < len(s):
        if not s[i].isalpha():
            out.append(s[i])
            i += 1
            continue
        matched = False
        for length in range(_MAX_KEY, 0, -1):
            seg = s[i:i + length].lower()
            if seg in table:
                out.append(table[seg])
                i += length
                matched = True
                break
        if not matched:
            out.append(s[i])
            i += 1
    return "".join(out)


#: Very common English words. Purpose-built for this check rather than borrowed from
#: another module's list: the job here is "is this sentence English?", and a list built
#: for filtering vocabulary proposals is missing "is", "it", "to", "a" and "me" -- exactly
#: the words that decide it.
#:
#: Kept short and uncontroversial on purpose. A longer list catches more English and also
#: swallows more Finglish, and the asymmetry below says which way to err.
_ENGLISH_MARKERS = frozenset("""
    the be to of and a in that have i it for not on with he as you do at this but his by
    from they we say her she or an will my one all would there their what so if me your
    can no when them how our its who them been has had was were are is am
""".split())


def looks_like_english(text: str) -> bool:
    """Does this Latin-script text contain a very common English word? Pure."""
    words = {w.strip(".,;:!?'\"").lower() for w in (text or "").split()}
    return bool(words & _ENGLISH_MARKERS)


def detect_scheme(text: str, enabled_scheme: str = "finglish"):
    """Return ``enabled_scheme`` when ``text`` looks like romanized input, else None. Pure.

    The docstring here used to promise "so English passes through" and the code returned
    the scheme for **any** all-ASCII text -- which is every English sentence. With
    ``[translit] enabled`` the caller transliterates whenever this is truthy, so English
    dictation was destroyed rather than passed through::

        "hello how are you"        ->  "ههللو هوو اره یو"
        "send me the file please"  ->  "سهند مه تهه فیله پلهاسه"
        "the quick brown fox"      ->  "تهه قویcک بروون فوx"

    The gate never gated. It now implements what it always claimed: a sentence containing
    a very common English word is left alone.

    The trade-off, stated because it is real: a Finglish sentence whose romanization
    collides with an English marker ("to khoobi?" -- Persian *to* is "you") is left in
    Latin script. That is the right direction. A missed transliteration leaves readable
    text the user can retry; a false one replaces the sentence with nonsense.
    """
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters or not all(ord(c) < 128 for c in letters):
        return None
    if looks_like_english(text):
        return None
    return enabled_scheme
