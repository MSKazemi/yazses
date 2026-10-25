package com.yazses.core.bench

/**
 * Rejects a record that must not be published: missing or unknown schema, negative or
 * non-finite durations, durations finer than the 6-decimal resolution the writer applies, an
 * RTF that disagrees with the durations as they will be written, sums that overflow, no clips,
 * and a "not measured" reading without a reason.
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

        if (r.clips.isEmpty()) v += "clips: no clips"

        val seen = HashSet<String>()
        for (c in r.clips) {
            val at = "clip '${c.clipId}'"
            val before = v.size
            if (c.clipId.isBlank()) v += "clip: id is blank"
            else if (!seen.add(c.clipId)) v += "$at: duplicate clip id"
            if (!c.audioS.isFinite() || c.audioS < 0) v += "$at: audio_s must be finite and >= 0, got ${c.audioS}"
            if (!c.wallS.isFinite() || c.wallS < 0) v += "$at: wall_s must be finite and >= 0, got ${c.wallS}"
            // Judged per clip by count, not by name: a clip whose id is a prefix of another's must not be skipped.
            if (v.size > before) continue
            if (roundsToZero(c.audioS)) {
                v += "$at: audio_s ${c.audioS} is below the 1 microsecond resolution of the format"
                continue
            }
            if (roundsToZero(c.wallS)) {
                v += "$at: wall_s ${c.wallS} is below the 1 microsecond resolution of the format"
                continue
            }
            if (c.audioS == 0.0) {
                if (c.rtf != null) v += "$at: rtf must be null when audio_s is 0, got ${c.rtf}"
            } else {
                val rtf = c.rtf
                if (rtf == null) {
                    v += "$at: rtf missing for audio_s ${c.audioS}"
                } else {
                    // Checked against the durations as the writer will print them: a value finer
                    // than 6 decimals cannot be recovered from the file, so its rtf must agree with that.
                    val expected = written(c.wallS) / written(c.audioS)
                    if (!rtf.isFinite() || !expected.isFinite() || Math.abs(rtf - expected) > tolerance(expected)) {
                        v += "$at: rtf $rtf is inconsistent with wall_s/audio_s = $expected"
                    }
                }
            }
        }

        if (r.clips.all { it.audioS.isFinite() && it.wallS.isFinite() }) {
            val audioSum = r.clips.sumOf { it.audioS }
            val wallSum = r.clips.sumOf { it.wallS }
            if (!audioSum.isFinite()) v += "aggregate audio_s is not finite (the sum overflows)"
            if (!wallSum.isFinite()) v += "aggregate wall_s is not finite (the sum overflows)"
            if (audioSum.isFinite() && wallSum.isFinite()) {
                val agg = Rtf.of(wallSum, audioSum)
                if (agg != null && !agg.isFinite()) v += "aggregate rtf is not finite"
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

    /** A duration as the writer prints it: rounded half-up to 6 decimals, the same rounding BenchJson uses. */
    private fun written(seconds: Double): Double =
        java.math.BigDecimal(seconds).setScale(6, java.math.RoundingMode.HALF_UP).toDouble()

    /** Non-zero but printed as 0.000000, so the file would say the clip took no time. */
    private fun roundsToZero(seconds: Double): Boolean = seconds != 0.0 && written(seconds) == 0.0

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
