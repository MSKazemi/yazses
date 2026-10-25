package com.yazses.core.bench

import java.math.BigDecimal
import java.math.RoundingMode

/** Outcome of [BenchJson.read]: a record that passed validation, or every reason it did not. */
sealed interface ReadResult {
    data class Ok(val result: BenchResult) : ReadResult
    data class Rejected(val problems: List<String>) : ReadResult
}

/**
 * Deterministic JSON writer for [BenchResult]: fixed key order, 2-space indent, durations and
 * rates at 6 decimals (as desktop `round(x, 6)`, cost_meter.py:584-590), no locale, no timestamps.
 * Two runs over the same record produce byte-identical output.
 *
 * A not-measured reading is written as `null` with a sibling `*_reason` key. It is never 0.
 *
 * Ceiling: [write] refuses, with [IllegalArgumentException], any record that [BenchValidator]
 * refuses, and any record whose text would exceed [MAX_READ_CHARS] characters. A record holds at most
 * [MAX_CLIPS] clips. So every record [write] accepts is one [read] accepts.
 *
 * Round trip: `read(write(x))` equals `x` for every record `x` that [write] accepts. A value the
 * format cannot store exactly is refused rather than rounded: a duration or rate finer than six
 * decimals, a negative zero, a lone surrogate in a string, and a measured peak of 0.
 */
object BenchJson {

    /**
     * Strict reader for the format [write] produces. Malformed JSON, a wrong type, an input over
     * [MAX_READ_CHARS] characters, nesting past [MAX_READ_DEPTH], an array over [MAX_ARRAY_ELEMENTS]
     * elements, an object over [MAX_OBJECT_MEMBERS] members, over [MAX_VALUES] values, and an
     * inconsistent record all come back as [ReadResult.Rejected] with the reasons, and at most
     * [MAX_PROBLEMS] + 1 of them. Keys and numbers echoed in a message are cut to [ECHO_CHARS]
     * characters. A record that is accepted has passed [BenchValidator].
     *
     * Round trip: `read(write(x))` equals `x` for every record `x` that [write] accepts (see the class
     * note). `write(read(t))` equals `t` only when `t` is what [write] produces: the reader also accepts
     * text [write] never prints, such as an integer-valued duration as `2` or `2E0` rather than
     * `2.000000`. Integer fields refuse `-0`.
     */
    fun read(text: String): ReadResult {
        if (text.length > MAX_READ_CHARS) {
            return ReadResult.Rejected(listOf("text is ${text.length} characters, over the $MAX_READ_CHARS limit"))
        }
        if (text.isNotEmpty() && text[0] == '\uFEFF') {
            return ReadResult.Rejected(listOf("text starts with a byte order mark, which the format does not allow"))
        }
        val root = try {
            JsonParser(text, MAX_READ_DEPTH).parseDocument()
        } catch (e: JsonSyntaxError) {
            return ReadResult.Rejected(listOf("not valid JSON: ${e.message}"))
        } catch (e: JsonLimitError) {
            return ReadResult.Rejected(listOf(e.message ?: "input exceeds a size limit"))
        }
        val decoder = BenchDecoder()
        val record = decoder.decode(root)
        return if (record != null) {
            ReadResult.Ok(record)
        } else {
            ReadResult.Rejected(decoder.problems.ifEmpty { listOf("record could not be read") })
        }
    }

    private class Raw(val text: String)

    /** Reason written beside an rtf that is null: the only way a validated record has none is no audio. */
    internal const val NO_AUDIO = "no audio"

    fun write(result: BenchResult): String {
        BenchValidator.require(result)
        val sb = StringBuilder()
        render(tree(result), 0, sb)
        sb.append('\n')
        if (sb.length > MAX_READ_CHARS) {
            throw IllegalArgumentException(
                "record encodes to ${sb.length} characters, over the reader's limit of $MAX_READ_CHARS",
            )
        }
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
     * A valid surrogate pair is kept as written. A lone surrogate never reaches here: [BenchValidator]
     * refuses it, since it has no UTF-8 encoding.
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
