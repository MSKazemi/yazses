package com.yazses.core.bench

import java.math.BigDecimal
import java.math.RoundingMode

/**
 * Largest text [BenchJson.read] parses, in UTF-16 code units: 1 MiB of characters. A UTF-8 file can
 * be larger than this in bytes when it holds non-ASCII text. A real record is a few kilobytes.
 */
internal const val MAX_READ_CHARS = 1_048_576

/** Most clips one record holds. Sized so that the largest such record fits in [MAX_READ_CHARS]. */
internal const val MAX_CLIPS = 5_000

/** Deepest nesting [BenchJson.read] parses. The record itself nests three levels. */
internal const val MAX_READ_DEPTH = 64

/** Most problems [BenchJson.read] reports. A longer list ends with one "and N more problems" entry. */
internal const val MAX_PROBLEMS = 100

/** Longest single problem message kept, so no message can carry an unbounded copy of the input. */
internal const val MAX_PROBLEM_CHARS = 300

private val INTEGER = Regex("-?(0|[1-9][0-9]*)")

/**
 * The integer a JSON number spells, or null. Refuses `-0`: the writer never prints a negative zero
 * for an integer field, so a file that has one was not written by it.
 */
private fun wholeNumber(raw: String): Long? =
    if (raw == "-0" || !INTEGER.matches(raw)) null else raw.toLongOrNull()

// The exact key set the writer emits at each level. Anything else is an unknown field, and any of
// these that is absent is a missing field: the schema is versioned, so the shape is fixed.
private val TOP_KEYS = setOf(
    "schema", "device", "engine", "threads", "peak_rss_bytes", "peak_rss_reason", "aggregate", "clips",
)
private val DEVICE_KEYS = setOf("model", "soc", "soc_reason", "android")
private val ENGINE_KEYS = setOf("id", "model_id", "model_sha256")
private val AGGREGATE_KEYS = setOf("clips", "audio_s", "wall_s", "rtf", "rtf_reason")
private val CLIP_KEYS = setOf("id", "audio_s", "wall_s", "rtf", "rtf_reason")

/**
 * Turns a parsed JSON tree into a [BenchResult]. Collects problems rather than stopping at the
 * first, but keeps at most [MAX_PROBLEMS] of them, so the list is bounded whatever the input. Value
 * rules are [BenchValidator]'s; this class checks shape (every key present, no key unknown), the
 * measured-or-reason pairing, and that the derived `aggregate` block is what the writer would print.
 */
internal class BenchDecoder {

    private val kept = ArrayList<String>()
    private var total = 0

    private fun add(problem: String) {
        total++
        if (kept.size < MAX_PROBLEMS) {
            kept += if (problem.length > MAX_PROBLEM_CHARS) problem.take(MAX_PROBLEM_CHARS) + "…" else problem
        }
    }

    private val hasProblems: Boolean get() = total > 0

    /** The kept problems, plus one summary entry with the exact count of the rest when there are more. */
    val problems: List<String>
        get() = if (total > MAX_PROBLEMS) kept + "and ${total - MAX_PROBLEMS} more problems" else kept.toList()

    fun decode(root: Any?): BenchResult? {
        if (root !is Map<*, *>) {
            add("record: expected an object")
            return null
        }
        val top = map(root)
        checkFields(top, "", TOP_KEYS)

        val schema = str(top, "", "schema")
        val threads = intField(top, "", "threads")
        val peak = reading(top, "", "peak_rss_bytes", "peak_rss_reason", "an integer") { v ->
            (v as? JsonNumber)?.raw?.let(::wholeNumber)
        }
        if (peak is Reading.Measured && peak.value == 0L) add(BenchValidator.PEAK_ZERO_PROBLEM)
        val device = child(top, "", "device", DEVICE_KEYS)?.let { d ->
            DeviceFields(
                model = str(d, "device", "model"),
                soc = reading(d, "device", "soc", "soc_reason", "a string") { it as? String },
                android = str(d, "device", "android"),
            )
        }
        val engine = child(top, "", "engine", ENGINE_KEYS)?.let { e ->
            EngineFields(
                id = str(e, "engine", "id"),
                modelId = str(e, "engine", "model_id"),
                sha256 = str(e, "engine", "model_sha256"),
            )
        }
        val aggregate = child(top, "", "aggregate", AGGREGATE_KEYS)?.let { a ->
            Aggregate(
                clips = intField(a, "aggregate", "clips"),
                audioS = doubleField(a, "aggregate", "audio_s"),
                wallS = doubleField(a, "aggregate", "wall_s"),
                rtf = rtf(a, "aggregate"),
            )
        }
        val clips = clipList(top)

        if (hasProblems) return null
        if (schema == null || threads == null || peak == null || device == null || engine == null ||
            aggregate == null || clips == null
        ) return null
        val model = device.model
        val soc = device.soc
        val android = device.android
        val id = engine.id
        val modelId = engine.modelId
        val sha = engine.sha256
        if (model == null || soc == null || android == null || id == null || modelId == null || sha == null) return null
        if (aggregate.clips == null || aggregate.audioS == null || aggregate.wallS == null) return null

        val record = BenchResult(
            device = DeviceInfo(model, soc, android),
            engineId = id,
            modelId = modelId,
            modelSha256 = sha,
            threads = threads,
            clips = clips,
            peakRssBytes = peak,
            schema = schema,
        )
        BenchValidator.violations(record).forEach { add(it) }
        if (hasProblems) return null

        checkAggregate(record, aggregate.clips, aggregate.audioS, aggregate.wallS, aggregate.rtf)
        return if (hasProblems) null else record
    }

