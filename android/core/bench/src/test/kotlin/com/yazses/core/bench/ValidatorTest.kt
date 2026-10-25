package com.yazses.core.bench

import kotlin.test.Test
import kotlin.test.assertContains
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

// SYNTHETIC fixture: invented device and numbers, not a measurement.
class ValidatorTest {

    private val valid = BenchResult(
        device = DeviceInfo("SYNTHETIC-device", Reading.Measured("SYNTHETIC-soc"), "SYNTHETIC-android"),
        engineId = "synthetic-engine",
        modelId = "synthetic-model",
        modelSha256 = "a".repeat(64),
        threads = 4,
        clips = listOf(
            ClipResult("c1", 2.0, 1.0, 0.5),
            ClipResult("c2", 3.0, 1.0, 0.333333), // within 6-decimal rounding of 1/3
        ),
        peakRssBytes = Reading.NotMeasured("synthetic: no memory probe"),
    )

    private fun withClip(c: ClipResult) = valid.copy(clips = listOf(c))

    @Test
    fun `a consistent synthetic record has no violations`() {
        assertEquals(emptyList(), BenchValidator.violations(valid))
    }

    @Test
    fun `a missing schema version is rejected`() {
        assertContains(BenchValidator.violations(valid.copy(schema = "")), "schema: missing")
    }

    @Test
    fun `an unknown schema version is rejected`() {
        assertContains(
            BenchValidator.violations(valid.copy(schema = "yazses.bench.android/9")).joinToString("\n"),
            "expected yazses.bench.android/1",
        )
    }

    @Test
    fun `negative audio seconds are rejected`() {
        val v = BenchValidator.violations(withClip(ClipResult("c", -1.0, 1.0, null)))
        assertTrue(v.any { "audio_s must be finite and >= 0" in it })
    }

    @Test
    fun `negative wall seconds are rejected`() {
        val v = BenchValidator.violations(withClip(ClipResult("c", 1.0, -1.0, null)))
        assertTrue(v.any { "wall_s must be finite and >= 0" in it })
    }

    @Test
    fun `an rtf that disagrees with wall over audio is rejected`() {
        // SYNTHETIC: 1.0 s wall over 2.0 s audio is 0.5, not 0.25.
        val v = BenchValidator.violations(withClip(ClipResult("c", 2.0, 1.0, 0.25)))
        assertTrue(v.any { "inconsistent with wall_s/audio_s" in it })
    }

    @Test
    fun `an rtf missing for a clip with audio is rejected`() {
        assertTrue(BenchValidator.violations(withClip(ClipResult("c", 2.0, 1.0, null))).any { "rtf missing" in it })
    }

    @Test
    fun `an rtf on a clip with no audio is rejected, and a null one is accepted`() {
        assertTrue(BenchValidator.violations(withClip(ClipResult("c", 0.0, 1.0, 5.0))).any { "must be null" in it })
        assertEquals(emptyList(), BenchValidator.violations(withClip(ClipResult("c", 0.0, 0.0, null))))
    }

    @Test
    fun `a not-measured reading without a reason is rejected`() {
        val v = BenchValidator.violations(valid.copy(peakRssBytes = Reading.NotMeasured("  ")))
        assertTrue(v.any { "no reason given" in it })
    }

    @Test
    fun `a negative peak memory is rejected`() {
        val v = BenchValidator.violations(valid.copy(peakRssBytes = Reading.Measured(-1L)))
        assertTrue(v.any { "peakRssBytes: negative" in it })
    }

    @Test
    fun `a malformed sha256 is rejected`() {
        assertContains(BenchValidator.violations(valid.copy(modelSha256 = "ABC")).joinToString("\n"), "modelSha256")
    }

    @Test
    fun `zero threads is rejected`() {
        assertContains(BenchValidator.violations(valid.copy(threads = 0)).joinToString("\n"), "threads: must be >= 1")
    }

    @Test
    fun `a non-finite duration is rejected`() {
        assertTrue(BenchValidator.violations(withClip(ClipResult("c", 1.0, Double.NaN, null))).any { "finite" in it })
    }

