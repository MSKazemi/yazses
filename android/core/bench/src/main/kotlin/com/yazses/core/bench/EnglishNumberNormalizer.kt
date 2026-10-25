// Port of whisper_normalizer.english.EnglishNumberNormalizer (whisper-normalizer 0.1.15, MIT).
// Licence and attribution: see the header of EnglishTextNormalizer.kt. Line-for-line port; the
// order of rules and every arithmetic result must match the Python.
//
// Python values are modelled as: null (None), BigInteger (int), String (str). Python's Fraction
// is modelled by BigDecimal, which is exact for the decimal strings this code ever sees.
package com.yazses.core.bench

import java.math.BigDecimal
import java.math.BigInteger

/** Python `^\d+(\.\d+)?$` (a full match here; the inputs never contain a newline). \d is Unicode in Python. */
private val NUMERIC = Regex("\\p{Nd}+(\\.\\p{Nd}+)?")

/** The digits Python's Fraction grammar accepts: an optional integer part, an optional fraction, at least one digit. */
private val FRACTION_FORM = Regex("(\\p{Nd}*)(?:\\.(\\p{Nd}*))?")

private val BI_10: BigInteger = BigInteger.valueOf(10)
private val BI_100: BigInteger = BigInteger.valueOf(100)
private val BI_1000: BigInteger = BigInteger.valueOf(1000)

/**
 * Python `Fraction(s)` for the strings this normaliser passes it, or null where Python raises
 * ValueError. Accepts "12", "1.", ".5", "1.50"; rejects "", ".", "1.2.3", "1.-5".
 */
internal fun toFraction(v: Any): BigDecimal? {
    if (v is BigInteger) return BigDecimal(v)
    val m = FRACTION_FORM.matchEntire(v as String) ?: return null
    val intPart = m.groupValues[1]
    val fracPart = m.groupValues[2]
    if (intPart.isEmpty() && fracPart.isEmpty()) return null
    return BigDecimal(asciiDigits(intPart.ifEmpty { "0" }) + "." + asciiDigits(fracPart.ifEmpty { "0" }))
}

/** Replaces each Unicode decimal digit with its ASCII value, so BigDecimal parses it as Python's int() would. */
private fun asciiDigits(s: String): String {
    val sb = StringBuilder(s.length)
    s.codePoints().forEach { cp ->
        if (cp == '.'.code) sb.append('.') else sb.append('0' + Character.digit(cp, 10))
    }
    return sb.toString()
}

/** A Fraction with denominator 1 (Python's `p.denominator == 1`): the value is a whole number. */
private fun BigDecimal.isIntegral(): Boolean = signum() == 0 || stripTrailingZeros().scale() <= 0

/** Python `str(x)` for the value types used here. */
private fun pyStr(v: Any?): String = when (v) {
    is BigInteger -> v.toString()
    is String -> v
    else -> throw IllegalStateException("str() of a Python None")
}

/** Python `str(value or "")`: None, int 0 and "" are all falsy and become "". */
private fun orEmpty(v: Any?): String = when {
    v == null -> ""
    v is BigInteger && v.signum() == 0 -> ""
    v is String && v.isEmpty() -> ""
    else -> pyStr(v)
}

/** Python `assert value[-1] == "0"`: a failed assertion raised AssertionError in Python, so it raises here too. */
private fun assertLastZero(s: String) {
    check(s.isNotEmpty() && s.last() == '0') { "assert value[-1] == \"0\" failed for \"$s\"" }
}

internal class EnglishNumberNormalizer {

    private val zeros: Set<String> = setOf("o", "oh", "zero")

    private val ones: Map<String, Int> = listOf(
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
        "eighteen", "nineteen",
    ).withIndex().associate { (i, name) -> name to i + 1 }

    private val onesPlural: Map<String, Pair<Int, String>> = ones.map { (name, value) ->
        (if (name == "six") "sixes" else name + "s") to (value to "s")
    }.toMap()

    private val onesOrdinal: Map<String, Pair<Int, String>> = linkedMapOf(
        "zeroth" to (0 to "th"),
        "first" to (1 to "st"),
        "second" to (2 to "nd"),
        "third" to (3 to "rd"),
        "fifth" to (5 to "th"),
        "twelfth" to (12 to "th"),
    ) + ones.filter { (_, value) -> value > 3 && value != 5 && value != 12 }.map { (name, value) ->
        (name + (if (name.endsWith("t")) "h" else "th")) to (value to "th")
    }.toMap()

    private val onesSuffixed: Map<String, Pair<Int, String>> = onesPlural + onesOrdinal

