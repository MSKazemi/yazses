package com.yazses.core.stt

/**
 * Per-call decode parameters. Mirrors the desktop `transcribe()` keyword
 * arguments (`sample_rate`, `initial_prompt`, `task`).
 *
 * @property sampleRate sample rate of the PCM passed in, in Hz. Engines that
 *   need a different rate resample internally.
 * @property initialPrompt optional vocabulary hint (`:core:vocab` builds it).
 *   Engines without an equivalent document and ignore it.
 * @property task `"transcribe"` (default, same language) or `"translate"`.
 *   Engines without a translate mode document and ignore it.
 */
public data class DecodeOptions(
    val sampleRate: Int = DEFAULT_SAMPLE_RATE,
    val initialPrompt: String? = null,
    val task: String? = null,
) {
    init {
        require(sampleRate > 0) { "sampleRate must be positive, was $sampleRate" }
    }

    public companion object {
        /** The rate every YazSes capture path produces (16 kHz mono PCM). */
        public const val DEFAULT_SAMPLE_RATE: Int = 16_000
    }
}
