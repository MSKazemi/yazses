package com.yazses.core.bench

import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue
import kotlin.test.fail

// SYNTHETIC fixtures throughout: invented names and numbers, not a device or a measurement.
class JsonReaderTest {

    private val zeros = "0".repeat(64)

    private fun record(
        peak: Reading<Long> = Reading.NotMeasured("synthetic: no memory probe"),
        soc: Reading<String> = Reading.Measured("SYNTHETIC-soc"),
        device: String = "SYNTHETIC-device",
        engine: String = "synthetic-engine",
        clips: List<ClipResult> = listOf(ClipResult("c1", 2.0, 1.0, 0.5)),
    ) = BenchResult(
        device = DeviceInfo(device, soc, "SYNTHETIC-android"),
        engineId = engine,
        modelId = "synthetic-model",
        modelSha256 = zeros,
        threads = 2,
        clips = clips,
        peakRssBytes = peak,
    )

    /**
     * The same record, written by hand in one line so every malformed case is a one-substring
     * edit of it. The malformed-input test first proves the base is accepted, so a rejection means the edit did it.
     */
    private val base =
        """{"schema":"yazses.bench.android/1","device":{"model":"SYNTHETIC-device","soc":"SYNTHETIC-soc","soc_reason":null,"android":"SYNTHETIC-android"},"engine":{"id":"synthetic-engine","model_id":"synthetic-model","model_sha256":"$zeros"},"threads":2,"peak_rss_bytes":null,"peak_rss_reason":"synthetic: no memory probe","aggregate":{"clips":1,"audio_s":2.000000,"wall_s":1.000000,"rtf":0.500000,"rtf_reason":null},"clips":[{"id":"c1","audio_s":2.000000,"wall_s":1.000000,"rtf":0.500000,"rtf_reason":null}]}"""

    private fun edit(old: String, new: String): String {
        require(base.split(old).size == 2) { "fixture edit '$old' must occur exactly once in the base" }
        return base.replace(old, new)
    }

    private fun okOf(text: String): BenchResult =
        assertIs<ReadResult.Ok>(BenchJson.read(text), "expected Ok").result

    @Test
    fun `the hand-written base is accepted and reads as the synthetic record`() {
        val r = okOf(base)
        assertEquals(record(), r)
        assertEquals(Reading.NotMeasured("synthetic: no memory probe"), r.peakRssBytes)
    }

    @Test
    fun `write then read round-trips over representative records`() {
        val records = listOf(
            record(),
            record(peak = Reading.Measured(123456789L)),
            record(soc = Reading.NotMeasured("synthetic: SoC string not exposed")),
            record(device = "测试设备 テスト 한국어", engine = "quote\" back\\slash tab\t nl\n ctl\u0001 é"),
            record(clips = listOf(ClipResult("z", 0.0, 0.0, null), ClipResult("p", 3.0, 1.0, 0.333333))),
            record(clips = listOf(ClipResult("a", 0.0, 0.0, null))),
            record(clips = listOf(ClipResult("clip-😀-𠀀", 2.0, 1.0, 0.5))),
        )
        for (r in records) {
            val text = BenchJson.write(r)
            val back = okOf(text)
            assertEquals(r, back, "record read back differs")
            assertEquals(text, BenchJson.write(back), "write(read(write(x))) differs from write(x)")
        }
    }

    @Test
    fun `a reading key absent from the file is rejected, and the problem names the key`() {
        val peakReasonGone = okOrRejected(edit(",\"peak_rss_reason\":\"synthetic: no memory probe\"", ""))
        assertTrue(peakReasonGone.any { it == "missing field: peak_rss_reason" }, peakReasonGone.toString())

        val socGone = okOrRejected(edit("\"soc\":\"SYNTHETIC-soc\",\"soc_reason\":null,", ""))
        assertTrue(socGone.any { it == "missing field: device.soc" }, socGone.toString())
        assertTrue(socGone.any { it == "missing field: device.soc_reason" }, socGone.toString())
    }

    @Test
    fun `an explicit null with a reason is the only not-measured form, and it is never zero`() {
        val peak = okOf(base).peakRssBytes
        assertEquals(Reading.NotMeasured("synthetic: no memory probe"), peak)
        assertNotEquals<Reading<Long>>(Reading.Measured(0L), peak)
    }

