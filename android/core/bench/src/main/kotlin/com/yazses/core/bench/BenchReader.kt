package com.yazses.core.bench

import java.math.BigDecimal
import java.math.RoundingMode

/** Largest text [BenchJson.read] parses, in UTF-16 code units (8 MiB). */
internal const val MAX_READ_CHARS = 8 * 1024 * 1024

/** Deepest nesting [BenchJson.read] parses. The record itself nests three levels. */
internal const val MAX_READ_DEPTH = 64

private val INTEGER = Regex("-?(0|[1-9][0-9]*)")

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
 * Turns a parsed JSON tree into a [BenchResult]. Collects every problem it finds rather than
 * stopping at the first. Value rules are [BenchValidator]'s; this class checks shape (every key
 * present, no key unknown), the measured-or-reason pairing, and that the derived `aggregate` block
 * is what the writer would print.
 */
internal class BenchDecoder {

    val problems = mutableListOf<String>()

    fun decode(root: Any?): BenchResult? {
        if (root !is Map<*, *>) {
            problems += "record: expected an object"
            return null
        }
        val top = map(root)
        checkFields(top, "", TOP_KEYS)

        val schema = str(top, "", "schema")
        val threads = intField(top, "", "threads")
        val peak = reading(top, "", "peak_rss_bytes", "peak_rss_reason", "an integer") {
            (it as? JsonNumber)?.raw?.takeIf { raw -> INTEGER.matches(raw) }?.toLongOrNull()
        }
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

        if (problems.isNotEmpty()) return null
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
        problems += BenchValidator.violations(record)
        if (problems.isNotEmpty()) return null

        checkAggregate(record, aggregate.clips, aggregate.audioS, aggregate.wallS, aggregate.rtf)
        return if (problems.isEmpty()) record else null
    }

    /**
     * The aggregate is derived: the writer prints the sums of the clips and their ratio. A file
     * whose aggregate is not those values is not the writer's output, so it is refused.
     */
    private fun checkAggregate(r: BenchResult, clipCount: Int, audioS: Double, wallS: Double, rtf: Double?) {
        if (clipCount != r.clips.size) problems += "aggregate.clips: $clipCount, but the record has ${r.clips.size} clips"
        val audioSum = r.clips.sumOf { it.audioS }
        val wallSum = r.clips.sumOf { it.wallS }
        sameAtMicroseconds(audioS, audioSum, "aggregate.audio_s")
        sameAtMicroseconds(wallS, wallSum, "aggregate.wall_s")
        val expected = Rtf.of(wallSum, audioSum)
        when {
            expected == null && rtf != null -> problems += "aggregate.rtf: there is no audio, so rtf must be null"
            expected != null && rtf == null -> problems += "aggregate.rtf: missing for audio_s $audioSum"
            expected != null && rtf != null -> sameAtMicroseconds(rtf, expected, "aggregate.rtf")
        }
    }

    private fun sameAtMicroseconds(file: Double, expected: Double, name: String) {
        if (!file.isFinite() || !expected.isFinite()) {
            problems += "$name: value $file is not finite"
            return
        }
        val want = BigDecimal(expected).setScale(6, RoundingMode.HALF_UP)
        if (BigDecimal(file).setScale(6, RoundingMode.HALF_UP).compareTo(want) != 0) {
            problems += "$name: $file does not match the value the record implies, ${want.toPlainString()}"
        }
    }

    private class DeviceFields(val model: String?, val soc: Reading<String>?, val android: String?)
    private class EngineFields(val id: String?, val modelId: String?, val sha256: String?)
    private class Aggregate(val clips: Int?, val audioS: Double?, val wallS: Double?, val rtf: Double?)

    private fun clipList(top: Map<String, Any?>): List<ClipResult>? {
        if (!top.containsKey("clips")) {
            problems += "missing field: clips"
            return null
        }
        val raw = top["clips"] as? List<*> ?: run {
            problems += "clips: expected an array"
            return null
        }
        val out = raw.mapIndexedNotNull { idx, item -> clip(item, "clips[$idx]") }
        return if (out.size == raw.size) out else null
    }

