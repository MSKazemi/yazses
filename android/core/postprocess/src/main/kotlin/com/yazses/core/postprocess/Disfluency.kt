package com.yazses.core.postprocess

/**
 * Settings for [filterTranscript].
 *
 * Mirrors the desktop `[filters.disfluency]` section. Defaults match the desktop
 * defaults, which the contract vectors assert against when a case supplies no
 * options.
 */
public data class DisfluencyConfig(
    val enabled: Boolean = true,
    /**
     * Words removed as fillers.
     *
     * Deliberately short. `like`, `right`, `sort of`, `kind of`, `actually`,
     * `basically` and `literally` are absent: each is a genuine filler in some
     * positions and load-bearing content in others, and stripping them turns
     * hedges into facts ("it seems basically correct" is not "it seems correct").
     * Someone who wants aggressive removal adds them back.
     */
    val fillerWords: List<String> = listOf(
        "um", "uh", "er", "ah", "hmm", "you know",
        "i mean", "okay so",
        "so um", "so uh",
    ),
    val selfCorrectionTriggers: List<String> = listOf(
        "no wait", "delete that", "scratch that", "never mind",
        "forget that", "strike that",
    ),
    /** Dysfluency-Friendly Mode collapse pass; off by default. */
    val collapseRepetitions: Boolean = false,
    val collapseProlongations: Boolean = false,
    val prolongationMinRun: Int = 3,
    val repetitionMaxFragmentLen: Int = 2,
)

/** Result of the filter: the text, and how much shorter it got. */
public data class FilterResult(val text: String, val charsRemoved: Int)

private const val TRAILING_PUNCTUATION = ".,;:!?…"

/** Non-lexical hesitation sounds — never ordinary words, so safe at position 0. */
private val HESITATION_PARTICLES = setOf("um", "uh", "er", "ah", "hmm")

/**
 * Words that, immediately before a self-correction trigger, mean the speaker is
 * *talking about* the action rather than performing it.
 *
 * "Please do not delete that branch" is an instruction whose whole point is the
 * negation, and treating it as a rollback left only "branch" — the most dangerous
 * output this filter can produce, because it does not garble the meaning, it
 * inverts it. Modals do the same thing without a negation ("you should never mind
 * the warning"): they put the trigger inside a verb phrase, and a correction is an
 * interjection that never continues the clause it interrupts.
 */
private val GOVERNING_WORDS = setOf(
    "not", "don't", "dont", "doesn't", "doesnt", "didn't", "didnt",
    "won't", "wont", "can't", "cant", "cannot", "never", "no",
    "should", "would", "could", "can", "will", "shall", "must", "may", "might",
    "do", "does", "did", "to", "please", "let", "lets", "let's",
)

/**
 * The same evidence, for the two phrase types a *verb* guard cannot see.
 *
 * A determiner or possessive requires a noun head, so a trigger after one is part of
 * a noun phrase and cannot be an interjection: "the no wait policy applies to
 * walk-ins" became "policy applies to walk-ins". A reporting verb makes the trigger
 * *quoted* rather than performed — the speaker is describing a correction somebody
 * else made, so "he said never mind the cost and left" became "the cost and left". A
 * copula covers the residue where the trigger heads a predicate noun phrase and the
 * determiner sits inside the trigger itself, as in "there is no wait time at this
 * branch", where the word before "no wait" is "is".
 *
 * Demonstratives are deliberately absent: "this" and "that" are as often the *object*
 * of the preceding verb as a determiner on the trigger, and "please do this strike
 * that please do that" is a real correction a demonstrative entry would suppress.
 *
 * Kept as a second set rather than folded into [GOVERNING_WORDS] so each half stays
 * comparable to the Python constant it mirrors — the contract vectors name only one
 * of these 33 words, so vector agreement cannot be what keeps the two in step.
 */
