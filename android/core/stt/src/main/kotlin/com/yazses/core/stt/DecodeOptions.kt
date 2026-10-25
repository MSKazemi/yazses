package com.yazses.core.stt

/**
 * Per-call decode parameters. Mirrors the desktop `transcribe()` keyword
 * arguments (`sample_rate`, `initial_prompt`, `task`).
 *
 * @property sampleRate sample rate of the PCM passed in, in Hz. Engines that
 *   need a different rate resample internally.
 * @property initialPrompt optional vocabulary hint (`:core:vocab` builds it).
 *   Engines without an equivalent document and ignore it.
 * @property task `null` (default, same as [TASK_TRANSCRIBE]) or [TASK_TRANSLATE].
 *   These are the only two values the desktop passes to `transcribe()`; any
 *   other string is rejected at construction. Engines without a translate mode
 *   document and ignore it.
 */
public data class DecodeOptions(
    val sampleRate: Int = DEFAULT_SAMPLE_RATE,
    val initialPrompt: String? = null,
    val task: String? = null,
) {
    init {
        require(sampleRate > 0) { "sampleRate must be positive, was $sampleRate" }
        require(task == null || task == TASK_TRANSCRIBE || task == TASK_TRANSLATE) {
            "task must be null, \"$TASK_TRANSCRIBE\" or \"$TASK_TRANSLATE\", was \"$task\""
        }
    }

    public companion object {
        /** The rate every YazSes capture path produces (16 kHz mono PCM). */
        public const val DEFAULT_SAMPLE_RATE: Int = 16_000

        /** Decode in the spoken language. The default. */
        public const val TASK_TRANSCRIBE: String = "transcribe"

        /** Render the speech as English (Whisper's built-in translate task). */
        public const val TASK_TRANSLATE: String = "translate"
    }
}