    /**
     * The aggregate is derived: the writer prints the sums of the clips and their ratio. A file
     * whose aggregate is not those values is not the writer's output, so it is refused.
     */
    private fun checkAggregate(r: BenchResult, clipCount: Int, audioS: Double, wallS: Double, rtf: Double?) {
        if (clipCount != r.clips.size) add("aggregate.clips: $clipCount, but the record has ${r.clips.size} clips")
        val audioSum = r.clips.sumOf { it.audioS }
        val wallSum = r.clips.sumOf { it.wallS }
        sameAtMicroseconds(audioS, audioSum, "aggregate.audio_s")
        sameAtMicroseconds(wallS, wallSum, "aggregate.wall_s")
        val expected = Rtf.of(wallSum, audioSum)
        when {
            expected == null && rtf != null -> add("aggregate.rtf: there is no audio, so rtf must be null")
            expected != null && rtf == null -> add("aggregate.rtf: missing for audio_s $audioSum")
            expected != null && rtf != null -> sameAtMicroseconds(rtf, expected, "aggregate.rtf")
        }
    }

    private fun sameAtMicroseconds(file: Double, expected: Double, name: String) {
        if (!file.isFinite() || !expected.isFinite()) {
            add("$name: value $file is not finite")
            return
        }
        val want = BigDecimal(expected).setScale(6, RoundingMode.HALF_UP)
        if (BigDecimal(file).setScale(6, RoundingMode.HALF_UP).compareTo(want) != 0) {
            add("$name: $file does not match the value the record implies, ${want.toPlainString()}")
        }
    }

    private class DeviceFields(val model: String?, val soc: Reading<String>?, val android: String?)
    private class EngineFields(val id: String?, val modelId: String?, val sha256: String?)
    private class Aggregate(val clips: Int?, val audioS: Double?, val wallS: Double?, val rtf: Double?)

    private fun clipList(top: Map<String, Any?>): List<ClipResult>? {
        if (!top.containsKey("clips")) {
            add("missing field: clips")
            return null
        }
        val raw = top["clips"] as? List<*> ?: run {
            add("clips: expected an array")
            return null
        }
        if (raw.size > MAX_CLIPS) {
            add("clips: more than $MAX_CLIPS clips, the most one record can hold")
            return null
        }
        val out = raw.mapIndexedNotNull { idx, item -> clip(item, "clips[$idx]") }
        return if (out.size == raw.size) out else null
    }

    private fun clip(item: Any?, path: String): ClipResult? {
        if (item !is Map<*, *>) {
            add("$path: expected an object")
            return null
        }
        val m = map(item)
        checkFields(m, path, CLIP_KEYS)
        val id = str(m, path, "id")
        val audio = doubleField(m, path, "audio_s")
        val wall = doubleField(m, path, "wall_s")
        val rtf = rtf(m, path)
        return if (id != null && audio != null && wall != null) ClipResult(id, audio, wall, rtf) else null
    }