private val PHRASE_CONTEXT_WORDS = setOf(
    // articles and possessives
    "the", "a", "an", "my", "your", "our", "their", "its", "his", "her",
    // reporting verbs — the trigger is quoted, not performed
    "said", "says", "say", "saying", "told", "tells", "tell", "asked", "asks",
    "wrote", "writes", "replied", "answered", "shouted", "yelled", "whispered",
    // copulas
    "is", "are", "was", "were", "be", "been", "being",
    // Nominative-only personal pronouns: a subject immediately before the trigger
    // makes the trigger the clause's own verb. "it" and "you" are deliberately
    // absent -- they are also objects, and a real correction turns on one of them
    // ("i think we should ship it never mind lets wait").
    "i", "we", "they", "he", "she",
)

private val DOUBLE_SPACE = Regex("""  +""")

private fun isProtected(token: String): Boolean =
    token.any { it.isUpperCase() } || '_' in token || '/' in token || '.' in token

private fun isCodeOrPathToken(token: String): Boolean {
    val core = token.trimEnd { it in TRAILING_PUNCTUATION }
    return '_' in core || '/' in core || '.' in core
}

private fun isUnambiguousFiller(filler: String): Boolean =
    filler.split(" ").any { it in HESITATION_PARTICLES }

/**
 * Three passes, then a self-correction rollback.
 *
 * Behaviour is defined by the disfluency contract vectors, not by this code. The
 * Kotlin is idiomatic rather than a transliteration of the Python (ADR-MOB-008 §4).
 */
public fun filterTranscript(text: String, config: DisfluencyConfig = DisfluencyConfig()): FilterResult {
    if (!config.enabled || text.isBlank()) return FilterResult(text, 0)

    val originalLength = text.length
    var out = removeFillers(text, config.fillerWords)
    out = dedup2Grams(out)
    out = collapseDysfluencies(out, config)
    out = applySelfCorrections(out, config.selfCorrectionTriggers)
    out = DOUBLE_SPACE.replace(out, " ").trim()

    return FilterResult(out, maxOf(0, originalLength - out.length))
}

// ---- Rule A: filler removal ------------------------------------------------

private fun dropAllFillerHyphenTokens(text: String, fillers: Set<String>): String {
    // A hyphen is a word boundary, so the regex below would otherwise reach
    // *inside* a hyphenated token and delete one part of it — turning
    // "a-a-actually" (what a stutter looks like once transcribed) into a fragment
    // glued to the next word. Destroying a stuttered word is the worst possible
    // failure for the user this filter exists to serve.
    val kept = text.split(" ").filter { token ->
        val core = token.trim { it in TRAILING_PUNCTUATION }
        if ('-' !in core) return@filter true
        val parts = core.split("-").filter { it.isNotEmpty() }
        !(parts.isNotEmpty() && parts.all { it.lowercase() in fillers })
    }
    return kept.joinToString(" ")
}

private fun removeFillers(text: String, fillerWords: List<String>): String {
    if (fillerWords.isEmpty()) return text
    val fillers = fillerWords.map { it.lowercase() }.toSet()
    val withoutHyphenFillers = dropAllFillerHyphenTokens(text, fillers)

    // Longest first so a multi-word filler matches before any single word could
    // claim part of it. The word boundaries are load-bearing: without the trailing
    // one, "like" matched the prefix of "likely" and left "ly" behind.
    //
    // The optional leading comma matters as much as the trailing one: a filler is
    // often a parenthetical ("the tests, you know, are slow"), and consuming only
    // the closing comma left "the tests, are slow" — a comma between subject and
    // verb, typed into the user's document.
    val alternation = fillerWords.sortedByDescending { it.length }.joinToString("|") { Regex.escape(it) }
    val pattern = Regex("""(?:,\s*)?\b($alternation)\b[,]?\s*""", RegexOption.IGNORE_CASE)

    var removedLeading = false
    val result = StringBuilder()
    var last = 0
    for (m in pattern.findAll(withoutHyphenFillers)) {
        val group = m.groups[1]!!.range
        val enclosing = enclosingToken(withoutHyphenFillers, group.first, group.last + 1)
        val atStart = withoutHyphenFillers.substring(0, m.range.first).isBlank()

        val keep = when {
            // Never reach inside a hyphenated token: anything still containing a
            // hyphen has at least one non-filler part, i.e. a real word.
            '-' in enclosing.trim { it in TRAILING_PUNCTUATION } -> true
            isProtected(enclosing) -> {
                // Whisper capitalises the first word, so a sentence-initial "Um"
                // trips the uppercase guard and would never be removed. Relax it
                // at position 0, and only for fillers that cannot open a sentence.
                isCodeOrPathToken(enclosing) || !atStart || !isUnambiguousFiller(m.groupValues[1].lowercase())
            }
            else -> false
        }

        result.append(withoutHyphenFillers, last, m.range.first)
        if (keep) {
            result.append(m.value)
        } else {
            if (atStart) removedLeading = true
            // When the match swallowed the parenthetical's opening comma it also
            // swallowed the space in front of it; returning nothing would glue the
            // neighbours together. The collapse at the end tidies any doubling.
            if (m.value.trimStart().startsWith(",")) result.append(' ')
        }
        last = m.range.last + 1
    }
    result.append(withoutHyphenFillers, last, withoutHyphenFillers.length)

    var out = result.toString()
    if (removedLeading) out = out.trimStart { it in TRAILING_PUNCTUATION || it == ' ' }
    if (out != withoutHyphenFillers) out = tidyOrphanedPunctuation(out)
    return out
}

