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
 * Whether the English [BUILTIN_PROMPT] may condition a decode in [language].
 *
 * True for English, and when the language is not pinned: null, empty, `auto` or
 * `translate` (which decodes the source language). Any other language gets no English
 * sentence, because Whisper conditions on the prompt and an echo of it on noise would put
 * English into that language's transcript. A region subtag is ignored (`en-GB` is `en`).
 */
public fun builtinPromptApplies(language: String?): Boolean {
    val code = (language ?: "").trim().lowercase().replace('_', '-')
    if (code == "auto" || code == "translate") return true
    val base = code.substringBefore('-')
    return base == "" || base == "en"
}

/**
 * Compose the effective `initial_prompt`: any configured or personal vocabulary
 * first, then, when [builtinPromptApplies] to [language], the built-in name **last**.
 *
 * That order is the opposite of the obvious one and it is the only order that
 * keeps the promise above. Truncation keeps the tail (see [PROMPT_TOKEN_BUDGET]),
 * so built-in-first meant built-in-first-to-be-discarded — a personal vocabulary
 * of ~120 terms overflows and takes the whole of the phrase with it, leaving the
 * app name unprimed with nothing said. Last is also the stronger position:
 * `initial_prompt` is preceding context and the tokens nearest the audio weigh
 * most.
 *
 * Blank parts are dropped, and the parts themselves are never altered by the language.
 * [language] defaults to null (unset), which keeps the phrase. Returns null when there
 * is nothing to send: a non-English language with no vocabulary.
 */
public fun mergeInitialPrompt(vararg parts: String?, language: String? = null): String? {
    val chunks = mutableListOf<String>()
    parts.forEach { part ->
        if (!part.isNullOrBlank()) chunks += part.trim()
    }
    if (builtinPromptApplies(language)) chunks += BUILTIN_PROMPT
    return chunks.joinToString(" ").trim().ifEmpty { null }
}