    @Test
    fun `duplicate clip ids are rejected`() {
        val dup = valid.copy(clips = listOf(ClipResult("c", 1.0, 0.5, 0.5), ClipResult("c", 1.0, 0.5, 0.5)))
        assertContains(BenchValidator.violations(dup).joinToString("\n"), "duplicate clip id")
    }

    @Test
    fun `a clip whose name is a prefix of a reported clip still has its rtf checked`() {
        // SYNTHETIC: "a'b" has negative audio (reported); "a" has rtf 99.0 where 0.5 is expected.
        val r = valid.copy(clips = listOf(ClipResult("a'b", -1.0, 1.0, null), ClipResult("a", 2.0, 1.0, 99.0)))
        assertTrue(BenchValidator.violations(r).any { it.startsWith("clip 'a': rtf 99.0") })
    }

    @Test
    fun `a record with no clips is rejected`() {
        assertContains(BenchValidator.violations(valid.copy(clips = emptyList())), "clips: no clips")
    }

    @Test
    fun `a duration that rounds to zero at 6 decimals is rejected`() {
        val v = BenchValidator.violations(withClip(ClipResult("c", 4e-7, 1.0, null)))
        assertTrue(v.any { "below the 1 microsecond resolution" in it }, v.joinToString("\n"))
    }

    @Test
    fun `a clip whose written durations disagree with its rtf is rejected`() {
        // SYNTHETIC: 1.5e-6 s is written as 0.000002, so 1.0 / 0.000002 = 500000, not 666666.67.
        val v = BenchValidator.violations(withClip(ClipResult("c", 1.5e-6, 1.0, 666666.67)))
        assertTrue(v.any { "inconsistent with" in it }, v.joinToString("\n"))
    }

    @Test
    fun `aggregate sums that overflow to infinity are rejected before the writer sees them`() {
        val big = Double.MAX_VALUE
        val r = valid.copy(clips = listOf(ClipResult("x", big, 1.0, 1.0 / big), ClipResult("y", big, 1.0, 1.0 / big)))
        assertTrue(BenchValidator.violations(r).any { "aggregate audio_s is not finite" in it })
    }

    @Test
    fun `require throws and names the violations`() {
        val e = assertFailsWith<IllegalArgumentException> { BenchValidator.require(valid.copy(schema = "")) }
        assertContains(e.message.orEmpty(), "schema: missing")
    }

    @Test
    fun `a measured zero peak is rejected, because a running process always has some resident memory`() {
        val v = BenchValidator.violations(valid.copy(peakRssBytes = Reading.Measured(0L)))
        assertContains(v.joinToString("\n"), "peak_rss_bytes must be positive when measured; use null with a reason")
    }

    @Test
    fun `more than 5000 clips is a violation, the most one record can hold`() {
        val clips = (0..MAX_CLIPS).map { ClipResult("c$it", 2.0, 1.0, 0.5) }
        assertContains(BenchValidator.violations(valid.copy(clips = clips)).joinToString("\n"), "more than 5000 clips")
    }

    @Test
    fun `a duration with more than six decimals is a violation, since the format cannot store it`() {
        val v = BenchValidator.violations(withClip(ClipResult("c", 1.0000001, 1.0, 1.0)))
        assertTrue(v.any { "finer than" in it || "6 decimals" in it }, v.joinToString("\n"))
    }

    @Test
    fun `an rtf with more than six decimals is a violation`() {
        val v = BenchValidator.violations(withClip(ClipResult("c", 3.0, 1.0, 0.3333333333)))
        assertTrue(v.any { "rtf" in it && "6 decimals" in it }, v.joinToString("\n"))
    }

    @Test
    fun `negative zero is a violation, because it does not survive the round trip`() {
        val v = BenchValidator.violations(withClip(ClipResult("c", 2.0, -0.0, 0.0)))
        assertTrue(v.any { "negative zero" in it }, v.joinToString("\n"))
    }

    @Test
    fun `a lone surrogate in a stored string is a violation`() {
        val v = BenchValidator.violations(valid.copy(engineId = "syn\uD800thetic"))
        assertContains(v.joinToString("\n"), "lone surrogate")
    }
}
