package com.yazses.core.model

import java.io.ByteArrayInputStream
import java.io.File
import java.security.MessageDigest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue

class ModelVerifierTest {

    // Synthetic fixtures: SHA-256("hello") and SHA-256("abc"). Not real model digests.
    private val helloSha = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    private val abcSha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    private val hello = ModelEntry(
        id = "synthetic-hello", displayName = "Synthetic hello", engine = "whisper.cpp",
        sizeBytes = 5, sha256 = helloSha, licence = "MIT", url = "https://example.invalid/hello.bin",
    )
    private val catalogue = ModelCatalogue.parse(
        """{"schemaVersion": 1, "models": [{"id": "synthetic-hello", "displayName": "Synthetic hello",
           "engine": "whisper.cpp", "sizeBytes": 5, "sha256": "$helloSha", "licence": "MIT",
           "url": "https://example.invalid/hello.bin"}]}""",
    )

    private fun stream(text: String) = ByteArrayInputStream(text.toByteArray(Charsets.UTF_8))

    @Test
    fun `the streamed digest matches the known vector`() {
        assertEquals(abcSha, ModelVerifier.sha256Hex(stream("abc")))
    }

    @Test
    fun `a stream larger than one buffer matches a one-shot digest`() {
        val bytes = ByteArray(200_003) { (it * 31 + 7).toByte() }
        val oneShot = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }
        assertEquals(oneShot, ModelVerifier.sha256Hex(ByteArrayInputStream(bytes)))
    }

    @Test
    fun `no java API newer than Android API 26 is referenced in the module`() {
        // The JVM test run cannot see an API-level crash (the JDK has every class), so this
        // scans main sources only. Gradle runs tests with the module directory as the working directory.
        val forbidden = listOf(
            "HexFormat", "java.util.stream", "java.util.Optional", "java.nio.file",
            "java.time", "java.util.concurrent.Flow", ".readString(", "List.of(", "Map.of(", "Set.of(",
        )
        val sources = File("src/main").walk().filter { it.isFile && it.extension == "kt" }.toList()
        assertTrue(sources.isNotEmpty(), "no main sources found under ${File(".").absolutePath}")
        val hits = sources.flatMap { file ->
            file.readLines().mapIndexedNotNull { i, line ->
                forbidden.firstOrNull { it in line }?.let { "${file.path}:${i + 1} uses $it" }
            }
        }
        assertEquals(emptyList(), hits)
    }

    @Test
    fun `the hand-written hex encoder matches sha256sum for hello`() {
        assertEquals(helloSha, ModelVerifier.sha256Hex(stream("hello")))
    }

    @Test
    fun `an empty stream has the well-known empty-input digest`() {
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            ModelVerifier.sha256Hex(ByteArrayInputStream(ByteArray(0))),
        )
    }

    @Test
    fun `a 200 KB repeating pattern streams to the same digest as a one-shot hash`() {
        val pattern = byteArrayOf(0x00, 0x7F, -0x80, -0x01, 0x42)
        val bytes = ByteArray(200 * 1024) { pattern[it % pattern.size] }
        val oneShot = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }
        assertEquals(oneShot, ModelVerifier.sha256Hex(ByteArrayInputStream(bytes)))
    }

    @Test
    fun `an upper-case digest never verifies, even against the right model`() {
        val result = ModelVerifier.verifyDigest(catalogue, helloSha.uppercase(), expected = hello)
        assertIs<VerifyResult.InvalidDigest>(result)
        assertEquals(helloSha.uppercase(), result.actual)
    }

    @Test
    fun `an upper-case digest with the unverified marker is not an unknown sideload`() {
        val result = ModelVerifier.verifyDigest(
            catalogue, abcSha.uppercase(), unverified = UnverifiedAcknowledgement,
        )
        assertIs<VerifyResult.InvalidDigest>(result)
    }

    @Test
    fun `an empty digest with the unverified marker fails closed`() {
        val result = ModelVerifier.verifyDigest(catalogue, "", unverified = UnverifiedAcknowledgement)
        assertIs<VerifyResult.InvalidDigest>(result)
    }

    @Test
    fun `a short or non-hex digest fails closed`() {
        for (bad in listOf(abcSha.take(63), abcSha + "0", abcSha.dropLast(1) + "g")) {
            val result = ModelVerifier.verifyDigest(catalogue, bad, unverified = UnverifiedAcknowledgement)
            assertIs<VerifyResult.InvalidDigest>(result, "accepted '$bad'")
        }
    }

    @Test
    fun `a file whose bytes match a catalogue entry is verified`() {
        val result = ModelVerifier.verify(catalogue, stream("hello"))
        assertEquals(VerifyResult.Verified(hello), result)
    }

    @Test
    fun `a known model whose bytes differ is a mismatch, carrying both digests`() {
        val result = ModelVerifier.verify(catalogue, stream("abc"), expected = hello)
        assertEquals(VerifyResult.Mismatch(expected = helloSha, actual = abcSha), result)
    }

    @Test
    fun `a known model that matches is verified even if unverified was also passed`() {
        val result = ModelVerifier.verify(
            catalogue, stream("hello"), expected = hello, unverified = UnverifiedAcknowledgement,
        )
        assertEquals(VerifyResult.Verified(hello), result)
    }

    @Test
    fun `an unknown file is accepted only with the explicit unverified marker`() {
        val result = ModelVerifier.verify(catalogue, stream("abc"), unverified = UnverifiedAcknowledgement)
        assertEquals(VerifyResult.UnknownSideload(abcSha), result)
    }

    @Test
    fun `an unknown file without the marker is refused, not accepted`() {
        val result = ModelVerifier.verify(catalogue, stream("abc"))
        assertIs<VerifyResult.UnverifiedRefused>(result)
        assertEquals(abcSha, result.actual)
    }

    @Test
    fun `the marker wording is the one the user must accept`() {
        assertEquals("unverified — you supplied this", UnverifiedAcknowledgement.LABEL)
    }

    @Test
    fun `an expected entry from another catalogue is a programming error`() {
        val other = hello.copy(id = "not-in-this-catalogue")
        assertFailsWith<IllegalArgumentException> {
            ModelVerifier.verify(catalogue, stream("hello"), expected = other)
        }
    }
}
