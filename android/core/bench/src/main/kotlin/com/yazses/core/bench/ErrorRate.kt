package com.yazses.core.bench

import java.text.Normalizer
import java.util.Locale

/** Edit errors against a reference of [refLength] tokens. [rate] is null when the reference is empty. */
data class ErrorRate(val errors: Int, val refLength: Int) {
    val rate: Double? get() = if (refLength > 0) errors.toDouble() / refLength else null

    operator fun plus(other: ErrorRate) = ErrorRate(errors + other.errors, refLength + other.refLength)

    companion object {
        val ZERO = ErrorRate(0, 0)
    }
}

/**
 * Which text normaliser runs before WER is counted.
 *
 * [SIMPLE] is this module's own rule (see [Wer.normalise]). It is the default so existing callers keep
 * their numbers. It is NOT comparable with the desktop benchmark.
 *
 * [WHISPER_ENGLISH] is [EnglishTextNormalizer], a port of the whisper-normalizer package that the
 * desktop benchmark uses (paper/benchmark/bench_wer.py:36). WER computed with it on English text is
 * comparable with the desktop benchmark's. It is verified against the package's own outputs
 * (EnglishTextNormalizerVectorsTest, 598 of 598). Known difference: a character assigned after the
 * JDK's Unicode version (13 on the JDK 17 toolchain) is treated as unassigned, so a symbol added
 * later, such as a recent emoji, is kept where the desktop drops it. See [EnglishTextNormalizer].
 */
enum class TextNormalizer { SIMPLE, WHISPER_ENGLISH }

/**
 * WER and CER by Levenshtein distance over normalised tokens.
 *
 * Mirrors the desktop: WER is jiwer-style word edit distance (paper/benchmark/bench_wer.py:35,227),
 * CER is per code point over the zh-eval-v1 view with whitespace and punctuation removed
 * (paper/benchmark/mandarin_metrics.py:69-71, :140, :186-190).
 *
 * WER takes a [TextNormalizer]. Pass [TextNormalizer.WHISPER_ENGLISH] to match the desktop
 * benchmark's English WER. The default, [TextNormalizer.SIMPLE], is this module's own rule and is
 * not comparable with the desktop's. CER does not normalise this way and is unaffected.
 */
object Wer {

    /**
     * [TextNormalizer.SIMPLE] normalises text to space-separated tokens. Rule, applied to the NFC,
     * lowercased code points:
     * 1. An apostrophe (U+0027, U+2019) is deleted with no space, so "don't" and "dont" match.
     * 2. A period, comma or hyphen (U+002D, U+2010, U+2011) directly between two letters or digits
     *    is deleted, so "e-mail" is one token and "U.S." is "us". The exception is a period or
     *    comma between two DIGITS, which is kept, so "3.5" and "1,000" stay distinct from "35"
     *    and "1000".
     * 3. Any other Unicode punctuation becomes a space, which separates words.
     * 4. Whitespace is collapsed. CJK is not split here; see [wordTokens].
     *
     * Limits: a sentence written without a space after its period ("end.Next") joins into one
     * token, and a list like "1,2,3" keeps its commas. Rule 1
     * deletes every apostrophe, including a quotation mark, so 'hello' and hello are one token.
     *
     * [TextNormalizer.WHISPER_ENGLISH] applies [EnglishTextNormalizer] instead, then the same
     * whitespace split as below.
     */
    fun normalise(text: String, normalizer: TextNormalizer = TextNormalizer.SIMPLE): String =
        when (normalizer) {
            TextNormalizer.SIMPLE -> simpleNormalise(text)
            TextNormalizer.WHISPER_ENGLISH -> EnglishTextNormalizer.normalize(text)
        }

    private fun simpleNormalise(text: String): String {
        val nfc = Normalizer.normalize(text, Normalizer.Form.NFC).lowercase(Locale.ROOT)
        val cps = nfc.codePoints().toArray()
        val sb = StringBuilder(nfc.length)
        for (i in cps.indices) {
            val cp = cps[i]
            when {
                cp in APOSTROPHES -> Unit
                cp in DIGIT_SEPARATORS && i > 0 && i < cps.lastIndex &&
                    Character.isDigit(cps[i - 1]) && Character.isDigit(cps[i + 1]) -> sb.appendCodePoint(cp)
                cp in JOINERS && i > 0 && i < cps.lastIndex &&
                    isAlnum(cps[i - 1]) && isAlnum(cps[i + 1]) -> Unit
                isPunctuation(Character.getType(cp)) -> sb.append(' ')
                else -> sb.appendCodePoint(cp)
            }
        }
        return sb.toString().trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")
    }

