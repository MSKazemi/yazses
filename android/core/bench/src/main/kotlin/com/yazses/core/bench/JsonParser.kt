package com.yazses.core.bench

/** Thrown by [JsonParser] for any text that is not strict JSON. Caught by [BenchJson.read] and nowhere else. */
internal class JsonSyntaxError(message: String) : Exception(message)

/** Thrown by [JsonParser] when the input is well-formed but exceeds a size limit. Caught by [BenchJson.read]. */
internal class JsonLimitError(message: String) : Exception(message)

/** Most elements any one JSON array may hold. The format's only array is `clips`, a real record has a few. */
internal const val MAX_ARRAY_ELEMENTS = 10_000

/** Most members any one JSON object may hold. A real record's objects have at most five. */
internal const val MAX_OBJECT_MEMBERS = 1_000

/** Most JSON values (of any kind, nested or not) one document may hold. Bounds the parse tree itself. */
internal const val MAX_VALUES = 200_000

/** Longest run of an input copied into an error message before it is cut with an ellipsis. */
internal const val ECHO_CHARS = 64

/** [s] cut to [ECHO_CHARS] characters, with an ellipsis when it was longer. */
internal fun echo(s: String): String = if (s.length > ECHO_CHARS) s.take(ECHO_CHARS) + "\u2026" else s

/** A JSON number as written, so the reader can check its digits as well as its value. */
internal class JsonNumber(val raw: String) {
    val asDouble: Double get() = raw.toDouble()
}

/**
 * Strict, dependency-free recursive-descent JSON parser (RFC 8259) for the bench record. It throws
 * [JsonSyntaxError] and nothing else on any input: lone surrogates, raw control characters, bad
 * escapes, NaN/Infinity, duplicate keys, trailing text and nesting past [maxDepth] are all errors.
 *
 * Values: `Map<String, Any?>` (insertion-ordered), `List<Any?>`, `String`, [JsonNumber], `Boolean`,
 * and Kotlin `null` for JSON null. Absent and null are told apart with `containsKey`.
 */
internal class JsonParser(private val s: String, private val maxDepth: Int) {

    private var i = 0
    private var values = 0

    fun parseDocument(): Any? {
        skipWhitespace()
        val v = value(0)
        skipWhitespace()
        if (i != s.length) fail("trailing characters after the record")
        return v
    }

    private fun value(depth: Int): Any? {
        if (++values > MAX_VALUES) throw JsonLimitError("more than $MAX_VALUES values in the record")
        if (i >= s.length) fail("unexpected end of text")
        return when (val c = s[i]) {
            '{' -> obj(depth + 1)
            '[' -> arr(depth + 1)
            '"' -> string()
            't' -> literal("true", true)
            'f' -> literal("false", false)
            'n' -> literal("null", null)
            '-', in '0'..'9' -> number()
            else -> fail("unexpected character '${printable(c)}'")
        }
    }

    private fun obj(depth: Int): Map<String, Any?> {
        if (depth > maxDepth) fail("nesting deeper than $maxDepth")
        i++
        val out = LinkedHashMap<String, Any?>()
        skipWhitespace()
        if (peek() == '}') { i++; return out }
        while (true) {
            skipWhitespace()
            if (peek() != '"') fail("expected a string key")
            val key = string()
            skipWhitespace()
            if (peek() != ':') fail(if (i >= s.length) "unexpected end of text" else "expected ':' after key '${echo(key)}'")
            i++
            skipWhitespace()
            if (out.containsKey(key)) fail("duplicate key '${echo(key)}'")
            if (out.size >= MAX_OBJECT_MEMBERS) throw JsonLimitError("object has more than $MAX_OBJECT_MEMBERS members")
            out[key] = value(depth)
            skipWhitespace()
            when (peek() ?: fail("unexpected end of text")) {
                ',' -> i++
                '}' -> { i++; return out }
                else -> fail("expected ',' or '}'")
            }
        }
    }

