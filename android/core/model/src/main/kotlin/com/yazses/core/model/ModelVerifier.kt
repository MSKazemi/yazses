package com.yazses.core.model

import java.io.InputStream
import java.security.MessageDigest

/**
 * The outcome of checking a model file's bytes. Every branch is a decision the
 * download and sideload code must handle explicitly; there is no "other" case.
 */
public sealed interface VerifyResult {

    /** The bytes match [entry]. The file may be made visible. */
    public data class Verified(val entry: ModelEntry) : VerifyResult

    /**
     * The file was supposed to be [expected] and its bytes differ.
     *
     * The caller must treat this as a security event (a corrupted or substituted model),
     * not a transient failure, and must not retry. This module only returns the result;
     * it deletes and reports nothing itself.
     */
    public data class Mismatch(val expected: String, val actual: String) : VerifyResult

    /**
     * The bytes are not in the catalogue, and the user explicitly accepted them as
     * unverified ([UnverifiedAcknowledgement]). The file is usable but carries no
     * checksum guarantee.
     */
    public data class UnknownSideload(val actual: String) : VerifyResult

    /**
     * The bytes are not in the catalogue and the user did not accept them as
     * unverified. The file must not be used.
     */
    public data class UnverifiedRefused(val actual: String) : VerifyResult

    /**
     * The digest handed to [ModelVerifier.verifyDigest] is not 64 lower-case hex
     * characters, so it cannot name any file. Fails closed: the file must not be used,
     * whatever the acknowledgement says.
     */
    public data class InvalidDigest(val actual: String) : VerifyResult
}

/**
 * The user's explicit acceptance of an unverified model file. The UI passes this only
 * after the user has seen and accepted [LABEL]. Passing it is what turns an unknown file
 * into [VerifyResult.UnknownSideload] instead of a refusal.
 */
public object UnverifiedAcknowledgement {
    /** The words the user must have been shown and accepted. */
    public const val LABEL: String = "unverified — you supplied this"
}

/**
 * Verifies model files against the catalogue. Pure: the bytes come in through an
 * injected [InputStream], and nothing is read from disk or the network here.
 */
public object ModelVerifier {

    private const val BUFFER_BYTES = 64 * 1024
    private const val HEX_DIGITS = "0123456789abcdef"
    private val SHA256_HEX = Regex("^[0-9a-f]{64}$")

    /** Streams [input] through SHA-256 and returns the lower-case hex digest. Does not close it. */
    public fun sha256Hex(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(BUFFER_BYTES)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
        return toLowerHex(digest.digest())
    }

    // Hand-written: the JDK's built-in hex formatter is Android API 34 and would crash on
    // minSdk 26 (ADR-MOB-006). Two characters per byte, high nibble first.
    private fun toLowerHex(bytes: ByteArray): String {
        val out = CharArray(bytes.size * 2)
        for (i in bytes.indices) {
            val v = bytes[i].toInt() and 0xFF
            out[2 * i] = HEX_DIGITS[v ushr 4]
            out[2 * i + 1] = HEX_DIGITS[v and 0x0F]
        }
        return String(out)
    }

    /**
     * Verifies the stream's bytes.
     *
     * - [expected] given (the caller is downloading or re-checking a known model): the
     *   digest must equal `expected.sha256`, or the result is [VerifyResult.Mismatch].
     *   [unverified] is ignored here, because a known model is never accepted unverified.
     * - [expected] null (a sideload): a catalogue match gives [VerifyResult.Verified];
     *   otherwise [unverified] decides between [VerifyResult.UnknownSideload] and
     *   [VerifyResult.UnverifiedRefused].
     *
     * @throws IllegalArgumentException when [expected] is not an entry of [catalogue].
     */
    public fun verify(
        catalogue: ModelCatalogue,
        input: InputStream,
        expected: ModelEntry? = null,
        unverified: UnverifiedAcknowledgement? = null,
    ): VerifyResult = verifyDigest(catalogue, sha256Hex(input), expected, unverified)

    /**
     * [verify] for a digest the caller has already computed. A [actual] that is not 64
     * lower-case hex characters gives [VerifyResult.InvalidDigest] before anything else is
     * checked, so a malformed digest can never verify or become an unknown sideload.
     */
    public fun verifyDigest(
        catalogue: ModelCatalogue,
        actual: String,
        expected: ModelEntry? = null,
        unverified: UnverifiedAcknowledgement? = null,
    ): VerifyResult {
        if (!SHA256_HEX.matches(actual)) return VerifyResult.InvalidDigest(actual)
        if (expected != null) {
            require(catalogue.byId(expected.id) == expected) {
                "expected model '${expected.id}' is not an entry of this catalogue"
            }
            return if (actual == expected.sha256) {
                VerifyResult.Verified(expected)
            } else {
                VerifyResult.Mismatch(expected.sha256, actual)
            }
        }
        val known = catalogue.models.firstOrNull { it.sha256 == actual }
        return when {
            known != null -> VerifyResult.Verified(known)
            unverified != null -> VerifyResult.UnknownSideload(actual)
            else -> VerifyResult.UnverifiedRefused(actual)
        }
    }
}
