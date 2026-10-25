package com.yazses.core.bench

import kotlin.test.Test
import kotlin.test.assertContains
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

// SYNTHETIC fixture throughout: invented names and numbers, not a device or a measurement.
class JsonWriterTest {

    private val zeros = "0".repeat(64)

    private fun record(
        peak: Reading<Long> = Reading.NotMeasured("synthetic: no memory probe in this fixture"),
        device: String = "SYNTHETIC-device",
    ) = BenchResult(
        device = DeviceInfo(device, Reading.Measured("SYNTHETIC-soc"), "SYNTHETIC-android"),
        engineId = "synthetic-engine",
        modelId = "synthetic-model",
        modelSha256 = zeros,
        threads = 2,
        clips = listOf(ClipResult("c1", 2.0, 1.0, 0.5)),
        peakRssBytes = peak,
    )

    @Test
    fun `golden output for a synthetic record is byte-exact`() {
        val expected = """
            {
              "schema": "yazses.bench.android/1",
              "device": {
                "model": "SYNTHETIC-device",
                "soc": "SYNTHETIC-soc",
                "soc_reason": null,
                "android": "SYNTHETIC-android"
              },
              "engine": {
                "id": "synthetic-engine",
                "model_id": "synthetic-model",
                "model_sha256": "$zeros"
              },
              "threads": 2,
              "peak_rss_bytes": null,
              "peak_rss_reason": "synthetic: no memory probe in this fixture",
              "aggregate": {
                "clips": 1,
                "audio_s": 2.000000,
                "wall_s": 1.000000,
                "rtf": 0.500000,
                "rtf_reason": null
              },
              "clips": [
                {
                  "id": "c1",
                  "audio_s": 2.000000,
                  "wall_s": 1.000000,
                  "rtf": 0.500000,
                  "rtf_reason": null
                }
              ]
            }
        """.trimIndent() + "\n"
        assertEquals(expected, BenchJson.write(record()))
    }

    @Test
    fun `writing the same record twice is byte-identical`() {
        assertEquals(BenchJson.write(record()), BenchJson.write(record()))
    }

    @Test
    fun `a not-measured peak is null with its reason, never zero`() {
        val json = BenchJson.write(record())
        assertTrue("\"peak_rss_bytes\": null" in json)
        assertFalse("\"peak_rss_bytes\": 0" in json)
    }

    @Test
    fun `a measured peak is written as an integer with no reason`() {
        val json = BenchJson.write(record(peak = Reading.Measured(123456789L)))
        assertTrue("\"peak_rss_bytes\": 123456789," in json)
        assertTrue("\"peak_rss_reason\": null" in json)
    }

    @Test
    fun `quotes and backslashes in strings are escaped`() {
        val json = BenchJson.write(record(device = "SYN\"THETIC\\x"))
        assertTrue("\"model\": \"SYN\\\"THETIC\\\\x\"" in json)
    }

    @Test
    fun `a clip with no audio writes rtf null with a reason, never a bare null`() {
        val r = record().copy(clips = listOf(ClipResult("z", 0.0, 0.0, null)))
        val expected = listOf(
            "  \"clips\": [",
            "    {",
            "      \"id\": \"z\",",
            "      \"audio_s\": 0.000000,",
            "      \"wall_s\": 0.000000,",
            "      \"rtf\": null,",
            "      \"rtf_reason\": \"no audio\"",
            "    }",
            "  ]",
        ).joinToString("\n")
        assertTrue(expected in BenchJson.write(r), BenchJson.write(r))
    }

    @Test
    fun `an aggregate with no audio writes rtf null with a reason`() {
        val r = record().copy(clips = listOf(ClipResult("z", 0.0, 0.0, null)))
        assertTrue("\"rtf\": null,\n    \"rtf_reason\": \"no audio\"\n  },\n  \"clips\"" in BenchJson.write(r), BenchJson.write(r))
    }

    @Test
    fun `a lone surrogate in a string is refused, since the format cannot store it`() {
        val e = assertFailsWith<IllegalArgumentException> { BenchJson.write(record(device = "SYN\uD800THETIC")) }
        assertContains(e.message.orEmpty(), "lone surrogate")
    }

    @Test
    fun `a valid surrogate pair in a string is kept as written`() {
        val pair = String(Character.toChars(0x2A700))
        assertTrue("\"model\": \"$pair\"" in BenchJson.write(record(device = pair)))
    }

    @Test
    fun `a record whose sums overflow is refused with the validator's error, not a NumberFormatException`() {
        val big = Double.MAX_VALUE
        val r = record().copy(clips = listOf(ClipResult("x", big, 1.0, 1.0 / big), ClipResult("y", big, 1.0, 1.0 / big)))
        // NumberFormatException is an IllegalArgumentException too, so the message is what proves the validator ran.
        val e = assertFailsWith<IllegalArgumentException> { BenchJson.write(r) }
        assertContains(e.message.orEmpty(), "aggregate audio_s is not finite")
    }

    @Test
    fun `the writer refuses a record that fails validation`() {
        val bad = record().copy(schema = "")
        assertFailsWith<IllegalArgumentException> { BenchJson.write(bad) }
    }
}
