/*
 * Ported from whisper-normalizer 0.1.15 (https://github.com/kurianbenoy/whisper_normalizer),
 * the MIT-licensed package whose English text normaliser this file ports line by line. The
 * package's source comments credit OpenAI Whisper's text normaliser
 * (https://github.com/openai/whisper/tree/main/whisper/normalizers) as the origin of the algorithm.
 *
 * The package's LICENSE, reproduced verbatim:
 *
 * MIT License
 *
 * Copyright (c) 2023 Kurian Benoy
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
package com.yazses.core.bench

/**
 * Whisper's English text normaliser: the same rules the desktop benchmark applies to WER
 * (benchmark/bench_wer.py uses whisper_normalizer.english.EnglishTextNormalizer), so a WER
 * measured on a phone is computed on the same text. Output is lower-case, space-separated, with
 * numbers written as digits and British spellings replaced by American ones.
 *
 * For ordinary English text the port matches the oracle exactly: all 614 vectors generated from the
 * package pass, and an independent differential review of about 250,000 inputs found no mismatch
 * outside the Unicode bucket below.
 *
 * The one documented difference is the age of the Unicode tables. The JDK 17 toolchain has Unicode 13;
 * CPython 3.14 (the oracle) has Unicode 16. They differ on 11,141 code points: 11,139 unassigned in
 * Unicode 13, plus U+1734 and U+1171E, which were reclassified. For those code points:
 * - letters (about 9,787) are not word characters, so `\b` is wrong beside `um`, `mr` and the like;
 * - about 110 decimal digits are not digits;
 * - about 950 symbols and 208 marks are kept where Python drops them, and 59 punctuation marks are kept
 *   where Python makes them spaces;
 * - emoji from as early as Unicode 14 (for example U+1F979) are kept.
 * On Android the normaliser runs on the operating system's tables, which vary by version; that is not
 * tested. The desktop result also depends on the Unicode version of the Python that runs it.
 *
 * Two more differences:
 * - The `\s+'` rule takes time quadratic in the length of a whitespace run, in both implementations. The
 *   Kotlin port is about 20 times slower in that pathological case (20,000 spaces: about 15 s against
 *   about 0.7 s in Python). Realistic text is linear, about 18 ms per 1,000 characters.
 * - CPython raises AssertionError on a digit token longer than 4,300 characters (its integer conversion
 *   limit). The port returns the text instead.
 */
object EnglishTextNormalizer {

    private val numbers: EnglishNumberNormalizer by lazy { EnglishNumberNormalizer() }
    private val spellings: EnglishSpellingNormalizer by lazy { EnglishSpellingNormalizer() }

    private val BRACKETS = Regex("[<\\[][^>\\]]*[>\\]]")
    private val PARENTHESES = Regex("\\(([^)]+?)\\)")
    private val FILLERS = Regex("${PY_B}(hmm|mm|mhm|mmm|uh|um)$PY_B")
    private val SPACE_BEFORE_APOSTROPHE = Regex("$PY_WS+'")
    private val DIGIT_COMMA_DIGIT = Regex("(\\p{Nd}),(\\p{Nd})")
    private val PERIOD_NOT_NUMBER = Regex("\\.([^0-9]|$PY_DOLLAR)")
    private val PREFIX_SYMBOL = Regex("[.$¢€£]([^0-9])")
    private val SUFFIX_PERCENT = Regex("([^0-9])%")
    private val WHITESPACE = Regex("$PY_WS+")

    /** Python `\bX\b`. */
    private fun word(x: String) = "$PY_B$x$PY_B"

    /** Python `X\b`. */
    private fun wordEnd(x: String) = "$x$PY_B"

    /** The oracle's `self.replacers`, in the same order (order matters: first match wins per pattern). */
    private val REPLACERS: List<Pair<Regex, String>> = listOf(
        // common contractions
        word("won't") to "will not",
        word("can't") to "can not",
        word("let's") to "let us",
        word("ain't") to "aint",
        word("y'all") to "you all",
        word("wanna") to "want to",
        word("kinda") to "kind of",
        word("sorta") to "sort of",
        word("dunno") to "do not know",
        word("gotta") to "got to",
        word("gonna") to "going to",
        word("i'ma") to "i am going to",
        word("imma") to "i am going to",
        word("woulda") to "would have",
        word("coulda") to "could have",
        word("shoulda") to "should have",
        word("cause") to "because",
        word("ma'am") to "madam",
        // contractions in titles/prefixes
        word("mr") to "mister ",
        word("mrs") to "missus ",
        word("st") to "saint ",
        word("dr") to "doctor ",
        word("prof") to "professor ",
        word("capt") to "captain ",
        word("gov") to "governor ",
        word("ald") to "alderman ",
        word("gen") to "general ",
        word("sen") to "senator ",
        word("rep") to "representative ",
        word("pres") to "president ",
        word("rev") to "reverend ",
        word("hon") to "honorable ",
        word("asst") to "assistant ",
        word("assoc") to "associate ",
        word("lt") to "lieutenant ",
        word("col") to "colonel ",
        word("jr") to "junior ",
        word("sr") to "senior ",
        word("esq") to "esquire ",
        // prefect tenses, ideally it should be any past participles, but it's harder..
        wordEnd("'d been") to " had been",
        wordEnd("'s been") to " has been",
        wordEnd("'d gone") to " had gone",
        wordEnd("'s gone") to " has gone",
        wordEnd("'d done") to " had done", // "'s done" is ambiguous
        wordEnd("'s got") to " has got",
        // general contractions
        wordEnd("n't") to " not",
        wordEnd("'re") to " are",
        wordEnd("'s") to " is",
        wordEnd("'d") to " would",
        wordEnd("'ll") to " will",
        wordEnd("'t") to " not",
        wordEnd("'ve") to " have",
        wordEnd("'m") to " am",
    ).map { (pattern, replacement) -> Regex(pattern) to replacement }

    /**
     * Normalises [text] exactly as the oracle's `EnglishTextNormalizer.__call__` does.
     * Steps: lower-case; drop bracketed and parenthesised text; drop fillers; close the gap before an
     * apostrophe; expand contractions and titles; drop commas between digits; drop periods not
     * followed by a digit; remove symbols and diacritics (keeping . % $ ¢ € £); spell numbers as
     * digits; apply the British-to-American table; drop symbols left next to no number; collapse
     * whitespace.
     */
    fun normalize(text: String): String {
        var s = pyLower(text)

        s = BRACKETS.replace(s, "")                       // remove words between brackets
        s = PARENTHESES.replace(s, "")                    // remove words between parenthesis
        s = FILLERS.replace(s, "")
        s = SPACE_BEFORE_APOSTROPHE.replace(s, "'")       // when there's a space before an apostrophe

        for ((pattern, replacement) in REPLACERS) {
            s = pattern.replace(s, replacement)
        }

        s = DIGIT_COMMA_DIGIT.replace(s, "$1$2")          // remove commas between digits
        s = PERIOD_NOT_NUMBER.replace(s, " $1")           // remove periods not followed by numbers
        s = removeSymbolsAndDiacritics(s, keep = ".%$¢€£") // keep numeric symbols

        s = numbers.normalize(s)
        s = spellings.normalize(s)

        // now remove prefix/suffix symbols that are not preceded/followed by numbers
        s = PREFIX_SYMBOL.replace(s, " $1")
        s = SUFFIX_PERCENT.replace(s, "$1 ")

        s = WHITESPACE.replace(s, " ")                    // replace any successive whitespaces with a space
        return s
    }
}
