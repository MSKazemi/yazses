package com.yazses.core.model

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class ModelCatalogueTest {

    // Synthetic fixture: the digest is SHA-256("hello"), not a real model's.
    private val helloSha = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    private fun catalogue(models: String) = """{"schemaVersion": 1, "models": [$models]}"""

    private fun model(
        id: String = "synthetic-a",
        sha: String = helloSha,
        size: String = "5",
        url: String = "https://example.invalid/synthetic-a.bin",
    ) = """{"id": "$id", "displayName": "Synthetic A", "engine": "whisper.cpp",
        "sizeBytes": $size, "sha256": "$sha", "licence": "MIT", "url": "$url"}"""

    private fun problemsOf(text: String): List<String> =
        assertFailsWith<CatalogueException> { ModelCatalogue.parse(text) }.problems

    @Test
    fun `the shipped catalogue parses and is valid`() {
        // Gradle runs tests with the module directory as the working directory.
        val shipped = File("../../app/src/main/assets/models.json")
        val catalogue = ModelCatalogue.parse(shipped.readText())
        assertEquals(emptyList(), catalogue.models, "no checksum is sourced yet, so the list is empty")
    }

    @Test
    fun `a valid entry parses and can be looked up by id`() {
        val parsed = ModelCatalogue.parse(catalogue(model()))
        val entry = parsed.byId("synthetic-a")
        assertEquals(helloSha, entry?.sha256)
        assertEquals(5L, entry?.sizeBytes)
        assertEquals(null, parsed.byId("absent"))
    }

    @Test
    fun `an empty models array is a valid catalogue`() {
        assertEquals(emptyList(), ModelCatalogue.parse(catalogue("")).models)
    }

    @Test
    fun `a plain http url is rejected`() {
        val problems = problemsOf(catalogue(model(url = "http://example.invalid/a.bin")))
        assertTrue(problems.any { "https://" in it }, "got $problems")
    }

    @Test
    fun `a url with no scheme or host is rejected`() {
        assertTrue(problemsOf(catalogue(model(url = "example.invalid/a.bin"))).isNotEmpty())
        assertTrue(problemsOf(catalogue(model(url = "https:///a.bin"))).isNotEmpty())
    }

    @Test
    fun `an https url is accepted`() {
        ModelCatalogue.parse(catalogue(model(url = "HTTPS://example.invalid/a.bin")))
    }

    @Test
    fun `duplicate ids are rejected`() {
        val problems = problemsOf(
            catalogue(model(id = "dup", sha = helloSha) + "," + model(id = "dup", sha = "a".repeat(64))),
        )
        assertTrue(problems.any { "duplicate id 'dup'" in it }, "got $problems")
    }

    @Test
    fun `two entries sharing a digest are rejected as ambiguous`() {
        val problems = problemsOf(
            catalogue(model(id = "one") + "," + model(id = "two")),
        )
        assertTrue(problems.any { "share one sha256" in it }, "got $problems")
    }

    @Test
    fun `malformed hashes are rejected`() {
        val bad = listOf(
            helloSha.uppercase(),        // upper-case hex
            helloSha.take(63),           // too short
            helloSha + "0",              // too long
            helloSha.dropLast(1) + "g",  // not hex
            "",
        )
        for (sha in bad) {
            val problems = problemsOf(catalogue(model(sha = sha)))
            assertTrue(problems.any { "64 lower-case hex" in it }, "accepted '$sha': $problems")
        }
    }

    @Test
    fun `non-positive sizes are rejected`() {
        assertTrue(problemsOf(catalogue(model(size = "0"))).any { "sizeBytes must be positive" in it })
        assertTrue(problemsOf(catalogue(model(size = "-1"))).any { "sizeBytes must be positive" in it })
    }

    @Test
    fun `a file missing a required field is rejected, not defaulted`() {
        val noSha = """{"schemaVersion": 1, "models": [{"id": "x", "displayName": "X",
            "engine": "e", "sizeBytes": 1, "licence": "MIT", "url": "https://example.invalid/x"}]}"""
        assertTrue(problemsOf(noSha).single().startsWith("malformed catalogue"))
    }

    @Test
    fun `an unsupported schema version is rejected`() {
        val text = """{"schemaVersion": 2, "models": []}"""
        assertTrue(problemsOf(text).single().contains("schemaVersion 2"))
    }

    @Test
    fun `every problem is reported at once`() {
        val problems = problemsOf(
            catalogue(model(size = "0", url = "http://example.invalid/a") + "," + model(sha = "xyz")),
        )
        assertTrue(problems.size >= 3, "expected several problems, got $problems")
    }
}
