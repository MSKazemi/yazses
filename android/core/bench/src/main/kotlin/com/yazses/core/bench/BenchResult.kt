package com.yazses.core.bench

/** Schema of an on-device benchmark record. Bump the suffix on any incompatible change. */
const val BENCH_SCHEMA = "yazses.bench.android/1"

/**
 * A value that was either taken or not. "Not measured" is a state with a reason, never a
 * zero: a phone that does not expose peak memory must not look like one that used none.
 */
sealed interface Reading<out T> {
    data class Measured<out T>(val value: T) : Reading<T>
    data class NotMeasured(val reason: String) : Reading<Nothing>
}

data class DeviceInfo(
    val device: String,
    val soc: Reading<String>,
    val androidVersion: String,
)

/**
 * One clip decoded once. [rtf] is wall / audio seconds, stored so a reader sees it without
 * arithmetic; [BenchValidator] rejects it when it disagrees with the two durations. It is
 * null only when the clip has no audio (not applicable, as desktop `per_unit`, cost_meter.py:203-209).
 */
data class ClipResult(
    val clipId: String,
    val audioS: Double,
    val wallS: Double,
    val rtf: Double?,
)

data class BenchResult(
    val device: DeviceInfo,
    val engineId: String,
    val modelId: String,
    val modelSha256: String,
    val threads: Int,
    val clips: List<ClipResult>,
    val peakRssBytes: Reading<Long>,
    val schema: String = BENCH_SCHEMA,
)
