package com.yazses.core.model

import java.io.InputStream
import java.security.MessageDigest
import java.util.HexFormat

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
     * This is a security event, not a transient failure: a corrupted or substituted
     * model. Delete the file, report it loudly, and never retry automatically.
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

    /** Streams [input] through SHA-256 and returns the lower-case hex digest. Does not close it. */
    public fun sha256Hex(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(BUFFER_BYTES)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
        return HexFormat.of().formatHex(digest.digest())
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

    /** [verify] for a digest the caller has already computed. [actual] must be lower-case hex. */
    public fun verifyDigest(
        catalogue: ModelCatalogue,
        actual: String,
        expected: ModelEntry? = null,
        unverified: UnverifiedAcknowledgement? = null,
    ): VerifyResult {
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