    @Test
    fun `a misspelt reason key reports both the missing key and the unknown one`() {
        val problems = okOrRejected(edit("\"soc_reason\":null", "\"soc_reasn\":null"))
        assertTrue(problems.any { it == "missing field: device.soc_reason" }, problems.toString())
        assertTrue(problems.any { it == "unknown field: device.soc_reasn" }, problems.toString())
    }

    @Test
    fun `an unknown top-level field is rejected and named`() {
        val problems = okOrRejected(edit("\"threads\":2,", "\"threads\":2,\"future\":true,"))
        assertEquals(listOf("unknown field: future"), problems)
    }

    @Test
    fun `an integer-valued duration written without decimals is accepted, so write of read is not always identical to the input`() {
        val text = edit("\"id\":\"c1\",\"audio_s\":2.000000", "\"id\":\"c1\",\"audio_s\":2")
        assertEquals(record(), okOf(text))
        assertTrue(BenchJson.write(okOf(text)) != text)
    }

    /** The problems of a rejected text; fails the test if the text is accepted. */
    private fun okOrRejected(text: String): List<String> =
        assertIs<ReadResult.Rejected>(BenchJson.read(text), "expected Rejected").problems

    private data class Case(val name: String, val text: String, val fragment: String)

    @Test
    fun `malformed and inconsistent inputs are all rejected without throwing`() {
        assertIs<ReadResult.Ok>(BenchJson.read(base), "control must be accepted")
        val cases = listOf(
            Case("empty text", "", "unexpected end"),
            Case("whitespace only", "   \n\t ", "unexpected end"),
            Case("truncated halfway", base.take(base.length / 2), "not valid JSON"),
            Case("missing closing brace", base.dropLast(1), "unexpected end"),
            Case("trailing garbage", base + "x", "trailing"),
            Case("two documents", base + base, "trailing"),
            Case("byte order mark", "\uFEFF" + base, "byte order mark"),
            Case("NaN token", edit("\"threads\":2", "\"threads\":NaN"), "unexpected character"),
            Case("Infinity token", edit("\"threads\":2", "\"threads\":Infinity"), "unexpected character"),
            Case("negative Infinity token", edit("\"threads\":2", "\"threads\":-Infinity"), "invalid number"),
            Case("duplicate key", edit("\"threads\":2", "\"threads\":2,\"threads\":3"), "duplicate key 'threads'"),
            Case("invalid escape", edit("\"synthetic-engine\"", "\"syn\\qthetic\""), "invalid escape"),
            Case("short unicode escape", edit("\"synthetic-engine\"", "\"syn\\u12\""), "unicode escape"),
            Case("non-hex unicode escape", edit("\"synthetic-engine\"", "\"syn\\uZZZZ\""), "unicode escape"),
            Case("lone high surrogate escape", edit("\"synthetic-engine\"", "\"syn\\uD800\""), "lone surrogate"),
            Case("lone low surrogate escape", edit("\"synthetic-engine\"", "\"syn\\uDC00\""), "lone surrogate"),
            Case("raw lone surrogate", edit("\"synthetic-engine\"", "\"syn\uD800\""), "lone surrogate"),
            Case("raw control character", edit("\"synthetic-engine\"", "\"syn\u0001\""), "control character"),
            Case("threads as a string", edit("\"threads\":2", "\"threads\":\"2\""), "threads"),
            Case("threads fractional", edit("\"threads\":2", "\"threads\":2.0"), "threads"),
            Case("threads exponent", edit("\"threads\":2", "\"threads\":2e0"), "threads"),
            Case("threads overflows Int", edit("\"threads\":2", "\"threads\":99999999999999999999"), "threads"),
            Case("threads with a leading zero", edit("\"threads\":2", "\"threads\":02"), "expected"),
            Case("threads with a plus sign", edit("\"threads\":2", "\"threads\":+2"), "unexpected character"),
            Case("threads zero", edit("\"threads\":2", "\"threads\":0"), "threads: must be"),
            Case("threads negative zero", edit("\"threads\":2", "\"threads\":-0"), "got -0"),
            Case(
                "peak negative zero",
                edit("\"peak_rss_bytes\":null,\"peak_rss_reason\":\"synthetic: no memory probe\"", "\"peak_rss_bytes\":-0,\"peak_rss_reason\":null"),
                "got -0",
            ),
            Case("peak measured with a reason set", edit("\"peak_rss_bytes\":null", "\"peak_rss_bytes\":0"), "measured, so"),
            Case(
                "peak null with no reason",
                edit("\"peak_rss_reason\":\"synthetic: no memory probe\"", "\"peak_rss_reason\":null"),
                "gives no reason",
            ),
            Case(
                "peak reason blank",
                edit("\"peak_rss_reason\":\"synthetic: no memory probe\"", "\"peak_rss_reason\":\"  \""),
                "is blank",
            ),
            Case(
                "peak negative",
                edit("\"peak_rss_bytes\":null,\"peak_rss_reason\":\"synthetic: no memory probe\"", "\"peak_rss_bytes\":-1,\"peak_rss_reason\":null"),
                "negative",
            ),
            Case("negative clip audio", edit("\"id\":\"c1\",\"audio_s\":2.000000", "\"id\":\"c1\",\"audio_s\":-2.000000"), "audio_s must be finite"),
            Case("clip rtf inconsistent", edit("\"rtf\":0.500000,\"rtf_reason\":null}]", "\"rtf\":0.250000,\"rtf_reason\":null}]"), "inconsistent"),
            Case(
                "clip rtf null for audio",
                edit("\"rtf\":0.500000,\"rtf_reason\":null}]", "\"rtf\":null,\"rtf_reason\":\"no audio\"}]"),
                "rtf missing",
            ),
            Case(
                "clip rtf number with reason set",
                edit("\"rtf\":0.500000,\"rtf_reason\":null}]", "\"rtf\":0.500000,\"rtf_reason\":\"no audio\"}]"),
                "measured, so",
            ),
            Case("clip rtf null with no reason", edit("\"rtf\":0.500000,\"rtf_reason\":null}]", "\"rtf\":null,\"rtf_reason\":null}]"), "no audio"),
            Case("unknown schema", edit("yazses.bench.android/1", "yazses.bench.android/2"), "expected yazses.bench.android/1"),
            Case("missing schema", edit("\"schema\":\"yazses.bench.android/1\",", ""), "missing field: schema"),
            Case("schema is a number", edit("\"schema\":\"yazses.bench.android/1\"", "\"schema\":1"), "schema"),
            Case("missing clips", edit(",\"clips\":[{\"id\":\"c1\",\"audio_s\":2.000000,\"wall_s\":1.000000,\"rtf\":0.500000,\"rtf_reason\":null}]", ""), "missing field: clips"),
            Case("engine is null", edit("\"engine\":{\"id\":\"synthetic-engine\",\"model_id\":\"synthetic-model\",\"model_sha256\":\"$zeros\"}", "\"engine\":null"), "engine"),
            Case("sha256 in capitals", edit(zeros, "A".repeat(64)), "modelSha256"),
            Case("aggregate clip count wrong", edit("\"clips\":1,", "\"clips\":2,"), "aggregate.clips"),
            Case(
                "aggregate wall tampered",
                edit("\"wall_s\":1.000000,\"rtf\":0.500000,\"rtf_reason\":null},\"clips\"", "\"wall_s\":9.000000,\"rtf\":0.500000,\"rtf_reason\":null},\"clips\""),
                "aggregate.wall_s",
            ),
            Case(
                "aggregate rtf tampered",
                edit("\"rtf\":0.500000,\"rtf_reason\":null},\"clips\"", "\"rtf\":0.250000,\"rtf_reason\":null},\"clips\""),
                "aggregate.rtf",
            ),
            Case("root is an array", "[]", "expected an object"),
            Case("root is a string", "\"record\"", "expected an object"),
            Case("nesting past the depth limit", "[".repeat(65) + "]".repeat(65), "nesting deeper than 64"),
            Case(
                "nesting inside an unknown field",
                edit("\"threads\":2,", "\"threads\":2,\"deep\":" + "[".repeat(100) + "]".repeat(100) + ","),
                "nesting deeper than 64",
            ),
            Case("deleted threads", edit("\"threads\":2,", ""), "missing field: threads"),
            Case("deleted peak_rss_bytes", edit("\"peak_rss_bytes\":null,", ""), "missing field: peak_rss_bytes"),
            Case("deleted engine model_id", edit("\"model_id\":\"synthetic-model\",", ""), "missing field: engine.model_id"),
            Case("deleted aggregate wall_s", edit("\"wall_s\":1.000000,\"rtf\":0.500000,\"rtf_reason\":null},\"clips\"", "\"rtf\":0.500000,\"rtf_reason\":null},\"clips\""), "missing field: aggregate.wall_s"),
            Case("deleted clip rtf_reason", edit("\"rtf\":0.500000,\"rtf_reason\":null}]", "\"rtf\":0.500000}]"), "missing field: clips[0].rtf_reason"),
            Case("misspelt peak reason key", edit("\"peak_rss_reason\"", "\"peak_rss_reasn\""), "unknown field: peak_rss_reasn"),
            Case("extra field in device", edit("\"android\":\"SYNTHETIC-android\"}", "\"android\":\"SYNTHETIC-android\",\"extra\":1}"), "unknown field: device.extra"),
            Case("extra field in engine", edit("\"model_sha256\":\"$zeros\"}", "\"model_sha256\":\"$zeros\",\"extra\":1}"), "unknown field: engine.extra"),
            Case("extra field in aggregate", edit("\"rtf_reason\":null},\"clips\"", "\"rtf_reason\":null,\"extra\":1},\"clips\""), "unknown field: aggregate.extra"),
            Case("extra field in a clip", edit("\"rtf_reason\":null}]", "\"rtf_reason\":null,\"extra\":1}]"), "unknown field: clips[0].extra"),
            Case("extra field at top level", edit("\"threads\":2,", "\"threads\":2,\"future\":true,"), "unknown field: future"),
            Case("text over the size limit", " ".repeat(MAX_READ_CHARS + 1) + base, "over the"),
        )
        for (c in cases) {
            val result = try {
                BenchJson.read(c.text)
            } catch (e: Throwable) {
                fail("${c.name}: read() threw ${e::class.simpleName}: ${e.message}")
            }
            val rejected = assertIs<ReadResult.Rejected>(result, "${c.name}: must be Rejected, got $result")
            assertTrue(rejected.problems.isNotEmpty(), "${c.name}: Rejected with no problems")
            assertTrue(
                rejected.problems.any { c.fragment in it },
                "${c.name}: no problem mentions '${c.fragment}': ${rejected.problems}",
            )
        }
        assertTrue(cases.size >= 25, "table must hold at least 25 malformed inputs, has ${cases.size}")
    }