    private val tens: Map<String, Int> = linkedMapOf(
        "twenty" to 20, "thirty" to 30, "forty" to 40, "fifty" to 50, "sixty" to 60,
        "seventy" to 70, "eighty" to 80, "ninety" to 90,
    )

    private val tensPlural: Map<String, Pair<Int, String>> =
        tens.map { (name, value) -> name.replace("y", "ies") to (value to "s") }.toMap()

    private val tensOrdinal: Map<String, Pair<Int, String>> =
        tens.map { (name, value) -> name.replace("y", "ieth") to (value to "th") }.toMap()

    private val tensSuffixed: Map<String, Pair<Int, String>> = tensPlural + tensOrdinal

    private val multipliers: Map<String, BigInteger> = linkedMapOf(
        "hundred" to BigInteger.valueOf(100),
        "thousand" to BigInteger.TEN.pow(3),
        "million" to BigInteger.TEN.pow(6),
        "billion" to BigInteger.TEN.pow(9),
        "trillion" to BigInteger.TEN.pow(12),
        "quadrillion" to BigInteger.TEN.pow(15),
        "quintillion" to BigInteger.TEN.pow(18),
        "sextillion" to BigInteger.TEN.pow(21),
        "septillion" to BigInteger.TEN.pow(24),
        "octillion" to BigInteger.TEN.pow(27),
        "nonillion" to BigInteger.TEN.pow(30),
        "decillion" to BigInteger.TEN.pow(33),
    )

    private val multipliersSuffixed: Map<String, Pair<BigInteger, String>> =
        multipliers.map { (name, value) -> (name + "s") to (value to "s") }.toMap() +
            multipliers.map { (name, value) -> (name + "th") to (value to "th") }.toMap()

    private val decimals: Set<String> = ones.keys + tens.keys + zeros

    private val precedingPrefixers: Map<String, String> = linkedMapOf(
        "minus" to "-", "negative" to "-", "plus" to "+", "positive" to "+",
    )

    private val followingPrefixers: Map<String, String> = linkedMapOf(
        "pound" to "£", "pounds" to "£", "euro" to "€", "euros" to "€",
        "dollar" to "$", "dollars" to "$", "cent" to "¢", "cents" to "¢",
    )

    private val prefixChars: Set<Char> =
        (precedingPrefixers.values + followingPrefixers.values).map { it[0] }.toSet()

    private val specials: Set<String> = setOf("and", "double", "triple", "point")

    /** Python `self.words`: every key of the mappings above, plus the suffixer keys "per" and "percent". */
    private val wordSet: Set<String> = (
        zeros + ones.keys + onesSuffixed.keys + tens.keys + tensSuffixed.keys + multipliers.keys +
            multipliersSuffixed.keys + precedingPrefixers.keys + followingPrefixers.keys +
            setOf("per", "percent") + specials
        ).toSet()

    /** Python `self.suffixers`: "per" maps {"cent": "%"}, "percent" maps to "%". */
    private val suffixKeys: Set<String> = setOf("per", "percent")

