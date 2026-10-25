package com.yazses.core.bench

import kotlin.test.Test
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
                "rtf": 0.500000
              },
              "clips": [
                {
                  "id": "c1",
                  "audio_s": 2.000000,
                  "wall_s": 1.000000,
                  "rtf": 0.500000
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
    fun `the writer refuses a record that fails validation`() {
        val bad = record().copy(schema = "")
        assertFailsWith<IllegalArgumentException> { BenchJson.write(bad) }
    }
}