private fun enclosingToken(text: String, startIn: Int, endIn: Int): String {
    var start = startIn
    var end = endIn
    while (start > 0 && !text[start - 1].isWhitespace()) start--
    while (end < text.length && !text[end].isWhitespace()) end++
    return text.substring(start, end)
}

/**
 * Repair punctuation left stranded by removing a filler.
 *
 * Only applied when the filler pass actually removed something, so text nobody
 * touched keeps whatever punctuation was dictated.
 */
private fun tidyOrphanedPunctuation(text: String): String =
    text
        .replace(Regex(""",\s*,"""), ",")
        .replace(Regex("""\s+([,;:])"""), "$1")
        .replace(Regex("""[,;:]\s*$"""), "")

// ---- Rule B: consecutive 2-gram dedup --------------------------------------

private fun dedup2Grams(text: String): String {
    var current = text
    while (true) {
        val tokens = current.split(" ").filter { it.isNotEmpty() }
        val result = mutableListOf<String>()
        var changed = false
        var i = 0
        while (i < tokens.size) {
            if (i + 3 < tokens.size &&
                tokens[i] == tokens[i + 2] &&
                tokens[i + 1] == tokens[i + 3]
            ) {
                result += tokens[i]
                result += tokens[i + 1]
                i += 4
                changed = true
            } else {
                result += tokens[i]
                i++
            }
        }
        current = result.joinToString(" ")
        if (!changed) return current
    }
}

// ---- Rule B.5: stutter / prolongation collapse (opt-in) --------------------

private fun collapseProlongations(text: String, minRun: Int): String {
    if (minRun < 2) return text
    val pattern = Regex("""([a-zA-Z])\1{${minRun - 1},}""")
    return text.split(" ").joinToString(" ") { token ->
        if (isProtected(token)) token else pattern.replace(token, "$1")
    }
}

private fun fixHyphenStutter(token: String): String {
    if ('-' !in token || isProtected(token)) return token
    val parts = token.split("-")
    if (parts.size < 3) return token
    val lead = parts.dropLast(1)
    val final = parts.last()
    val fragment = lead.first()
    val allSame = fragment.isNotEmpty() && fragment.all { it.isLetter() } && lead.all { it == fragment }
    return if (allSame && final.isNotEmpty() && final.lowercase().startsWith(fragment.lowercase())) final else token
}

