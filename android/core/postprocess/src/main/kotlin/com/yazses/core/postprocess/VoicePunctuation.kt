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
 *
 * Whisper punctuates the spoken mark *as a word* ("Hello, comma, world period."), so the
 * decoder's mark glued to the phrase's end is dropped, and a pause mark (or the very
 * symbol being inserted) directly before it is replaced. The spoken mark wins. Any other
 * sentence mark before the phrase is kept.
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

/** Punctuation a recogniser puts around a spoken mark it heard as a word. */
private const val ASR_MARK = "[,.;:!?]"

/** The pause marks a spoken mark may replace when they come right before it. */
private val PAUSE_MARKS = setOf(",", ";", ":")

// Spaces only: "tab key tab key" is two deliberate tabs, not a run to squash.
private val DOUBLED_SPACES = Regex(""" {2,}""")

private val SYMBOL_FOR: Map<String, String> = ATTACH_LEFT.toMap()

/** Group 1 is the decoder's mark before the phrase, if any; group 2 is the spoken phrase. */
private val ATTACH_PATTERN = Regex(
    """($ASR_MARK)?\s*\b(${ATTACH_LEFT.joinToString("|") { Regex.escape(it.first) }})\b$ASR_MARK*""",
    RegexOption.IGNORE_CASE,
)

private val FORMATTING_PATTERNS: List<Pair<Regex, String>> = FORMATTING.map { (phrase, replacement) ->
    Regex("""\s*\b${Regex.escape(phrase)}\b$ASR_MARK*\s*""", RegexOption.IGNORE_CASE) to replacement
}

private fun attach(match: MatchResult): String {
    // A case-insensitive match that lowercases to no known phrase is left as spoken.
    val symbol = SYMBOL_FOR[match.groupValues[2].lowercase()] ?: return match.value
    val before = match.groupValues[1]
    return if (before in PAUSE_MARKS || before == symbol) symbol else before + symbol
}

/** Replace spoken punctuation and formatting words with their symbols. */
public fun applyVoicePunctuation(text: String): String {
    if (text.isEmpty()) return text
    var s = text
    // Formatting absorbs the whitespace on both sides: the newline IS the break.
    for ((pattern, replacement) in FORMATTING_PATTERNS) {
        s = pattern.replace(s) { replacement }
    }
    // One pass for every mark, so a symbol just inserted is never mistaken for decoder
    // punctuation and absorbed by the next phrase ("a comma period" -> "a,.").
    // The symbol hugs the previous word; whatever follows (usually a space) survives.
    s = ATTACH_PATTERN.replace(s) { attach(it) }
    return DOUBLED_SPACES.replace(s, " ")
}
