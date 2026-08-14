package com.yazses.core.postprocess

/**
 * Whisper artefacts that are not speech.
 *
 * The recogniser emits these for silence, and a confident-looking `[BLANK_AUDIO]`
 * typed into someone's document is worse than nothing at all.
 */
private val BLANK_ARTEFACTS = setOf("[BLANK_AUDIO]", "(blank)", "[INAUDIBLE]", "[silence]")

/** Leading noise Whisper adds when an utterance opens mid-thought. */
private val LEADING_NOISE = Regex("""^[\s.…]+""")

/**
 * Strip recogniser artefacts and leading punctuation from a raw transcript.
 *
 * Behaviour is defined by `contract/vectors/clean_text.json`, not by this
 * implementation — see [ADR-MOB-008]. The Kotlin is idiomatic rather than a
 * transliteration; only the observable result is contractual.
 */
public fun cleanText(text: String): String {
    val trimmed = text.trim()
    if (trimmed in BLANK_ARTEFACTS) return ""
    return LEADING_NOISE.replace(trimmed, "").trim()
}