private fun collapseRepetitions(text: String, maxFragmentLen: Int): String {
    val tokens = text.split(" ").filter { it.isNotEmpty() }.map(::fixHyphenStutter)
    val result = mutableListOf<String>()
    var i = 0
    while (i < tokens.size) {
        val token = tokens[i]
        // Two or more identical short fragments followed by the longer word they
        // prefix: "b b because" -> "because".
        if (token.isNotEmpty() && token.all { it.isLetter() } && !isProtected(token) && token.length <= maxFragmentLen) {
            var j = i
            while (j < tokens.size && tokens[j] == token) j++
            if (j - i >= 2 && j < tokens.size && !isProtected(tokens[j]) &&
                tokens[j].length > token.length &&
                tokens[j].lowercase().startsWith(token.lowercase())
            ) {
                result += tokens[j]
                i = j + 1
                continue
            }
        }
        // A run of three or more identical tokens collapses to one.
        if (!isProtected(token)) {
            var j = i
            while (j < tokens.size && tokens[j] == token) j++
            if (j - i >= 3) {
                result += token
                i = j
                continue
            }
        }
        result += token
        i++
    }
    return result.joinToString(" ")
}

private fun collapseDysfluencies(text: String, config: DisfluencyConfig): String {
    var out = text
    if (config.collapseRepetitions) out = collapseRepetitions(out, config.repetitionMaxFragmentLen)
    if (config.collapseProlongations) out = collapseProlongations(out, config.prolongationMinRun)
    return out
}

// ---- Rule C: self-correction rollback --------------------------------------

private fun triggerIsGoverned(lower: String, idx: Int): Boolean {
    val before = lower.substring(0, idx).trimEnd(' ', ',')
    if (before.isEmpty()) return false
    val preceding = before.substringAfterLast(' ')
    return preceding in GOVERNING_WORDS || preceding in PHRASE_CONTEXT_WORDS
}

/**
 * True when something precedes the trigger for it to correct.
 *
 * A self-correction replaces what was just said, so a trigger with nothing in
 * front of it cannot be one — it is a sentence starting with those words:
 * "delete that file when you are done", "never mind the warning". Each of those
 * previously discarded everything before the trigger and left the remainder,
 * which is the worst thing this filter can do: the result reads as fluent text
 * the user never said.
 *
 * At position 0 the only signal is the punctuation Whisper writes for the pause,
 * and the safe default is to require it. Deliberately NOT required mid-utterance:
 * Whisper does not reliably render a spoken pause, and corrections without one
 * are a supported case.
 */
private fun hasTextToRollBack(lower: String, start: Int, end: Int): Boolean {
    if (lower.substring(0, start).isNotBlank()) return true
    return lower.getOrNull(end) in setOf('.', ',', ';', ':', '!', '?', '…')
}

private fun triggerPositions(lower: String, trigger: String): List<Int> {
    val out = mutableListOf<Int>()
    var start = 0
    while (true) {
        val idx = lower.indexOf(trigger, start)
        if (idx < 0) return out
        start = idx + 1
        val beforeOk = idx == 0 || !(lower[idx - 1].isLetterOrDigit() || lower[idx - 1] == '\'')
        val after = idx + trigger.length
        val afterOk = after >= lower.length || !(lower[after].isLetterOrDigit() || lower[after] == '\'')
        if (beforeOk && afterOk && !triggerIsGoverned(lower, idx) &&
            hasTextToRollBack(lower, idx, after)
        ) {
            out += idx
        }
    }
}

private fun applySelfCorrections(text: String, triggers: List<String>): String {
    if (triggers.isEmpty()) return text
    var current = text
    while (true) {
        val lower = current.lowercase()
        // Resolve the trigger that was SPOKEN first, not the one declared first in
        // config: "scratch that. no wait ..." must resolve "scratch that".
        val found = triggers
            .flatMap { t -> triggerPositions(lower, t.lowercase()).map { it to t.lowercase() } }
            .minByOrNull { it.first } ?: return current

        val (idx, trigger) = found

        val boundary = maxOf(
            current.lastIndexOf(". ", idx - 1),
            current.lastIndexOf("! ", idx - 1),
            current.lastIndexOf("? ", idx - 1),
        )
        var end = idx + trigger.length
        // Consume the punctuation belonging to the trigger clause, or "delete
        // that." leaves a bare " . " in the middle of the output.
        while (end < current.length && current[end] in " ,.!?…") end++

        current = if (boundary == -1) {
            current.substring(end).trim()
        } else {
            (current.substring(0, boundary + 2) + current.substring(end)).trim()
        }
    }
}