    /**
     * An rtf is a number, or null with `rtf_reason` "no audio". Both keys must be present. Not a
     * [Reading]: a clip with no audio has no rtf to report.
     */
    private fun rtf(m: Map<String, Any?>, path: String): Double? {
        val name = full(path, "rtf")
        val reasonName = full(path, "rtf_reason")
        var present = true
        if (!m.containsKey("rtf")) { add("missing field: $name"); present = false }
        if (!m.containsKey("rtf_reason")) { add("missing field: $reasonName"); present = false }
        if (!present) return null
        val value = m["rtf"]
        val reason = m["rtf_reason"]
        if (value != null) {
            if (reason != null) {
                add("$name: measured, so $reasonName must be absent or null")
                return null
            }
            if (value !is JsonNumber) {
                add("$name: expected a number")
                return null
            }
            return value.asDouble
        }
        if (reason != BenchJson.NO_AUDIO) add("$name: null needs $reasonName \"no audio\"")
        return null
    }

    /**
     * A value that is measured or not, with its reason beside it. Both keys must be present. Measured:
     * a non-null value and a null reason. Not measured: a null value with a non-blank reason. Anything
     * else, including an absent key, is a problem. A not-measured reading is never zero.
     */
    private fun <T : Any> reading(
        m: Map<String, Any?>,
        path: String,
        key: String,
        reasonKey: String,
        typeName: String,
        parse: (Any?) -> T?,
    ): Reading<T>? {
        val valueName = full(path, key)
        val reasonName = full(path, reasonKey)
        var present = true
        if (!m.containsKey(key)) { add("missing field: $valueName"); present = false }
        if (!m.containsKey(reasonKey)) { add("missing field: $reasonName"); present = false }
        if (!present) return null
        val value = m[key]
        val reason = m[reasonKey]
        if (reason != null && reason !is String) {
            add("$reasonName: expected a string or null")
            return null
        }
        if (value != null) {
            if (reason != null) {
                add("$valueName: measured, so $reasonName must be absent or null")
                return null
            }
            val parsed = parse(value)
            if (parsed == null) {
                val got = (value as? JsonNumber)?.let { ", got ${echo(it.raw)}" } ?: ""
                add("$valueName: expected $typeName$got")
                return null
            }
            return Reading.Measured(parsed)
        }
        if (reason is String) {
            if (reason.isBlank()) {
                add("$reasonName: is blank")
                return null
            }
            return Reading.NotMeasured(reason)
        }
        add("$valueName is null but $reasonName gives no reason")
        return null
    }

    /** Reports every key in [m] that the schema does not define at this level. */
    private fun checkFields(m: Map<String, Any?>, path: String, allowed: Set<String>) {
        for (key in m.keys) {
            if (key !in allowed) add("unknown field: ${echo(full(path, key))}")
        }
    }

    private fun str(m: Map<String, Any?>, path: String, key: String): String? {
        val name = full(path, key)
        if (!m.containsKey(key)) {
            add("missing field: $name")
            return null
        }
        return m[key] as? String ?: run {
            add("$name: expected a string")
            null
        }
    }

    private fun child(m: Map<String, Any?>, path: String, key: String, allowed: Set<String>): Map<String, Any?>? {
        val name = full(path, key)
        if (!m.containsKey(key)) {
            add("missing field: $name")
            return null
        }
        val v = m[key]
        if (v !is Map<*, *>) {
            add("$name: expected an object")
            return null
        }
        val out = map(v)
        checkFields(out, name, allowed)
        return out
    }

    private fun number(m: Map<String, Any?>, path: String, key: String): JsonNumber? {
        val name = full(path, key)
        if (!m.containsKey(key)) {
            add("missing field: $name")
            return null
        }
        return m[key] as? JsonNumber ?: run {
            add("$name: expected a number")
            null
        }
    }

    private fun intField(m: Map<String, Any?>, path: String, key: String): Int? {
        val n = number(m, path, key) ?: return null
        val v = wholeNumber(n.raw)?.takeIf { it in Int.MIN_VALUE..Int.MAX_VALUE }?.toInt()
        if (v == null) add("${full(path, key)}: expected an integer, got ${echo(n.raw)}")
        return v
    }

    private fun doubleField(m: Map<String, Any?>, path: String, key: String): Double? =
        number(m, path, key)?.asDouble

    private fun full(path: String, key: String) = if (path.isEmpty()) key else "$path.$key"

    @Suppress("UNCHECKED_CAST")
    private fun map(m: Map<*, *>): Map<String, Any?> = m as Map<String, Any?>
}
