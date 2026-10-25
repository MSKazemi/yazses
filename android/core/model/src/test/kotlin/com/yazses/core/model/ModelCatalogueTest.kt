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

    private fun idProblems(id: String): List<String> =
        problemsOf(catalogue(model(id = id))).filter { "model id" in it }

    @Test
    fun `an id that would escape the storage directory is rejected`() {
        assertTrue(idProblems("../../../x").isNotEmpty(), "traversal accepted")
        assertTrue(idProblems("..").isNotEmpty(), "bare dot-dot accepted")
        assertTrue(idProblems("a..b").isNotEmpty(), "embedded dot-dot accepted")
    }

    @Test
    fun `an id with a slash is rejected`() {
        assertTrue(idProblems("a/b").isNotEmpty(), "slash accepted")
        // The fixture embeds the id raw in JSON, so "\\\\" here is one escaped backslash there.
        assertTrue(idProblems("a\\\\b").isNotEmpty(), "backslash accepted")
    }

    @Test
    fun `an id with an upper-case letter is rejected`() {
        assertTrue(idProblems("Whisper-Base").isNotEmpty(), "upper-case accepted")
    }

    @Test
    fun `an empty id is rejected`() {
        assertTrue(idProblems("").isNotEmpty(), "empty accepted")
    }

    @Test
    fun `an id with a leading dot is rejected`() {
        assertTrue(idProblems(".hidden").isNotEmpty(), "leading dot accepted")
    }

    @Test
    fun `an id longer than 64 characters is rejected`() {
        assertTrue(idProblems("a".repeat(65)).isNotEmpty(), "65 characters accepted")
        ModelCatalogue.parse(catalogue(model(id = "a".repeat(64))))
    }

    @Test
    fun `a valid id is accepted`() {
        ModelCatalogue.parse(catalogue(model(id = "whisper-base.en-q5")))
    }

    @Test
    fun `a url with userinfo is rejected`() {
        val problems = problemsOf(catalogue(model(url = "https://user:pw@example.invalid/a.bin")))
        assertTrue(problems.any { "url" in it && "credentials" in it }, "got $problems")
    }

    @Test
    fun `localhost and loopback hosts are rejected`() {
        for (url in listOf(
            "https://localhost/a.bin",
            "https://LOCALHOST./a.bin",
            "https://sub.localhost/a.bin",
            "https://127.0.0.1/a.bin",
            "https://[::1]/a.bin",
        )) {
            val problems = problemsOf(catalogue(model(url = url)))
            assertTrue(problems.any { "url" in it }, "accepted '$url': $problems")
        }
    }

    @Test
    fun `a bare IP literal is rejected as a host`() {
        for (url in listOf("https://10.0.0.5/a.bin", "https://93.184.216.34/a.bin")) {
            val problems = problemsOf(catalogue(model(url = url)))
            assertTrue(problems.any { "url" in it }, "accepted '$url': $problems")
        }
    }

    @Test
    fun `every problem is reported at once`() {
        val problems = problemsOf(
            catalogue(model(size = "0", url = "http://example.invalid/a") + "," + model(sha = "xyz")),
        )
        assertTrue(problems.size >= 3, "expected several problems, got $problems")
    }
}
