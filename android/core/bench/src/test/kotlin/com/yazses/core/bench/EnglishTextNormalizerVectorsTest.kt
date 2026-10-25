package com.yazses.core.bench

import org.junit.jupiter.api.Assumptions.assumeFalse
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.DynamicTest.dynamicTest
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestFactory
import kotlin.test.assertEquals

/**
 * Replays the oracle's own outputs (wer-normalizer-vectors.json, generated from whisper-normalizer
 * 0.1.15 by scripts/gen-wer-normalizer-vectors.py) through [EnglishTextNormalizer].
 *
 * A vector is never edited to make it pass. [KNOWN_DIFFERENCES] is the only escape hatch: an id
 * goes there with a one-line reason only after its cause is shown to be irreducible, and
 * [knownDifferencesAreExact] fails the build if that set and the real mismatches disagree. The
 * target is an empty set.
 */
class EnglishTextNormalizerVectorsTest {

    private data class Vector(val id: String, val input: String, val expected: String)

    private class Mismatch(val vector: Vector, val actual: String)

    @TestFactory
    fun `each vector is replayed under its case id`(): List<DynamicTest> = vectors.map { v ->
        dynamicTest(v.id) {
            val reason = KNOWN_DIFFERENCES[v.id]
            assumeFalse(reason != null, "known difference: $reason")
            assertEquals(v.expected, EnglishTextNormalizer.normalize(v.input), "input=${show(v.input)}")
        }
    }

    @Test
    fun `summary counts every vector and the known differences are exactly the real mismatches`() {
        assertEquals(614, vectors.size, "the vector file must hold all 614 cases")
        val failing = vectors.mapNotNull { v ->
            val actual = EnglishTextNormalizer.normalize(v.input)
            if (actual == v.expected) null else Mismatch(v, actual)
        }
        val passing = vectors.size - failing.size
        val report = failing.take(30).joinToString("\n") { m ->
            "${m.vector.id}\n  input:    ${show(m.vector.input)}\n  expected: ${show(m.vector.expected)}\n  actual:   ${show(m.actual)}"
        }
        assertEquals(
            KNOWN_DIFFERENCES.keys.sorted(),
            failing.map { it.vector.id }.sorted(),
            "$passing/${vectors.size} vectors match. Mismatches not listed in KNOWN_DIFFERENCES (first 30):\n$report",
        )
        assertEquals(vectors.size - KNOWN_DIFFERENCES.size, passing, "pass count\n$report")
    }

    @Test
    fun `known differences name only ids that exist`() {
        val ids = vectors.map { it.id }.toSet()
        assertEquals(emptySet(), KNOWN_DIFFERENCES.keys - ids, "KNOWN_DIFFERENCES names an unknown id")
    }

    private fun show(s: String): String = "\"" + s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t") + "\""

    companion object {
        /** Vector id -> why it still differs from the oracle. Target: empty. */
        val KNOWN_DIFFERENCES: Map<String, String> = emptyMap()

        private val vectors: List<Vector> by lazy { load() }

        @Suppress("UNCHECKED_CAST") // the parser returns the record as Map/List; the shape is the vector file's
        private fun load(): List<Vector> {
            val text = EnglishTextNormalizerVectorsTest::class.java
                .getResourceAsStream("/wer-normalizer-vectors.json")
                ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }
                ?: throw IllegalStateException("wer-normalizer-vectors.json is missing from the test classpath")
            val doc = JsonParser(text, maxDepth = 4).parseDocument() as Map<String, Any?>
            val cases = doc.getValue("cases") as List<Map<String, Any?>>
            return cases.map { m ->
                Vector(m.getValue("id") as String, m.getValue("input") as String, m.getValue("expected") as String)
            }
        }
    }
}
