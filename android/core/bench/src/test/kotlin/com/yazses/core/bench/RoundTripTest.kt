package com.yazses.core.bench

import java.math.BigDecimal
import java.math.RoundingMode
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertContains
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue

// SYNTHETIC fixtures throughout. Covers the write-side ceiling and the claim that read(write(x)) == x
// for every record write() accepts.
class RoundTripTest {

    private val zeros = "0".repeat(64)

    private fun record(
        clips: List<ClipResult>,
        peak: Reading<Long> = Reading.NotMeasured("synthetic: no memory probe"),
        device: String = "SYNTHETIC-device",
    ) = BenchResult(
        device = DeviceInfo(device, Reading.Measured("SYNTHETIC-soc"), "SYNTHETIC-android"),
        engineId = "synthetic-engine",
        modelId = "synthetic-model",
        modelSha256 = zeros,
        threads = 2,
        clips = clips,
        peakRssBytes = peak,
    )

    private fun clipsOf(n: Int) = (0 until n).map { ClipResult("c$it", 2.0, 1.0, 0.5) }

    @Test
    fun `write accepts 5000 clips and the output reads back equal`() {
        val r = record(clipsOf(MAX_CLIPS))
        val text = BenchJson.write(r)
        assertTrue(text.length <= MAX_READ_CHARS)
        val back = assertIs<ReadResult.Ok>(BenchJson.read(text)).result
        assertEquals(r, back)
    }

    @Test
    fun `write refuses 5001 clips with the ceiling named`() {
        val e = assertFailsWith<IllegalArgumentException> { BenchJson.write(record(clipsOf(MAX_CLIPS + 1))) }
        assertContains(e.message.orEmpty(), "more than 5000 clips")
    }

    @Test
    fun `read refuses 5001 clips with a named problem`() {
        val clip = """{"id":"c","audio_s":2.000000,"wall_s":1.000000,"rtf":0.500000,"rtf_reason":null}"""
        val text = """{"clips":[""" + List(MAX_CLIPS + 1) { clip }.joinToString(",") + "]}"
        val r = assertIs<ReadResult.Rejected>(BenchJson.read(text))
        assertTrue(r.problems.any { "more than 5000 clips" in it }, r.problems.toString())
        assertTrue(r.problems.size <= 101)
    }

    @Test
    fun `write refuses a record whose output would exceed the 1 MiB reader limit`() {
        // 5000 clips, each with a 300-character id: about 2 MB of text, within the clip ceiling.
        val clips = (0 until MAX_CLIPS).map { ClipResult("c$it".padEnd(300, 'x'), 2.0, 1.0, 0.5) }
        val e = assertFailsWith<IllegalArgumentException> { BenchJson.write(record(clips)) }
        assertContains(e.message.orEmpty(), "over the reader's limit of $MAX_READ_CHARS")
    }

    @Test
    fun `write refuses a duration with more than six decimals`() {
        val e = assertFailsWith<IllegalArgumentException> {
            BenchJson.write(record(listOf(ClipResult("c", 1.0000001, 1.0, 1.0))))
        }
        assertContains(e.message.orEmpty(), "audio_s")
    }

    @Test
    fun `write refuses an rtf with more than six decimals`() {
        val e = assertFailsWith<IllegalArgumentException> {
            BenchJson.write(record(listOf(ClipResult("c", 3.0, 1.0, 0.3333333333))))
        }
        assertContains(e.message.orEmpty(), "rtf")
    }

    @Test
    fun `write refuses a measured zero peak`() {
        val e = assertFailsWith<IllegalArgumentException> {
            BenchJson.write(record(clipsOf(1), peak = Reading.Measured(0L)))
        }
        assertContains(e.message.orEmpty(), "peak_rss_bytes must be positive when measured")
    }

    private fun round6(x: Double): Double = BigDecimal(x).setScale(6, RoundingMode.HALF_UP).toDouble()

    private fun text(rnd: Random): String {
        val pieces = listOf(
            "a", "Z", " ", "\"", "\\", "\n", "\t", "\u0001", "测", "テ", "한", "é",
            "😀", "𠀀", "/", "{", "}", " ",
        )
        return "s" + (0 until 1 + rnd.nextInt(12)).joinToString("") { pieces[rnd.nextInt(pieces.size)] }
    }

    /** A random record built on the writer's resolution, so every one is accepted by [BenchJson.write]. */
    private fun randomRecord(rnd: Random): BenchResult {
        val clips = (0 until 1 + rnd.nextInt(20)).map { i ->
            val wall = round6(rnd.nextDouble() * 100)
            val audio = if (rnd.nextInt(8) == 0) 0.0 else round6(rnd.nextDouble() * 100)
            val rtf = if (audio == 0.0) null else round6(wall / audio)
            ClipResult("c$i-" + text(rnd), audio, wall, rtf)
        }
        val peak: Reading<Long> = if (rnd.nextBoolean()) {
            Reading.Measured(1L + rnd.nextLong(1_000_000_000L))
        } else {
            Reading.NotMeasured(text(rnd))
        }
        val soc: Reading<String> = if (rnd.nextBoolean()) Reading.Measured(text(rnd)) else Reading.NotMeasured(text(rnd))
        return BenchResult(
            device = DeviceInfo(text(rnd), soc, text(rnd)),
            engineId = text(rnd),
            modelId = text(rnd),
            modelSha256 = (0 until 64).joinToString("") { "0123456789abcdef"[rnd.nextInt(16)].toString() },
            threads = 1 + rnd.nextInt(8),
            clips = clips,
            peakRssBytes = peak,
        )
    }

    @Test
    fun `seeded property - every record write accepts reads back equal, and writes back identically`() {
        val rnd = Random(92)
        repeat(300) { iter ->
            val r = randomRecord(rnd)
            val text = BenchJson.write(r)
            val back = assertIs<ReadResult.Ok>(BenchJson.read(text), "iteration $iter").result
            assertEquals(r, back, "iteration $iter: read(write(x)) != x")
            assertEquals(text, BenchJson.write(back), "iteration $iter: write(read(write(x))) != write(x)")
        }
    }
}