    /** Python `process_words`, a line-for-line port. Returns the yielded pieces in order. */
    internal fun processWords(words: List<String>): List<String> {
        val out = ArrayList<String>()
        var prefix: String? = null
        var value: Any? = null // null, BigInteger, or String
        var skip = false

        fun output(result: Any?): String {
            var r = pyStr(result)
            val p = prefix
            if (p != null) r = p + r
            value = null
            prefix = null
            return r
        }

        fun emit(result: Any?) {
            out += output(result)
        }

        for (idx in words.indices) {
            val prev: String? = if (idx > 0) words[idx - 1] else null
            val current = words[idx]
            val next: String? = if (idx + 1 < words.size) words[idx + 1] else null
            if (skip) {
                skip = false
                continue
            }

            val nextIsNumeric = next != null && NUMERIC.matches(next)
            val hasPrefix = current[0] in prefixChars
            val currentWithoutPrefix = if (hasPrefix) current.substring(1) else current

            if (NUMERIC.matches(currentWithoutPrefix)) {
                // arabic numbers (potentially with signs and fractions)
                val f = toFraction(currentWithoutPrefix)
                checkNotNull(f) { "assert f is not None" }
                val v = value
                if (v != null) {
                    if (v is String && v.endsWith(".")) {
                        // concatenate decimals / ip address components
                        value = v + current
                        continue
                    } else {
                        emit(v)
                    }
                }
                prefix = if (hasPrefix) current[0].toString() else prefix
                value = if (f.isIntegral()) f.toBigInteger() else currentWithoutPrefix
            } else if (current !in wordSet) {
                // non-numeric words
                if (value != null) emit(value)
                emit(current)
            } else if (current in zeros) {
                value = orEmpty(value) + "0"
            } else if (current in ones) {
                val onesN = ones.getValue(current)
                val v = value
                if (v == null) {
                    value = BigInteger.valueOf(onesN.toLong())
                } else if (v is String || (prev != null && prev in ones)) {
                    if (prev != null && prev in tens && onesN < 10) {
                        // replace the last zero with the digit
                        val s = pyStr(v)
                        assertLastZero(s)
                        value = s.dropLast(1) + onesN
                    } else {
                        value = pyStr(v) + onesN
                    }
                } else if (onesN < 10) {
                    val n = v as BigInteger
                    value = if (n.mod(BI_10).signum() == 0) n.add(BigInteger.valueOf(onesN.toLong())) else n.toString() + onesN
                } else { // eleven to nineteen
                    val n = v as BigInteger
                    value = if (n.mod(BI_100).signum() == 0) n.add(BigInteger.valueOf(onesN.toLong())) else n.toString() + onesN
                }
            } else if (current in onesSuffixed) {
                // ordinal or cardinal; yield the number right away
                val (onesN, suffix) = onesSuffixed.getValue(current)
                val v = value
                if (v == null) {
                    emit("$onesN$suffix")
                } else if (v is String || (prev != null && prev in ones)) {
                    if (prev != null && prev in tens && onesN < 10) {
                        val s = pyStr(v)
                        assertLastZero(s)
                        emit(s.dropLast(1) + onesN + suffix)
                    } else {
                        emit(pyStr(v) + onesN + suffix)
                    }
                } else if (onesN < 10) {
                    val n = v as BigInteger
                    if (n.mod(BI_10).signum() == 0) emit(n.add(BigInteger.valueOf(onesN.toLong())).toString() + suffix)
                    else emit(n.toString() + onesN + suffix)
                } else { // eleven to nineteen
                    val n = v as BigInteger
                    if (n.mod(BI_100).signum() == 0) emit(n.add(BigInteger.valueOf(onesN.toLong())).toString() + suffix)
                    else emit(n.toString() + onesN + suffix)
                }
                value = null
            } else if (current in tens) {
                val tensN = tens.getValue(current)
                val v = value
                if (v == null) {
                    value = BigInteger.valueOf(tensN.toLong())
                } else if (v is String) {
                    value = v + tensN
                } else {
                    val n = v as BigInteger
                    value = if (n.mod(BI_100).signum() == 0) n.add(BigInteger.valueOf(tensN.toLong())) else n.toString() + tensN
                }
            } else if (current in tensSuffixed) {
                // ordinal or cardinal; yield the number right away
                val (tensN, suffix) = tensSuffixed.getValue(current)
                val v = value
                if (v == null) {
                    emit("$tensN$suffix")
                } else if (v is String) {
                    emit(v + tensN + suffix)
                } else {
                    val n = v as BigInteger
                    if (n.mod(BI_100).signum() == 0) emit(n.add(BigInteger.valueOf(tensN.toLong())).toString() + suffix)
                    else emit(n.toString() + tensN + suffix)
                }
            } else if (current in multipliers) {
                val multiplier = multipliers.getValue(current)
                val v = value
                if (v == null) {
                    value = multiplier
                } else if (v is String || (v is BigInteger && v.signum() == 0)) {
                    val f = toFraction(v)
                    val p = f?.multiply(BigDecimal(multiplier))
                    if (f != null && p != null && p.isIntegral()) {
                        value = p.toBigInteger()
                    } else {
                        emit(v)
                        value = multiplier
                    }
                } else { // int
                    val n = v as BigInteger
                    val before = n.divide(BI_1000).multiply(BI_1000)
                    val residual = n.mod(BI_1000)
                    value = before.add(residual.multiply(multiplier))
                }
            } else if (current in multipliersSuffixed) {
                val (multiplier, suffix) = multipliersSuffixed.getValue(current)
                val v = value
                if (v == null) {
                    emit(multiplier.toString() + suffix)
                } else if (v is String) {
                    val f = toFraction(v)
                    val p = f?.multiply(BigDecimal(multiplier))
                    if (f != null && p != null && p.isIntegral()) {
                        emit(p.toBigInteger().toString() + suffix)
                    } else {
                        emit(v)
                        emit(multiplier.toString() + suffix)
                    }
                } else { // int
                    val n = v as BigInteger
                    val before = n.divide(BI_1000).multiply(BI_1000)
                    val residual = n.mod(BI_1000)
                    value = before.add(residual.multiply(multiplier))
                    emit(value.toString() + suffix)
                }
                value = null
            } else if (current in precedingPrefixers) {
                // apply prefix (positive, minus, etc.) if it precedes a number
                if (value != null) emit(value)
                if ((next != null && next in wordSet) || nextIsNumeric) {
                    prefix = precedingPrefixers.getValue(current)
                } else {
                    emit(current)
                }
            } else if (current in followingPrefixers) {
                // apply prefix (dollars, cents, etc.) only after a number
                if (value != null) {
                    prefix = followingPrefixers.getValue(current)
                    emit(value)
                } else {
                    emit(current)
                }
            } else if (current in suffixKeys) {
                // apply suffix symbols (percent -> '%')
                if (value != null) {
                    if (current == "per") {
                        if (next == "cent") {
                            emit(pyStr(value) + "%")
                            skip = true
                        } else {
                            emit(value)
                            emit(current)
                        }
                    } else {
                        emit(pyStr(value) + "%")
                    }
                } else {
                    emit(current)
                }
            } else if (current in specials) {
                if ((next == null || next !in wordSet) && !nextIsNumeric) {
                    // apply special handling only if the next word can be numeric
                    if (value != null) emit(value)
                    emit(current)
                } else if (current == "and") {
                    // ignore "and" after hundreds, thousands, etc.
                    if (!(prev != null && prev in multipliers)) {
                        if (value != null) emit(value)
                        emit(current)
                    }
                } else if (current == "double" || current == "triple") {
                    // Python's `next in self.ones` is False for None; orEmpty() is in neither set either.
                    if (next.orEmpty() in ones || next.orEmpty() in zeros) {
                        val repeats = if (current == "double") 2 else 3
                        val digit = ones[next.orEmpty()] ?: 0
                        value = orEmpty(value) + digit.toString().repeat(repeats)
                        skip = true
                    } else {
                        if (value != null) emit(value)
                        emit(current)
                    }
                } else if (current == "point") {
                    if (next.orEmpty() in decimals || nextIsNumeric) {
                        value = orEmpty(value) + "."
                    }
                } else {
                    throw IllegalStateException("Unexpected token: $current")
                }
            } else {
                throw IllegalStateException("Unexpected token: $current")
            }
        }

        if (value != null) emit(value)
        return out
    }

