package com.yazses.core.postprocess

/**
 * Closing punctuation that hugs the preceding word and is never given a leading
 * space. Opening delimiters are deliberately absent: a new clause starting with
 * a quote or a bracket still wants one.
 */
private const val NO_LEADING_SPACE_BEFORE = ".,!?;:)]}…%"

/**
 * The separator to prepend before injecting [text] as a continuation.
 *
 * Each hold-to-talk burst is injected independently after trimming, so without a
 * separator consecutive bursts glue together: "words together" + "I mean" becomes
 * "words togetherI mean".
 *
 * Returns a single space when this burst continues a recent one, and "" for the
 * first burst, for empty text, or before closing punctuation.
 */
public fun continuationPrefix(text: String, hadRecentInjection: Boolean): String {
    if (!hadRecentInjection || text.isEmpty()) return ""
    if (text[0] in NO_LEADING_SPACE_BEFORE) return ""
    return " "
}
