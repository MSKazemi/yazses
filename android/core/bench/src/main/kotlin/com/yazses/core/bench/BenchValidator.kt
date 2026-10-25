package com.yazses.core.bench

/**
 * Rejects a record that must not be published: missing or unknown schema, negative or
 * non-finite durations, an RTF that disagrees with its own wall and audio seconds, and a
 * "not measured" reading without a reason.
 */
object BenchValidator {

    private val SHA256 = Regex("[0-9a-f]{64}")

    /** Human-readable violations; empty when the record is publishable. */
    fun violations(r: BenchResult): List<String> {
        val v = mutableListOf<String>()

        when {
            r.schema.isBlank() -> v += "schema: missing"
            r.schema != BENCH_SCHEMA -> v += "schema: expected $BENCH_SCHEMA, got '${r.schema}'"
        }

        blank(r.device.device, "device.device", v)
        blank(r.device.androidVersion, "device.androidVersion", v)
        checkReading(r.device.soc, "device.soc", v) { if (it.isBlank()) v += "device.soc: measured value is blank" }
        blank(r.engineId, "engineId", v)
        blank(r.modelId, "modelId", v)
        if (!SHA256.matches(r.modelSha256)) v += "modelSha256: must be 64 lowercase hex characters"
        if (r.threads < 1) v += "threads: must be >= 1, got ${r.threads}"

        checkReading(r.peakRssBytes, "peakRssBytes", v) {
            if (it < 0) v += "peakRssBytes: negative (${it})"
        }

        val seen = HashSet<String>()
        for (c in r.clips) {
            val at = "clip '${c.clipId}'"
            if (c.clipId.isBlank()) v += "clip: id is blank"
            else if (!seen.add(c.clipId)) v += "$at: duplicate clip id"
            if (!c.audioS.isFinite() || c.audioS < 0) v += "$at: audio_s must be finite and >= 0, got ${c.audioS}"
            if (!c.wallS.isFinite() || c.wallS < 0) v += "$at: wall_s must be finite and >= 0, got ${c.wallS}"
            if (v.any { it.startsWith(at) }) continue
            if (c.audioS == 0.0) {
                if (c.rtf != null) v += "$at: rtf must be null when audio_s is 0, got ${c.rtf}"
            } else {
                val rtf = c.rtf
                if (rtf == null) {
                    v += "$at: rtf missing for audio_s ${c.audioS}"
                } else {
                    val expected = c.wallS / c.audioS
                    if (!rtf.isFinite() || Math.abs(rtf - expected) > tolerance(expected)) {
                        v += "$at: rtf $rtf is inconsistent with wall_s/audio_s = $expected"
                    }
                }
            }
        }
        return v
    }

    /** Throws [IllegalArgumentException] listing every violation, or returns [r] unchanged. */
    fun require(r: BenchResult): BenchResult {
        val v = violations(r)
        require(v.isEmpty()) { "invalid bench record: ${v.joinToString("; ")}" }
        return r
    }

    /** Covers the 6-decimal rounding the writer applies to wall, audio and rtf. */
    internal fun tolerance(expected: Double): Double = maxOf(1e-5, 1e-4 * Math.abs(expected))

    private fun blank(value: String, name: String, out: MutableList<String>) {
        if (value.isBlank()) out += "$name: is blank"
    }

    private fun <T> checkReading(
        reading: Reading<T>,
        name: String,
        out: MutableList<String>,
        checkMeasured: (T) -> Unit,
    ) {
        when (reading) {
            is Reading.Measured -> checkMeasured(reading.value)
            is Reading.NotMeasured ->
                if (reading.reason.isBlank()) out += "$name: not measured but no reason given"
        }
    }
}
