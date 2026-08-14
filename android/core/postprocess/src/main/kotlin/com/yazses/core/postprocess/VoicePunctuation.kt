package com.yazses.core.postprocess

/**
 * Spoken punctuation and formatting words to symbols — opt-in.
 *
 * "hello comma world period" becomes "hello, world." Off by default on the
 * desktop because the words also occur in ordinary speech ("a period of time"),
 * so it is only safe for someone who has chosen it and adapted their phrasing.
 *
 * Longest phrase first within each group, so "exclamation mark" is matched before
 * any shorter phrase could claim part of it.
 */
private val FORMATTING: List<Pair<String, String>> = listOf(
    "new paragraph" to "\n\n",
    "new line" to "\n",
    "newline" to "\n",
    "tab key" to "\t",
)

/** Punctuation that attaches to the preceding word: no space before, keep after. */
private val ATTACH_LEFT: List<Pair<String, String>> = listOf(
    "full stop" to ".",
    "period" to ".",
    "question mark" to "?",
    "exclamation mark" to "!",
    "exclamation point" to "!",
    "semicolon" to ";",
    "semi colon" to ";",
    "colon" to ":",
    "comma" to ",",
)

private val DOUBLED_SPACES = Regex("""[ \t]{2,}""")

private fun phrasePattern(phrase: String, absorbTrailing: Boolean): Regex {
    val body = Regex.escape(phrase)
    val tail = if (absorbTrailing) """\s*""" else ""
    return Regex("""\s*\b$body\b$tail""", RegexOption.IGNORE_CASE)
}

/** Replace spoken punctuation and formatting words with their symbols. */
public fun applyVoicePunctuation(text: String): String {
    if (text.isEmpty()) return text
    var s = text
    // Formatting absorbs the whitespace on both sides: the newline IS the break.
    for ((phrase, replacement) in FORMATTING) {
        s = phrasePattern(phrase, absorbTrailing = true).replace(s) { replacement }
    }
    // Punctuation absorbs only what precedes it, so the symbol hugs the previous
    // word while whatever follows (usually a space) survives.
    for ((phrase, symbol) in ATTACH_LEFT) {
        s = phrasePattern(phrase, absorbTrailing = false).replace(s) { symbol }
    }
    return DOUBLED_SPACES.replace(s, " ")
}
