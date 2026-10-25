package com.yazses.core.bench

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

// Adversarial inputs for the "never throws, bounded output" claim. Each one runs in the test JVM's
// default heap; the reader must come back Rejected with a short, bounded list, not an exception.
class JsonReaderLimitsTest {

    private val head = """{"schema":"yazses.bench.android/1","""

    private fun rejected(text: String): ReadResult.Rejected {
        val r = try {
            BenchJson.read(text)
        } catch (e: Throwable) {
            throw AssertionError("BenchJson.read threw ${e::class.simpleName}: ${e.message}", e)
        }
        return assertIs<ReadResult.Rejected>(r, "expected Rejected")
    }

    private fun assertBounded(r: ReadResult.Rejected) {
        assertTrue(r.problems.isNotEmpty(), "Rejected with no problems")
        assertTrue(r.problems.size <= 101, "problem list has ${r.problems.size} entries, over 101")
        assertTrue(r.problems.all { it.length <= 400 }, "a problem message is not bounded in length")
    }

    @Test
    fun `a 1 MiB clips array of empty objects is refused by the element cap`() {
        val n = (MAX_READ_CHARS - head.length - 20) / 3
        val text = head + "\"clips\":[" + "{},".repeat(n) + "{}]}"
        assertTrue(text.length <= MAX_READ_CHARS)
        val r = rejected(text)
        assertBounded(r)
        assertEquals(1, r.problems.size)
        assertTrue("more than 10000 elements" in r.problems.single(), r.problems.single())
    }

    @Test
    fun `700k unknown keys are refused by the size limit, because they cannot fit in 1 MiB`() {
        val text = head + (0 until 700_000).joinToString(",", prefix = "", postfix = "}") { "\"k$it\":0" }
        assertTrue(text.length > MAX_READ_CHARS)
        val r = rejected(text)
        assertBounded(r)
        assertEquals(1, r.problems.size)
        assertTrue("over the" in r.problems.single(), r.problems.single())
    }

    @Test
    fun `1001 unknown keys in one object are refused by the member cap`() {
        val text = "{" + (0..1000).joinToString(",") { "\"k$it\":0" } + "}"
        assertTrue(text.length < MAX_READ_CHARS)
        val r = rejected(text)
        assertBounded(r)
        assertEquals(1, r.problems.size)
        assertTrue("more than 1000 members" in r.problems.single(), r.problems.single())
    }

    @Test
    fun `a 1 MiB run of open brackets is refused by the depth limit`() {
        val text = "[".repeat(MAX_READ_CHARS)
        val r = rejected(text)
        assertBounded(r)
        assertEquals(1, r.problems.size)
        assertTrue("nesting deeper than 64" in r.problems.single(), r.problems.single())
    }

    @Test
    fun `a 1 MiB digit string in a field is refused, and the echo is truncated`() {
        val text = head + "\"threads\":" + "1".repeat(MAX_READ_CHARS - head.length - 40) + "}"
        assertTrue(text.length <= MAX_READ_CHARS)
        val r = rejected(text)
        assertBounded(r)
        val threads = r.problems.single { it.startsWith("threads: expected an integer") }
        assertTrue(threads.length <= 100, "echo was not truncated: ${threads.length} characters")
        assertTrue(threads.endsWith("…"), threads)
    }

    @Test
    fun `problems past the cap are summed exactly into one final entry`() {
        // 7 top-level fields missing (schema, threads, peak value and reason, device, engine, aggregate),
        // then 5 per empty clip (id, audio_s, wall_s, rtf, rtf_reason): 7 + 5 * 30 = 157 problems.
        val text = "{\"clips\":[" + "{},".repeat(29) + "{}]}"
        val r = rejected(text)
        assertEquals(101, r.problems.size)
        assertEquals("and 57 more problems", r.problems.last())
        assertTrue(r.problems.take(100).none { it.startsWith("and ") })
    }

    @Test
    fun `a problem list under the cap is returned whole, with no summary entry`() {
        val r = rejected("{\"threads\":2}")
        assertTrue(r.problems.none { it.startsWith("and ") }, r.problems.toString())
        assertTrue(r.problems.size < 100)
    }

    @Test
    fun `a 1 MiB number in a clip duration is refused without an exception`() {
        val digits = "9".repeat(MAX_READ_CHARS - 200)
        val withDigits = "{\"clips\":[{\"id\":\"c\",\"audio_s\":$digits,\"wall_s\":1.0,\"rtf\":null,\"rtf_reason\":\"no audio\"}]}"
        assertTrue(withDigits.length <= MAX_READ_CHARS)
        assertBounded(rejected(withDigits))
        val withExponent = "{\"clips\":[{\"id\":\"c\",\"audio_s\":1e$digits,\"wall_s\":1.0,\"rtf\":null,\"rtf_reason\":\"no audio\"}]}"
        assertTrue(withExponent.length <= MAX_READ_CHARS)
        assertBounded(rejected(withExponent))
    }
}
