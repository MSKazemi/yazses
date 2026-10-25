package com.yazses.core.stt

/**
 * What an engine returns for one decode.
 *
 * @property text the decoded text, as the engine produced it.
 * @property segments per-segment timings, empty when the engine reports none.
 */
public data class Transcript(
    val text: String,
    val segments: List<Segment> = emptyList(),
) {
    /**
     * One timed span of [text]. Times are seconds from the start of the PCM.
     *
     * @throws IllegalArgumentException unless both times are finite, the start is
     *   not negative and the end is not before the start.
     */
    public data class Segment(
        val startSec: Double,
        val endSec: Double,
        val text: String,
        /** Mean token confidence in 0..1, or null when the engine does not report it. */
        val confidence: Float? = null,
    ) {
        init {
            require(startSec.isFinite() && endSec.isFinite() && startSec >= 0.0 && endSec >= startSec) {
                "segment times must be finite and satisfy 0 <= start <= end, was $startSec..$endSec"
            }
            require(confidence == null || confidence in 0f..1f) {
                "segment confidence must be in 0..1 or null, was $confidence"
            }
        }
    }

    public companion object {
        /**
         * The transcript of silence: no text, no segments. Returned for an empty
         * or below-gate buffer so nothing is ever delivered for a silent burst
         * (ADR-MOB-005 Consequences: never `[BLANK_AUDIO]`).
         */
        public val EMPTY: Transcript = Transcript(text = "")
    }
}
