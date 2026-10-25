package com.yazses.core.model

/**
 * What to do with a partial download, given the bytes already on disk.
 *
 * Pure: the caller reads the partial file's length and the server's range support, and
 * performs the request or truncation itself. A plan never asks for a byte at or past the
 * declared size, and a partial file longer than that is reported as [Corrupt] rather than
 * resumed.
 */
public sealed interface ResumePlan {

    /** Download from byte 0. The caller must truncate any partial file first. */
    public object FromStart : ResumePlan

    /** Request bytes from [offset] (inclusive) to the end. [offset] is always in 1 until size. */
    public data class ResumeFrom(val offset: Long) : ResumePlan

    /** The partial file is the whole file. It still needs SHA-256 verification before use. */
    public object AlreadyComplete : ResumePlan

    /** The partial file is longer than the catalogue says the model is. Discard it. */
    public data class Corrupt(val partialBytes: Long, val expectedBytes: Long) : ResumePlan

    public companion object {
        /**
         * @param partialBytes length of the partial file on disk, zero when there is none.
         * @param expectedSizeBytes [ModelEntry.sizeBytes] from the catalogue, positive.
         * @param serverSupportsRanges whether the server answered range requests.
         */
        public fun plan(partialBytes: Long, expectedSizeBytes: Long, serverSupportsRanges: Boolean): ResumePlan {
            require(expectedSizeBytes > 0) { "expectedSizeBytes must be positive, was $expectedSizeBytes" }
            require(partialBytes >= 0) { "partialBytes must not be negative, was $partialBytes" }
            return when {
                partialBytes > expectedSizeBytes -> Corrupt(partialBytes, expectedSizeBytes)
                partialBytes == expectedSizeBytes -> AlreadyComplete
                partialBytes == 0L -> FromStart
                serverSupportsRanges -> ResumeFrom(partialBytes)
                else -> FromStart
            }
        }
    }
}