    private fun clip(item: Any?, path: String): ClipResult? {
        if (item !is Map<*, *>) {
            problems += "$path: expected an object"
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
        if (!m.containsKey("rtf")) { problems += "missing field: $name"; present = false }
        if (!m.containsKey("rtf_reason")) { problems += "missing field: $reasonName"; present = false }
        if (!present) return null
        val value = m["rtf"]
        val reason = m["rtf_reason"]
        if (value != null) {
            if (reason != null) {
                problems += "$name: measured, so $reasonName must be absent or null"
                return null
            }
            if (value !is JsonNumber) {
                problems += "$name: expected a number"
                return null
            }
            return value.asDouble
        }
        if (reason != BenchJson.NO_AUDIO) problems += "$name: null needs $reasonName \"no audio\""
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
        if (!m.containsKey(key)) { problems += "missing field: $valueName"; present = false }
        if (!m.containsKey(reasonKey)) { problems += "missing field: $reasonName"; present = false }
        if (!present) return null
        val value = m[key]
        val reason = m[reasonKey]
        if (reason != null && reason !is String) {
            problems += "$reasonName: expected a string or null"
            return null
        }
        if (value != null) {
            if (reason != null) {
                problems += "$valueName: measured, so $reasonName must be absent or null"
                return null
            }
            val parsed = parse(value) ?: run {
                problems += "$valueName: expected $typeName"
                return null
            }
            return Reading.Measured(parsed)
        }
        if (reason is String) {
            if (reason.isBlank()) {
                problems += "$reasonName: is blank"
                return null
            }
            return Reading.NotMeasured(reason)
        }
        problems += "$valueName is null but $reasonName gives no reason"
        return null
    }

    /** Reports every key in [m] that the schema does not define at this level. */
    private fun checkFields(m: Map<String, Any?>, path: String, allowed: Set<String>) {
        for (key in m.keys) {
            if (key !in allowed) problems += "unknown field: ${full(path, key)}"
        }
    }

    private fun str(m: Map<String, Any?>, path: String, key: String): String? {
        val name = full(path, key)
        if (!m.containsKey(key)) {
            problems += "missing field: $name"
            return null
        }
        return m[key] as? String ?: run {
            problems += "$name: expected a string"
            null
        }
    }

    private fun child(m: Map<String, Any?>, path: String, key: String, allowed: Set<String>): Map<String, Any?>? {
        val name = full(path, key)
        if (!m.containsKey(key)) {
            problems += "missing field: $name"
            return null
        }
        val v = m[key]
        if (v !is Map<*, *>) {
            problems += "$name: expected an object"
            return null
        }
        val out = map(v)
        checkFields(out, name, allowed)
        return out
    }

    private fun number(m: Map<String, Any?>, path: String, key: String): JsonNumber? {
        val name = full(path, key)
        if (!m.containsKey(key)) {
            problems += "missing field: $name"
            return null
        }
        return m[key] as? JsonNumber ?: run {
            problems += "$name: expected a number"
            null
        }
    }

    private fun intField(m: Map<String, Any?>, path: String, key: String): Int? {
        val n = number(m, path, key) ?: return null
        val v = n.raw.takeIf { INTEGER.matches(it) }?.toIntOrNull()
        if (v == null) problems += "${full(path, key)}: expected an integer, got ${n.raw}"
        return v
    }

    private fun doubleField(m: Map<String, Any?>, path: String, key: String): Double? =
        number(m, path, key)?.asDouble

    private fun full(path: String, key: String) = if (path.isEmpty()) key else "$path.$key"

    @Suppress("UNCHECKED_CAST")
    private fun map(m: Map<*, *>): Map<String, Any?> = m as Map<String, Any?>
}
