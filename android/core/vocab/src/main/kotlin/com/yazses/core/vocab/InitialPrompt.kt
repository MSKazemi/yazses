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
 * How many prompt tokens a Whisper decode actually keeps.
 *
 * `max_length` is 448 and the decoder splices the prompt in as the **last**
 * `max_length / 2 - 1` tokens. A longer prompt is not rejected and does not warn:
 * the front is silently discarded, and the cut lands mid-word.
 */
public const val PROMPT_TOKEN_BUDGET: Int = 223

/**
 * Compose the effective `initial_prompt`: any configured or personal vocabulary
 * first, then the built-in name **last**.
 *
 * That order is the opposite of the obvious one and it is the only order that
 * keeps the promise above. Truncation keeps the tail (see [PROMPT_TOKEN_BUDGET]),
 * so built-in-first meant built-in-first-to-be-discarded — a personal vocabulary
 * of ~120 terms overflows and takes the whole of the phrase with it, leaving the
 * app name unprimed with nothing said. Last is also the stronger position:
 * `initial_prompt` is preceding context and the tokens nearest the audio weigh
 * most.
 *
 * Blank parts are dropped. Always returns a non-empty string, because the
 * built-in phrase is always present — the nullable return mirrors the optional
 * prompts callers pass in.
 */
public fun mergeInitialPrompt(vararg parts: String?): String? {
    val chunks = mutableListOf<String>()
    parts.forEach { part ->
        if (!part.isNullOrBlank()) chunks += part.trim()
    }
    chunks += BUILTIN_PROMPT
    return chunks.joinToString(" ").trim().ifEmpty { null }
}