    private fun arr(depth: Int): List<Any?> {
        if (depth > maxDepth) fail("nesting deeper than $maxDepth")
        i++
        val out = ArrayList<Any?>()
        skipWhitespace()
        if (peek() == ']') { i++; return out }
        while (true) {
            skipWhitespace()
            if (out.size >= MAX_ARRAY_ELEMENTS) throw JsonLimitError("array has more than $MAX_ARRAY_ELEMENTS elements")
            out += value(depth)
            skipWhitespace()
            when (peek() ?: fail("unexpected end of text")) {
                ',' -> i++
                ']' -> { i++; return out }
                else -> fail("expected ',' or ']'")
            }
        }
    }

    private fun string(): String {
        i++ // opening quote
        val sb = StringBuilder()
        while (true) {
            if (i >= s.length) fail("unexpected end of text inside a string")
            val c = s[i]
            when {
                c == '"' -> { i++; return sb.toString() }
                c == '\\' -> escape(sb)
                c < ' ' -> fail("unescaped control character U+${"%04X".format(c.code)} in string")
                Character.isHighSurrogate(c) -> {
                    if (i + 1 < s.length && Character.isLowSurrogate(s[i + 1])) {
                        sb.append(c).append(s[i + 1])
                        i += 2
                    } else {
                        fail("lone surrogate in string")
                    }
                }
                Character.isLowSurrogate(c) -> fail("lone surrogate in string")
                else -> { sb.append(c); i++ }
            }
        }
    }

    private fun escape(sb: StringBuilder) {
        i++ // backslash
        if (i >= s.length) fail("unterminated escape")
        val c = s[i]
        i++
        when (c) {
            '"', '\\', '/' -> sb.append(c)
            'b' -> sb.append('\b')
            'f' -> sb.append('\u000C')
            'n' -> sb.append('\n')
            'r' -> sb.append('\r')
            't' -> sb.append('\t')
            'u' -> {
                val unit = hex4()
                when {
                    unit in 0xD800..0xDBFF -> {
                        if (i + 1 < s.length && s[i] == '\\' && s[i + 1] == 'u') {
                            i += 2
                            val low = hex4()
                            if (low !in 0xDC00..0xDFFF) fail("lone surrogate in string")
                            sb.append(unit.toChar()).append(low.toChar())
                        } else {
                            fail("lone surrogate in string")
                        }
                    }
                    unit in 0xDC00..0xDFFF -> fail("lone surrogate in string")
                    else -> sb.append(unit.toChar())
                }
            }
            else -> fail("invalid escape '\\${printable(c)}'")
        }
    }

    private fun hex4(): Int {
        if (i + 4 > s.length) fail("invalid unicode escape: fewer than four hex digits")
        var v = 0
        repeat(4) {
            val d = s[i]
            val digit = when (d) {
                in '0'..'9' -> d - '0'
                in 'a'..'f' -> d - 'a' + 10
                in 'A'..'F' -> d - 'A' + 10
                else -> fail("invalid unicode escape: '${printable(d)}' is not a hex digit")
            }
            v = v * 16 + digit
            i++
        }
        return v
    }

    private fun number(): JsonNumber {
        val start = i
        if (peek() == '-') i++
        when (peek()) {
            '0' -> i++
            in '1'..'9' -> while (i < s.length && s[i] in '0'..'9') i++
            else -> fail("invalid number")
        }
        if (peek() == '.') {
            i++
            if (!digit()) fail("invalid number: no digit after '.'")
            while (digit()) i++
        }
        if (peek() == 'e' || peek() == 'E') {
            i++
            if (peek() == '+' || peek() == '-') i++
            if (!digit()) fail("invalid number: no digit in exponent")
            while (digit()) i++
        }
        return JsonNumber(s.substring(start, i))
    }

    private fun literal(word: String, value: Any?): Any? {
        if (!s.startsWith(word, i)) fail("invalid literal, expected '$word'")
        i += word.length
        return value
    }

    private fun digit(): Boolean = i < s.length && s[i] in '0'..'9'

    private fun peek(): Char? = if (i < s.length) s[i] else null

    private fun skipWhitespace() {
        while (i < s.length && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) i++
    }

    private fun printable(c: Char): String = if (c < ' ' || c.code > 126) "U+${"%04X".format(c.code)}" else c.toString()

    private fun fail(message: String): Nothing = throw JsonSyntaxError("$message at character $i")
}