    private val APOSTROPHES = setOf(0x27, 0x2019)
    private val DIGIT_SEPARATORS = setOf('.'.code, ','.code)
    private val JOINERS = setOf('.'.code, ','.code, '-'.code, 0x2010, 0x2011)

    private fun isAlnum(cp: Int): Boolean = Character.isLetterOrDigit(cp)

    /** Word tokens. Each CJK character is its own token, so a Chinese/Japanese WER counts characters. */
    fun wordTokens(normalised: String): List<String> {
        val out = mutableListOf<String>()
        val run = StringBuilder()
        fun flush() {
            if (run.isNotEmpty()) { out += run.toString(); run.setLength(0) }
        }
        normalised.codePoints().forEach { cp ->
            when {
                cp == ' '.code -> flush()
                isCjk(cp) -> { flush(); out += String(Character.toChars(cp)) }
                else -> run.appendCodePoint(cp)
            }
        }
        flush()
        return out
    }

    /** Code points with whitespace and punctuation removed (zh-eval-v1 view, mandarin_metrics.py). */
    fun charTokens(text: String): List<String> {
        val out = mutableListOf<String>()
        Normalizer.normalize(text, Normalizer.Form.NFC).codePoints().forEach { cp ->
            if (!Character.isWhitespace(cp) && !isPunctuation(Character.getType(cp))) {
                out += String(Character.toChars(cp))
            }
        }
        return out
    }

    fun wer(
        reference: String,
        hypothesis: String,
        normalizer: TextNormalizer = TextNormalizer.SIMPLE,
    ): ErrorRate {
        val ref = wordTokens(normalise(reference, normalizer))
        val hyp = wordTokens(normalise(hypothesis, normalizer))
        return ErrorRate(editDistance(ref, hyp), ref.size)
    }

    fun cer(reference: String, hypothesis: String): ErrorRate {
        val ref = charTokens(reference)
        val hyp = charTokens(hypothesis)
        return ErrorRate(editDistance(ref, hyp), ref.size)
    }

    /**
     * Corpus WER: total errors over total reference tokens. Pairs with an empty reference are
     * skipped, as bench_wer.py:223-224 does (`if r.strip()`), after normalisation as there.
     */
    fun corpusWer(
        pairs: List<Pair<String, String>>,
        normalizer: TextNormalizer = TextNormalizer.SIMPLE,
    ): ErrorRate =
        pairs.filter { normalise(it.first, normalizer).isNotEmpty() }
            .fold(ErrorRate.ZERO) { acc, (r, h) -> acc + wer(r, h, normalizer) }

    fun editDistance(a: List<String>, b: List<String>): Int {
        if (a.isEmpty()) return b.size
        if (b.isEmpty()) return a.size
        var prev = IntArray(b.size + 1) { it }
        var curr = IntArray(b.size + 1)
        for (i in 1..a.size) {
            curr[0] = i
            for (j in 1..b.size) {
                val cost = if (a[i - 1] == b[j - 1]) 0 else 1
                curr[j] = minOf(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            }
            val tmp = prev; prev = curr; curr = tmp
        }
        return prev[b.size]
    }

    private fun isPunctuation(type: Int): Boolean = type in PUNCTUATION_TYPES

    private val PUNCTUATION_TYPES = setOf(
        Character.CONNECTOR_PUNCTUATION.toInt(), Character.DASH_PUNCTUATION.toInt(),
        Character.START_PUNCTUATION.toInt(), Character.END_PUNCTUATION.toInt(),
        Character.INITIAL_QUOTE_PUNCTUATION.toInt(), Character.FINAL_QUOTE_PUNCTUATION.toInt(),
        Character.OTHER_PUNCTUATION.toInt(),
    )

    /**
     * Han, kana: scripts written without spaces between words, so each character is a token.
     * Hangul is excluded on purpose: Korean is space-delimited, so its WER is word-level.
     */
    internal fun isCjk(cp: Int): Boolean =
        cp in 0x3040..0x30FF ||   // Hiragana, Katakana
        cp in 0x3400..0x4DBF ||   // CJK Ext A
        cp in 0x4E00..0x9FFF ||   // CJK Unified
        cp in 0xF900..0xFAFF ||   // CJK compatibility
        cp in 0x20000..0x2FA1F ||  // CJK Ext B-F (to 0x2EBEF) and the Compatibility Supplement
        cp in 0x30000..0x323AF    // CJK Ext G (0x30000..0x3134F) and Ext H (0x31350..0x323AF)
}
