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
 * WER and CER by Levenshtein distance over normalised tokens.
 *
 * Mirrors the desktop: WER is jiwer-style word edit distance (paper/benchmark/bench_wer.py:35,227),
 * CER is per code point over the zh-eval-v1 view with whitespace and punctuation removed
 * (paper/benchmark/mandarin_metrics.py:69-71, :140, :186-190).
 *
 * Deliberate simplification: the desktop WER normalises with whisper_normalizer's
 * EnglishTextNormalizer (bench_wer.py:36). This port lowercases, drops Unicode punctuation and
 * collapses whitespace. It is NOT the same normaliser, so WER here is not a drop-in replacement
 * for a desktop number until the normaliser is ported and checked against shared vectors.
 */
object Wer {

    /** NFC, lowercase, punctuation removed, whitespace collapsed. */
    fun normalise(text: String): String {
        val nfc = Normalizer.normalize(text, Normalizer.Form.NFC).lowercase(Locale.ROOT)
        val sb = StringBuilder(nfc.length)
        nfc.codePoints().forEach { cp ->
            when {
                isPunctuation(Character.getType(cp)) -> sb.append(' ')
                else -> sb.appendCodePoint(cp)
            }
        }
        return sb.toString().trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")
    }

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

    fun wer(reference: String, hypothesis: String): ErrorRate {
        val ref = wordTokens(normalise(reference))
        val hyp = wordTokens(normalise(hypothesis))
        return ErrorRate(editDistance(ref, hyp), ref.size)
    }

    fun cer(reference: String, hypothesis: String): ErrorRate {
        val ref = charTokens(reference)
        val hyp = charTokens(hypothesis)
        return ErrorRate(editDistance(ref, hyp), ref.size)
    }

    /**
     * Corpus WER: total errors over total reference tokens. Pairs with an empty reference are
     * skipped, as bench_wer.py:223-224 does (`if r.strip()`).
     */
    fun corpusWer(pairs: List<Pair<String, String>>): ErrorRate =
        pairs.filter { normalise(it.first).isNotEmpty() }
            .fold(ErrorRate.ZERO) { acc, (r, h) -> acc + wer(r, h) }

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
        cp in 0x20000..0x2A6DF    // CJK Ext B
}