    internal fun preprocess(s: String): String {
        // replace "<number> and a half" with "<number> point five"
        val results = ArrayList<String>()
        val segments = pyReSplit(AND_A_HALF, s)
        for ((i, segment) in segments.withIndex()) {
            if (pyStrip(segment).isEmpty()) continue
            if (i == segments.size - 1) {
                results += segment
            } else {
                results += segment
                val lastWord = pySplit(segment).last() // segment.rsplit(maxsplit=2)[-1]
                if (lastWord in decimals || lastWord in multipliers) results += "point five"
                else results += "and a half"
            }
        }

        var out = results.joinToString(" ")

        // put a space at number/letter boundary
        out = NUMBER_THEN_LETTER_BOUNDARY.replace(out, "$1 $2")
        out = LETTER_THEN_NUMBER_BOUNDARY.replace(out, "$1 $2")

        // but remove spaces which could be a suffix
        out = SUFFIX_SPACE.replace(out, "$1$2")
        return out
    }

    internal fun postprocess(s0: String): String {
        // apply currency postprocessing; "$2 and ¢7" -> "$2.07"
        var s = COMBINE_CENTS.replace(s0) { m ->
            val currency = m.groupValues[1]
            val integer = m.groupValues[2]
            val cents = m.groupValues[3].toInt()
            currency + integer + "." + cents.toString().padStart(2, '0')
        }
        s = EXTRACT_CENTS.replace(s) { m -> "¢" + m.groupValues[1].toInt().toString() }

        // write "one(s)" instead of "1(s)", just for the readability
        s = ONE_OR_ONES.replace(s, "one$1")
        return s
    }

    /** Python `__call__`: preprocess, process the words, join with single spaces, postprocess. */
    fun normalize(s: String): String {
        val pre = preprocess(s)
        val joined = processWords(pySplit(pre)).joinToString(" ")
        return postprocess(joined)
    }

    private companion object {
        val AND_A_HALF = Regex("${PY_B}and$PY_WS+a$PY_WS+half$PY_B")
        val NUMBER_THEN_LETTER_BOUNDARY = Regex("([a-z])([0-9])")
        val LETTER_THEN_NUMBER_BOUNDARY = Regex("([0-9])([a-z])")
        val SUFFIX_SPACE = Regex("([0-9])$PY_WS+(st|nd|rd|th|s)$PY_B")
        val COMBINE_CENTS = Regex("([€£$])([0-9]+) (?:and )?¢([0-9]{1,2})$PY_B")
        val EXTRACT_CENTS = Regex("[€£$]0[^\\n]([0-9]{1,2})$PY_B")
        val ONE_OR_ONES = Regex("${PY_B}1(s?)$PY_B")
    }
}
