package com.yazses.core.bench

/** Real-time factor: wall seconds per audio second. Same definition as desktop `span_record` (cost_meter.py:580-591). */
object Rtf {
    /** `wallS / audioS`, or null when there is no audio to divide by (not applicable, never 0). */
    fun of(wallS: Double, audioS: Double): Double? =
        if (audioS > 0.0) wallS / audioS else null
}
