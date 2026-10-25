package com.yazses.core.bench

import java.math.BigDecimal
import java.math.RoundingMode

/**
 * Deterministic JSON writer for [BenchResult]: fixed key order, 2-space indent, durations and
 * rates at 6 decimals (as desktop `round(x, 6)`, cost_meter.py:584-590), no locale, no timestamps.
 * Two runs over the same record produce byte-identical output.
 *
 * A not-measured reading is written as `null` with a sibling `*_reason` key. It is never 0.
 */
object BenchJson {

    private class Raw(val text: String)

    /** Reason written beside an rtf that is null: the only way a validated record has none is no audio. */
    private const val NO_AUDIO = "no audio"

    fun write(result: BenchResult): String {
        BenchValidator.require(result)
        val sb = StringBuilder()
        render(tree(result), 0, sb)
        sb.append('\n')
        return sb.toString()
    }

    internal fun tree(r: BenchResult): Map<String, Any?> {
        val (socValue, socReason) = split(r.device.soc)
        val (peakValue, peakReason) = split(r.peakRssBytes)
        val audioTotal = r.clips.sumOf { it.audioS }
        val wallTotal = r.clips.sumOf { it.wallS }
        val aggregateRtf = Rtf.of(wallTotal, audioTotal)
        return linkedMapOf(
            "schema" to r.schema,
            "device" to linkedMapOf(
                "model" to r.device.device,
                "soc" to socValue,
                "soc_reason" to socReason,
                "android" to r.device.androidVersion,
            ),
            "engine" to linkedMapOf(
                "id" to r.engineId,
                "model_id" to r.modelId,
                "model_sha256" to r.modelSha256,
            ),
            "threads" to r.threads,
            "peak_rss_bytes" to peakValue,
            "peak_rss_reason" to peakReason,
            "aggregate" to linkedMapOf(
                "clips" to r.clips.size,
                "audio_s" to num(audioTotal),
                "wall_s" to num(wallTotal),
                "rtf" to aggregateRtf?.let { num(it) },
                "rtf_reason" to if (aggregateRtf == null) NO_AUDIO else null,
            ),
            "clips" to r.clips.map { c ->
                linkedMapOf(
                    "id" to c.clipId,
                    "audio_s" to num(c.audioS),
                    "wall_s" to num(c.wallS),
                    "rtf" to c.rtf?.let { num(it) },
                    "rtf_reason" to if (c.rtf == null) NO_AUDIO else null,
                )
            },
        )
    }

    /** A reading becomes (value, reason): exactly one of the two is non-null. */
    private fun <T : Any> split(reading: Reading<T>): Pair<Any?, String?> = when (reading) {
        is Reading.Measured -> when (val v = reading.value) {
            is Long -> v to null
            is String -> v to null
            else -> error("unsupported reading type ${v::class}")
        }
        is Reading.NotMeasured -> null to reading.reason
    }

    private fun num(d: Double): Raw = Raw(BigDecimal(d).setScale(6, RoundingMode.HALF_UP).toPlainString())

    private fun render(v: Any?, depth: Int, sb: StringBuilder) {
        when (v) {
            null -> sb.append("null")
            is Boolean, is Int, is Long -> sb.append(v.toString())
            is Raw -> sb.append(v.text)
            is String -> quote(v, sb)
            is Map<*, *> -> {
                if (v.isEmpty()) { sb.append("{}"); return }
                sb.append("{\n")
                v.entries.forEachIndexed { i, (k, value) ->
                    indent(depth + 1, sb)
                    quote(k as String, sb)
                    sb.append(": ")
                    render(value, depth + 1, sb)
                    if (i < v.size - 1) sb.append(',')
                    sb.append('\n')
                }
                indent(depth, sb)
                sb.append('}')
            }
            is List<*> -> {
                if (v.isEmpty()) { sb.append("[]"); return }
                sb.append("[\n")
                v.forEachIndexed { i, item ->
                    indent(depth + 1, sb)
                    render(item, depth + 1, sb)
                    if (i < v.size - 1) sb.append(',')
                    sb.append('\n')
                }
                indent(depth, sb)
                sb.append(']')
            }
            else -> error("unsupported JSON value ${v::class}")
        }
    }

    private fun indent(depth: Int, sb: StringBuilder) {
        repeat(depth) { sb.append("  ") }
    }

    /**
     * A lone surrogate has no UTF-8 encoding, so it is written as U+FFFD rather than raw; a valid
     * surrogate pair is kept as written.
     */
    private fun quote(s: String, sb: StringBuilder) {
        sb.append('"')
        var i = 0
        while (i < s.length) {
            val ch = s[i]
            if (Character.isHighSurrogate(ch) && i + 1 < s.length && Character.isLowSurrogate(s[i + 1])) {
                sb.append(ch).append(s[i + 1])
                i += 2
                continue
            }
            when {
                Character.isSurrogate(ch) -> sb.append('\uFFFD')
                ch == '"' -> sb.append("\\\"")
                ch == '\\' -> sb.append("\\\\")
                ch == '\n' -> sb.append("\\n")
                ch == '\r' -> sb.append("\\r")
                ch == '\t' -> sb.append("\\t")
                ch < ' ' -> sb.append(String.format("\\u%04x", ch.code))
                else -> sb.append(ch)
            }
            i++
        }
        sb.append('"')
    }
}
