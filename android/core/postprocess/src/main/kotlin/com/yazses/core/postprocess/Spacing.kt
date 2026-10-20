package com.yazses.core.postprocess

/**
 * Closing punctuation that hugs the preceding word and is never given a leading
 * space. Opening delimiters are deliberately absent: a new clause starting with
 * a quote, a bracket or U+00AB « still wants one.
 *
 * Script-aware since contract 7.0.0 (#551): the Persian closing marks U+060C ،,
 * U+061F ؟ and U+061B ؛ and the closing guillemet U+00BB » hug the word exactly
 * like their Latin cousins. Written as escapes so the set survives any editor.
 */
private const val NO_LEADING_SPACE_BEFORE = ".,!?;:)]}\u2026%\u060C\u061F\u061B\u00BB"

/**
 * The first code point of [text] that is not an invisible format character
 * (Unicode category Cf: ZWNJ, ZWJ, the bidi controls, the Arabic letter mark,
 * the byte-order mark), or -1 if there is none.
 *
 * A character the user cannot see cannot carry the "this burst opens with closing
 * punctuation" decision, so the probe walks past it — in either direction: a
 * leading ZWNJ no longer hides a comma from the rule, and no longer suppresses the
 * space in front of a word. Walks code points, not chars, to match the Python
 * reference, which iterates code points.
 */
private fun firstVisibleCodePoint(text: String): Int {
    var i = 0
    while (i < text.length) {
        val cp = text.codePointAt(i)
        if (Character.getType(cp) != Character.FORMAT.toInt()) return cp
        i += Character.charCount(cp)
    }
    return -1
}

/**
 * The separator to prepend before injecting [text] as a continuation.
 *
 * Each hold-to-talk burst is injected independently after trimming, so without a
 * separator consecutive bursts glue together: "words together" + "I mean" becomes
 * "words togetherI mean".
 *
 * Returns a single space when this burst continues a recent one, and "" for the
 * first burst, for empty text, or when its first *visible* character is closing
 * punctuation or any CJK punctuation mark (contract 7.1.0, #501: a full-width mark
 * carries its own spacing, opening ones included).
 *
 * [previousTail] is the last character the previous burst typed, or "" when it is
 * not known. When given, the seam is judged from both sides by [needsSpace]: two Han
 * clauses take no space between them. "" reproduces the pre-7.1.0 answer exactly.
 */
public fun continuationPrefix(
    text: String,
    hadRecentInjection: Boolean,
    previousTail: String = "",
): String {
    if (!hadRecentInjection || text.isEmpty()) return ""
    val first = firstVisibleCodePoint(text)
    if (first in 0..0xFFFF && first.toChar() in NO_LEADING_SPACE_BEFORE) return ""
    if (first >= 0 && isCjkPunct(first)) return ""
    if (previousTail.isNotEmpty() && first >= 0) {
        val tail = previousTail.codePointBefore(previousTail.length)
        if (!needsSpace(tail, first)) return ""
    }
    return " "
}