    private fun mutate(src: String, rnd: Random, alphabet: String): String {
        var s = src
        repeat(1 + rnd.nextInt(3)) {
            if (s.isEmpty()) return s
            val pos = rnd.nextInt(s.length)
            val ch = alphabet[rnd.nextInt(alphabet.length)]
            s = when (rnd.nextInt(4)) {
                0 -> s.substring(0, pos) + ch + s.substring(pos + 1)
                1 -> s.substring(0, pos) + s.substring(pos + 1)
                2 -> s.substring(0, pos) + ch + s.substring(pos)
                else -> s.substring(0, pos)
            }
        }
        return s
    }

    @Test
    fun `seeded fuzz of 2000 mutated records never throws and is Ok that re-validates or Rejected`() {
        val seeds = listOf(
            BenchJson.write(record()),
            BenchJson.write(record(peak = Reading.Measured(123L))),
            BenchJson.write(record(clips = listOf(ClipResult("z", 0.0, 0.0, null), ClipResult("p", 3.0, 1.0, 0.333333)))),
        )
        val alphabet = "{}[]\":,.-+eE0123456789truefalsnNI \\\n\u0000𐀀\uFEFFé测"
        val rnd = Random(92)
        var ok = 0
        var rejected = 0
        val iterations = 2000
        repeat(iterations) { iter ->
            val text = mutate(seeds[rnd.nextInt(seeds.size)], rnd, alphabet)
            val result = try {
                BenchJson.read(text)
            } catch (e: Throwable) {
                fail("iteration $iter: read() threw ${e::class.simpleName}: ${e.message}; input=${text.take(200)}")
            }
            when (result) {
                is ReadResult.Ok -> {
                    val v = BenchValidator.violations(result.result)
                    assertEquals(emptyList(), v, "iteration $iter: Ok record fails validation; input=${text.take(200)}")
                    BenchJson.write(result.result)
                    ok++
                }
                is ReadResult.Rejected -> {
                    assertTrue(result.problems.isNotEmpty(), "iteration $iter: Rejected with no problems")
                    rejected++
                }
            }
        }
        println("fuzz: iterations=$iterations ok=$ok rejected=$rejected")
        assertEquals(iterations, ok + rejected)
        assertTrue(ok > 0 && rejected > 0, "fuzz is degenerate: ok=$ok rejected=$rejected")
    }
}
