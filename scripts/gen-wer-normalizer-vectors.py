#!/usr/bin/env python3
"""Freeze Whisper's English text normaliser as test vectors for the Kotlin port (#677).

The desktop benchmark scores WER after ``whisper_normalizer.EnglishTextNormalizer``
(``paper/benchmark/bench_wer.py``). A phone measurement is only comparable with a desktop
one if both normalise the same way, so the Android ``:core:bench`` module ports that
normaliser. This script writes the oracle for the port: every input below, normalised by
the real package, as JSON the Kotlin tests replay.

Not a ``contract/`` vector family on purpose: ``contract/vectors`` is regenerated from
YazSes's own shipped code, and this expectation comes from a third-party package that a
default install does not have. The file is frozen data, guarded by
``tests/test_wer_normalizer_vectors.py`` (skipped when the package is absent).

    uv sync --group benchmark
    uv run python scripts/gen-wer-normalizer-vectors.py          # rewrite the file
    uv run python scripts/gen-wer-normalizer-vectors.py --check  # exit 1 if it differs

Output is deterministic: a fixed seed, sorted keys, no timestamps.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "android" / "core" / "bench" / "src" / "test" / "resources" / "wer-normalizer-vectors.json"
# The British->American table the Kotlin port ships (main resources, not test): the oracle's own
# english.json, flattened to "british<TAB>american" lines because :core:bench's strict JSON reader
# caps an object at 1,000 members and this table has about 1,700.
SPELLING_OUT = ROOT / "android" / "core" / "bench" / "src" / "main" / "resources" / "english-spelling.tsv"
SEED = 20261025

# (id, description, input). Every Whisper normaliser rule gets named cases; the seeded block
# below adds breadth. Ids are lower-case kebab, as in contract/vectors.
HAND: list[tuple[str, str, str]] = [
    # --- the empty and the degenerate -------------------------------------------------
    ("empty", "an empty string stays empty", ""),
    ("spaces-only", "whitespace alone collapses to nothing", "   \t \n  "),
    ("punctuation-only", "punctuation alone collapses to nothing", "?!.,;:--()[]{}"),
    ("single-word", "a plain word is lower-cased", "Hello"),
    ("mixed-case", "case is folded", "THE Quick bRoWn FoX"),
    ("extra-spaces", "runs of spaces collapse", "a    b     c"),
    # --- brackets, hesitations, fillers -----------------------------------------------
    ("square-brackets", "text in square brackets is dropped", "hello [inaudible] world"),
    ("round-brackets", "text in round brackets is dropped", "hello (laughs) world"),
    ("nested-brackets", "nested brackets", "a [b (c) d] e"),
    ("unclosed-bracket", "an unclosed bracket", "a [b c"),
    ("hesitation-um", "um is removed", "well um I think so"),
    ("hesitation-uh", "uh is removed", "uh yes uh no"),
    ("hesitation-hmm", "hmm and mm", "hmm mm yes"),
    ("hesitation-mhm", "mhm and mmm", "mhm mmm okay"),
    ("filler-after-space", "a filler at the start", "um hello"),
    # --- contractions and apostrophes -------------------------------------------------
    ("contraction-dont", "don't", "I don't know"),
    ("contraction-cant", "can't", "we can't go"),
    ("contraction-wont", "won't", "they won't come"),
    ("contraction-im", "I'm", "I'm here"),
    ("contraction-theyre", "they're", "they're late"),
    ("contraction-youve", "you've", "you've seen it"),
    ("possessive", "possessive 's", "John's book"),
    ("plural-possessive", "plural possessive", "the dogs' bowls"),
    ("curly-apostrophe", "typographic apostrophe", "don’t stop"),
    ("quote-marks", "quotation marks", "he said \"yes\" and 'no'"),
    ("contraction-letd", "let's", "let's go"),
    ("contraction-wouldve", "would've", "I would've gone"),
    ("contraction-whats", "what's", "what's that"),
    # --- titles and abbreviations -----------------------------------------------------
    ("title-mr", "mr", "Mr. Smith arrived"),
    ("title-mrs", "mrs", "Mrs. Jones left"),
    ("title-ms", "ms", "Ms. Lee spoke"),
    ("title-dr", "dr", "Dr. Who is here"),
    ("title-prof", "prof", "Prof. Brown teaches"),
    ("title-sr-jr", "senior and junior", "Smith Jr. and Smith Sr."),
    ("title-st", "saint or street", "St. Louis on Main St."),
    ("abbrev-etc", "etc", "apples, pears, etc."),
    ("abbrev-eg", "e.g.", "fruit, e.g. apples"),
    ("abbrev-ie", "i.e.", "that is, i.e. this one"),
    ("abbrev-vs", "vs", "red vs blue"),
    ("abbrev-am-pm", "a.m. and p.m.", "at 9 a.m. or 5 p.m."),
    ("abbrev-ok", "ok", "ok that's fine"),
    ("abbrev-okay", "okay", "okay then"),
    ("abbrev-us", "U.S.", "the U.S. economy"),
    ("abbrev-no", "no.", "see no. 5"),
    # --- cardinal numbers, spelled ----------------------------------------------------
    ("num-zero", "zero", "zero"),
    ("num-one", "one", "one"),
    ("num-teens", "teens", "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"),
    ("num-tens", "tens", "twenty thirty forty fifty sixty seventy eighty ninety"),
    ("num-twentyone", "compound", "twenty one"),
    ("num-twenty-hyphen", "hyphenated compound", "twenty-one"),
    ("num-ninety-nine", "ninety nine", "ninety nine"),
    ("num-hundred", "a hundred", "a hundred"),
    ("num-one-hundred", "one hundred", "one hundred"),
    ("num-hundred-and", "one hundred and five", "one hundred and five"),
    ("num-hundred-twenty-three", "one hundred twenty three", "one hundred twenty three"),
    ("num-two-hundred-fifty", "two hundred fifty", "two hundred fifty"),
    ("num-thousand", "one thousand", "one thousand"),
    ("num-two-thousand-and-five", "two thousand and five", "two thousand and five"),
    ("num-twelve-thousand", "twelve thousand three hundred", "twelve thousand three hundred forty five"),
    ("num-million", "three million", "three million"),
    ("num-million-half", "two and a half million", "two and a half million"),
    ("num-billion", "five billion", "five billion"),
    ("num-trillion", "one trillion", "one trillion"),
    ("num-a-thousand", "a thousand", "a thousand"),
    ("num-a-million", "a million", "a million"),
    ("num-hundred-thousand", "one hundred thousand", "one hundred thousand"),
    ("num-oh-one", "digit-by-digit with oh", "one oh one"),
    ("num-oh-seven", "oh seven", "oh seven"),
    ("num-digits-run", "digits spoken one by one", "five five five one two one two"),
    ("num-double", "double", "double oh seven"),
    ("num-triple", "triple", "triple five"),
    ("num-years-nineteen-eighty-four", "a year", "nineteen eighty four"),
    ("num-years-twenty-twenty", "twenty twenty", "twenty twenty"),
    ("num-years-two-thousand-ten", "two thousand ten", "two thousand ten"),
    ("num-decade-eighties", "nineteen eighties", "in the nineteen eighties"),
    ("num-decade-sixties", "the sixties", "the sixties"),
    ("num-point", "decimal with point", "three point one four"),
    ("num-point-five", "point five", "point five"),
    ("num-zero-point", "zero point two", "zero point two five"),
    ("num-and-a-half", "and a half", "two and a half"),
    ("num-quarter", "a quarter", "a quarter"),
    ("num-three-quarters", "three quarters", "three quarters of the way"),
    ("num-half", "a half", "half of it"),
    ("num-dozen", "a dozen", "a dozen eggs"),
    ("num-score", "a score", "four score and seven"),
    ("num-couple", "a couple", "a couple of times"),
    ("num-negative", "minus", "minus five degrees"),
    ("num-negative-word", "negative", "negative three"),
    ("num-plus", "plus", "two plus two"),
    # --- ordinals ---------------------------------------------------------------------
    ("ord-first", "first", "the first time"),
    ("ord-second", "second", "the second one"),
    ("ord-third", "third", "third place"),
    ("ord-fourth", "fourth", "fourth floor"),
    ("ord-twenty-first", "twenty first", "twenty first century"),
    ("ord-thirty-first", "thirty-first", "thirty-first of may"),
    ("ord-hundredth", "hundredth", "the hundredth day"),
    ("ord-thousandth", "thousandth", "the thousandth time"),
    ("ord-digits-1st", "1st", "the 1st of May"),
    ("ord-digits-2nd", "2nd", "the 2nd floor"),
    ("ord-digits-3rd", "3rd", "the 3rd time"),
    ("ord-digits-21st", "21st", "the 21st century"),
    ("ord-digits-112th", "112th", "the 112th street"),
    # --- digits -----------------------------------------------------------------------
    ("digits-plain", "plain digits", "I have 3 cats"),
    ("digits-thousands-comma", "a thousands separator", "1,000 people"),
    ("digits-thousands-comma-big", "bigger", "1,234,567 people"),
    ("digits-decimal", "a decimal", "pi is 3.14"),
    ("digits-decimal-lead", "leading decimal point", ".5 percent"),
    ("digits-trailing-dot", "a number ending a sentence", "it costs 5."),
    ("digits-phone", "a phone number", "call 555-1212"),
    ("digits-time", "a time", "at 10:30 tomorrow"),
    ("digits-time-ampm", "a time with am", "at 10:30am"),
    ("digits-time-oclock", "o'clock", "at ten o'clock"),
    ("digits-date-slash", "a date with slashes", "on 12/25/2020"),
    ("digits-ranges", "a range", "pages 10-20"),
    ("digits-with-letters", "digits with a letter suffix", "a 4k screen and 5g"),
    ("digits-k-suffix", "k suffix", "5k people"),
    ("digits-m-suffix", "m suffix", "2m dollars"),
    ("digits-b-suffix", "b suffix", "3b parameters"),
    ("digits-km", "kilometres", "10 km away"),
    ("digits-mixed", "digits and number words", "3 hundred and 5"),
    ("digits-zero-lead", "leading zero", "007 is a number"),
    ("digits-percent", "percent sign", "50% of them"),
    ("digits-percent-word", "percent word", "fifty percent of them"),
    ("digits-per-cent", "per cent", "ten per cent"),
    # --- currency ---------------------------------------------------------------------
    ("cur-dollar-sign", "dollar sign", "it costs $5"),
    ("cur-dollar-decimal", "dollars and cents as digits", "$5.50 please"),
    ("cur-dollar-thousands", "dollars with a comma", "$1,000 dollars"),
    ("cur-dollar-words", "dollars spelled", "five dollars"),
    ("cur-dollars-and-cents", "dollars and cents spelled", "five dollars and fifty cents"),
    ("cur-dollar-singular", "one dollar", "one dollar"),
    ("cur-cents", "cents spelled", "fifty cents"),
    ("cur-pound-sign", "pound sign", "it costs £5"),
    ("cur-pound-decimal", "pound with pence", "£5.50 only"),
    ("cur-pounds-words", "pounds spelled", "five pounds and fifty pence"),
    ("cur-euro-sign", "euro sign", "€10 each"),
    ("cur-euros-words", "euros spelled", "ten euros"),
    ("cur-yen-sign", "yen sign", "¥500 each"),
    ("cur-million-dollars", "million dollars", "three million dollars"),
    ("cur-dollar-million-sign", "dollar sign with million", "$3 million"),
    ("cur-dollar-m-sign", "dollar sign with m", "$3m"),
    ("cur-dollar-bn", "dollar sign with bn", "$2bn budget"),
    ("cur-cent-sign", "cent sign", "50¢"),
    # --- british and american spellings -----------------------------------------------
    ("spell-colour", "colour", "the colour red"),
    ("spell-favourite", "favourite", "my favourite song"),
    ("spell-organise", "organise", "we organise events"),
    ("spell-realise", "realise", "I realise now"),
    ("spell-centre", "centre", "the city centre"),
    ("spell-theatre", "theatre", "at the theatre"),
    ("spell-grey", "grey", "a grey sky"),
    ("spell-defence", "defence", "national defence"),
    ("spell-licence", "licence", "a driving licence"),
    ("spell-travelling", "travelling", "travelling abroad"),
    ("spell-cancelled", "cancelled", "the flight was cancelled"),
    ("spell-programme", "programme", "the programme starts"),
    ("spell-tyre", "tyre", "a flat tyre"),
    ("spell-aluminium", "aluminium", "aluminium foil"),
    ("spell-mum", "mum", "my mum said"),
    ("spell-whilst", "whilst", "whilst we wait"),
    ("spell-already-american", "already american", "color center favorite"),
    # --- symbols and punctuation ------------------------------------------------------
    ("sym-ampersand", "ampersand", "salt & pepper"),
    ("sym-at", "at sign", "email me @ home"),
    ("sym-hash", "hash", "number #5"),
    ("sym-plus-sign", "plus sign", "2+2"),
    ("sym-equals", "equals", "2 = 2"),
    ("sym-slash", "slash", "and/or"),
    ("sym-hyphen-word", "hyphenated word", "well-known facts"),
    ("sym-em-dash", "em dash", "wait—what"),
    ("sym-ellipsis", "ellipsis", "well… maybe"),
    ("sym-three-dots", "three dots", "well... maybe"),
    ("sym-semicolon-colon", "semicolon and colon", "yes; no: maybe"),
    ("sym-exclaim-question", "! and ?", "what?! really!"),
    ("sym-underscore", "underscore", "snake_case name"),
    ("sym-tilde-caret", "tilde and caret", "~5 ^2"),
    ("sym-degree", "degree sign", "20° outside"),
    ("sym-copyright", "copyright", "© 2020"),
    ("sym-guillemets", "guillemets", "«bonjour»"),
    # --- accents, scripts, emoji ------------------------------------------------------
    ("acc-cafe", "accented e", "café au lait"),
    ("acc-naive", "diaeresis", "naïve idea"),
    ("acc-zoe", "name with diaeresis", "Zoë said hi"),
    ("acc-senor", "tilde n", "señor García"),
    ("acc-combining", "combining accent", "café time"),
    ("acc-ligature", "ligature", "coöperate and æsthetic"),
    ("acc-sharp-s", "sharp s", "Straße"),
    ("acc-fullwidth", "full-width letters", "Ｈｅｌｌｏ"),
    ("script-cjk", "CJK passes through", "你好 world"),
    ("script-cyrillic", "Cyrillic", "привет mir"),
    ("script-arabic", "Arabic", "مرحبا hello"),
    ("emoji-simple", "emoji", "great job \U0001F44D"),
    ("emoji-zwj", "zero-width joiner sequence", "family \U0001F468‍\U0001F469‍\U0001F467"),
    # --- supplementary-plane letters and digits next to word-boundary rules ----------------
    # Found by an independent differential test: a lookbehind that steps back one UTF-16 unit
    # sees a lone low surrogate after an astral letter, so \b is wrong before um / mr / st.
    ("astral-math-script-um", "an astral letter before a hesitation", "\U0001D49Cum"),
    ("astral-math-bold-mr", "an astral letter before a title", "\U0001D400mr"),
    ("astral-cjk-extb-um", "a CJK Extension B ideograph before a hesitation", "\U00020000um"),
    ("astral-math-digit-um", "an astral digit before a hesitation", "\U0001D7CFum"),
    ("astral-math-digit-num", "an astral digit before a number word", "\U0001D7CFone"),
    ("astral-then-space-um", "an astral letter, then a space, then a hesitation", "\U0001D49C um"),
    ("astral-after-um", "a hesitation, then an astral letter", "um\U0001D49C"),
    ("astral-between", "astral letters on both sides", "\U0001D49Cum\U0001D49C"),
    ("astral-mixed-sentence", "an astral letter inside a sentence", "see \U0001D49Cmr smith um today"),
    ("astral-deseret", "Deseret letters", "\U00010400um \U00010428st"),
    ("sym-dollar-percent", "symbols that normalise to a lone space", "$%"),
    ("sym-pound-percent", "pound sign and percent", "\u00a3%"),
    ("sym-cent-percent", "cent sign and percent", "\u00a2%"),
    ("space-nbsp", "a no-break space between words", "a\u00a0b"),
    ("space-ideographic", "an ideographic space between words", "a\u3000b"),
    ("space-line-separator", "a line separator", "a\u2028b"),
    # --- real-looking dictation -------------------------------------------------------
    ("dict-email", "an email address spoken", "send it to john dot smith at example dot com"),
    ("dict-url", "a url", "go to www.example.com/path?x=1"),
    ("dict-code", "code spoken", "open paren x close paren"),
    ("dict-meeting", "a meeting sentence", "Let's meet on Tuesday the 3rd at 2:30 p.m. in room 4B."),
    ("dict-money", "a money sentence", "The total is $1,250.75, not £1,000."),
    ("dict-list", "a list", "First, buy milk; second, buy eggs; third, call Dr. Patel."),
    ("dict-long", "a longer paragraph",
     "So um, I was thinking that, you know, we could, uh, push the release to the twenty-first "
     "of March, which is roughly three and a half weeks from now, and that would give us about "
     "one hundred and fifty hours of testing at $45 an hour."),
    ("dict-question", "a question", "Did you see Mr. O'Brien's colour proofs yesterday?"),
    ("dict-numbers-in-words", "numbers in running prose",
     "There were twenty five people, thirty two chairs and one hundred and one dalmatians."),
]

# Pools for the seeded block: realistic fragments, composed at random. Numbers come in spelled
# and digit forms because the number normaliser is where a port is most likely to diverge.
_WORDS = ("the a an of to in on at for with from by and or but not so then also very quite "
          "really just still never always often today tomorrow yesterday here there where when "
          "who what which why how people team meeting report budget plan release version "
          "customer server file project deadline review change update model test result").split()
_SPELLED = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
            "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
            "eighty ninety hundred thousand million billion first second third fourth fifth "
            "sixth seventh eighth ninth tenth eleventh twelfth twentieth thirtieth hundredth "
            "half quarter dozen point oh zero double triple and a").split()
_DIGITS = ["0", "1", "7", "10", "12", "19", "21", "42", "99", "100", "101", "250", "1,000",
           "2,500", "10,000", "3.5", "0.25", "99.9", "1st", "2nd", "3rd", "4th", "11th",
           "21st", "100th", "5k", "2m", "7b", "1990s", "80s", "10:30", "9:05", "12/25/2020",
           "555-1234", "$5", "$5.50", "$1,000", "$3m", "£5", "£1.50", "€20",
           "50%", "3.5%", "1/2", "3/4", "2x"]
_PUNCT = [",", ".", "?", "!", ";", ":", " -", " --", "...", "", "", "", ""]
_FILLERS = ["um", "uh", "hmm", "mm", "mhm", "[noise]", "(laughs)", "[inaudible]"]
_TITLES = ["Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "St.", "Jr.", "Sr."]
_CONTRACTIONS = ["don't", "can't", "won't", "I'm", "it's", "that's", "they're", "we've", "you'll",
                 "I'd", "isn't", "wouldn't", "John's", "the dogs'", "ma'am", "o'clock", "y'all"]


def _random_cases(normalizer, count: int) -> list[tuple[str, str, str]]:
    rng = random.Random(SEED)
    spellings = sorted(normalizer.standardize_spellings.mapping)
    out: list[tuple[str, str, str]] = []
    for i in range(count):
        parts: list[str] = []
        for _ in range(rng.randint(3, 14)):
            r = rng.random()
            if r < 0.30:
                parts.append(rng.choice(_WORDS))
            elif r < 0.50:
                parts.append(" ".join(rng.choice(_SPELLED) for _ in range(rng.randint(1, 5))))
            elif r < 0.62:
                parts.append(rng.choice(_DIGITS))
            elif r < 0.70:
                parts.append(rng.choice(spellings))
            elif r < 0.78:
                parts.append(rng.choice(_CONTRACTIONS))
            elif r < 0.84:
                parts.append(rng.choice(_TITLES))
            elif r < 0.90:
                parts.append(rng.choice(_FILLERS))
            else:
                parts.append(rng.choice(["dollars", "cents", "pounds", "euros", "percent",
                                         "per cent", "o'clock", "a.m.", "p.m.", "k", "m", "bn"]))
            if rng.random() < 0.25:
                parts[-1] += rng.choice(_PUNCT)
        text = " ".join(parts)
        if rng.random() < 0.3:
            text = text[:1].upper() + text[1:]
        out.append((f"random-{i:03d}", f"seeded random sentence {i}", text))
    return out


def build() -> dict:
    """The whole file as data. Requires ``whisper_normalizer`` (the ``benchmark`` group)."""
    import importlib.metadata as md

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the package ships a SyntaxWarning in basic.py
        from whisper_normalizer.english import EnglishTextNormalizer

    normalizer = EnglishTextNormalizer()
    rows = list(HAND) + _random_cases(normalizer, 400)
    seen: set[str] = set()
    cases = []
    for case_id, description, text in rows:
        assert case_id == case_id.lower() and case_id not in seen, f"bad or duplicate id {case_id!r}"
        seen.add(case_id)
        cases.append({"id": case_id, "description": description, "input": text,
                      "expected": normalizer(text)})
    return {
        "unit": "bench.wer_normalizer",
        "purpose": ("Replay target for the Kotlin port of Whisper's English text normaliser "
                    "(android :core:bench). Generated, frozen test data; not a contract/ family."),
        "oracle": {"package": "whisper-normalizer", "version": md.version("whisper-normalizer"),
                   "class": "whisper_normalizer.english.EnglishTextNormalizer"},
        "seed": SEED,
        "cases": cases,
    }


def build_spelling() -> str:
    """The oracle's British->American mapping as sorted ``british<TAB>american`` lines."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from whisper_normalizer.english import EnglishTextNormalizer

    mapping = EnglishTextNormalizer().standardize_spellings.mapping
    lines = []
    for british in sorted(mapping):
        american = mapping[british]
        for field in (british, american):
            assert field and "\t" not in field and "\n" not in field and field == field.strip(), field
        lines.append(f"{british}\t{american}")
    return "\n".join(lines) + "\n"


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed file differs")
    args = ap.parse_args(argv)
    try:
        outputs = [(OUT, render(build())), (SPELLING_OUT, build_spelling())]
    except ModuleNotFoundError as exc:
        print(f"{exc}. Install the oracle: uv sync --group benchmark", file=sys.stderr)
        return 2
    if args.check:
        stale = [p for p, text in outputs
                 if (p.read_text(encoding="utf-8") if p.exists() else "") != text]
        for p in stale:
            print(f"{p.relative_to(ROOT)} is out of date; run this script without --check.",
                  file=sys.stderr)
        if stale:
            return 1
        for p, text in outputs:
            print(f"{p.relative_to(ROOT)} is current ({len(text.splitlines())} lines).")
        return 0
    for p, text in outputs:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
