package com.yazses.core.vocab

/** The coined app name, which no speech model has seen in training. */
public const val APP_NAME: String = "YazSes"

/**
 * A short natural sentence primes Whisper better than a bare token: it sees the
 * word in context and in its canonical capitalisation.
 *
 * Without it the spoken name comes back as "yes ses", "yaz says", "yacht says".
 * Kept short and neutral so it primes the name without the model hallucinating
 * "YazSes" into unrelated speech.
 */
public const val BUILTIN_PROMPT: String = "The app is called YazSes."

/**
 * Compose the effective `initial_prompt`: the built-in name first, then any
 * configured or personal vocabulary.
 *
 * Blank parts are dropped. Always returns a non-empty string, because the
 * built-in phrase is always present — the nullable return mirrors the optional
 * prompts callers pass in.
 */
public fun mergeInitialPrompt(vararg parts: String?): String? {
    val chunks = mutableListOf(BUILTIN_PROMPT)
    parts.forEach { part ->
        if (!part.isNullOrBlank()) chunks += part.trim()
    }
    return chunks.joinToString(" ").trim().ifEmpty { null }
}
