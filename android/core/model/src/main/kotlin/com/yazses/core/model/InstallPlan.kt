package com.yazses.core.model

/**
 * Where a model install stands. The order is fixed by ADR-MOB-006 §3:
 * download to a temporary name, verify, and only then rename into place. Nothing becomes
 * visible under its final name except through [InstallOutcome.Installed].
 */
public sealed interface InstallStep {
    /** Bytes are being written to [tempName]. */
    public data class Downloading(val entry: ModelEntry, val tempName: String) : InstallStep

    /** The complete temporary file is being checked against [entry]. */
    public data class Verifying(val entry: ModelEntry, val tempName: String) : InstallStep

    /** Terminal. The caller acts on [outcome]: rename, or delete the temporary file. */
    public data class Finished(val outcome: InstallOutcome) : InstallStep
}

/**
 * The terminal decision for one install. [Installed] is the only outcome that permits a
 * rename into place. Every [Rejected] outcome means the temporary file (or the user's
 * sideloaded file) must not be used, and a [Rejected.Mismatch] is also a security event.
 *
 * What is guaranteed: [InstallPlan] produces [Installed] only from a [VerifyResult] it is
 * handed that is [VerifyResult.Verified], or [VerifyResult.UnknownSideload] together with an
 * [UnverifiedAcknowledgement]. The caller must obtain that result from [ModelVerifier].
 *
 * What is not guaranteed: the [Installed] and [Rejected] subclasses have `internal`
 * constructors, which stops Kotlin code in other modules from building them directly. That
 * is not a hard boundary, since bytecode and reflection can reach `internal` members, and
 * [VerifyResult.Verified] has a public constructor, so any caller can build one with any
 * entry and pass it in. The check is on the state machine's own paths, not on the provenance
 * of the result.
 */
public sealed interface InstallOutcome {

    public sealed interface Installed : InstallOutcome {
        /** The bytes match a catalogue entry. */
        public class Verified internal constructor(val entry: ModelEntry) : Installed

        /** A sideloaded file that is not in the catalogue, accepted by explicit acknowledgement. */
        public class UnverifiedSideload internal constructor(val sha256: String) : Installed
    }

    public sealed interface Rejected : InstallOutcome {
        /** Substituted or corrupted model: delete the temporary file and report, never retry. */
        public class Mismatch internal constructor(val expected: String, val actual: String) : Rejected

        /** The digest is malformed, so it names no file. Fails closed. */
        public class InvalidDigest internal constructor(val actual: String) : Rejected

        /** A file not in the catalogue, and the user did not accept it as unverified. */
        public class Unverified internal constructor(val actual: String) : Rejected

        /** The verifier said "unknown, accepted as unverified", but no acknowledgement was given here. */
        public class AckMissing internal constructor(val actual: String) : Rejected

        /** The result was produced for a different model than the one being installed. */
        public class WrongModel internal constructor(val detail: String) : Rejected
    }
}

/**
 * The safe install ordering as pure transitions. No I/O: the caller writes the temporary
 * file, computes its digest with [ModelVerifier], renames on [InstallOutcome.Installed],
 * and deletes on [InstallOutcome.Rejected].
 */
public object InstallPlan {

    /**
     * Starts a download of [entry]. The entry must be the catalogue's own and its URL must
     * pass the catalogue's https rule ([ModelCatalogue]). Both are programming errors when
     * they fail, because the caller chose the entry.
     */
    public fun begin(catalogue: ModelCatalogue, entry: ModelEntry): InstallStep.Downloading {
        require(ModelCatalogue.urlProblem(entry.url) == null) {
            "download source for '${entry.id}' is not allowed: ${ModelCatalogue.urlProblem(entry.url)}"
        }
        require(catalogue.byId(entry.id) == entry) {
            "entry '${entry.id}' is not an entry of this catalogue"
        }
        val tempName = tempNameFor(entry)
        require(catalogue.models.none { it.id == tempName }) {
            "temporary name '$tempName' would overwrite a model of the same name"
        }
        return InstallStep.Downloading(entry, tempName)
    }

    /**
     * `<id>.<first 12 digest characters>.part`. The digest prefix means a catalogue that changes
     * the digest under the same id gets a new temporary name, so stale partial bytes are never
     * resumed into a different model. The `.part` suffix is reserved by [ModelCatalogue.validate],
     * so no final model name can equal this name.
     */
    public fun tempNameFor(entry: ModelEntry): String =
        entry.id + "." + entry.sha256.take(TEMP_DIGEST_CHARS) + ModelCatalogue.TEMP_SUFFIX

    private const val TEMP_DIGEST_CHARS: Int = 12

    /** The temporary file is complete; it is now checked. */
    public fun downloaded(step: InstallStep.Downloading): InstallStep.Verifying =
        InstallStep.Verifying(step.entry, step.tempName)

    /**
     * Ends a download. [result] must come from [ModelVerifier] run with `expected = step.entry`.
     * A result that is about a different model, or that a download can never produce (a
     * sideload classification), is [InstallOutcome.Rejected.WrongModel].
     */
    public fun verified(
        step: InstallStep.Verifying,
        result: VerifyResult,
        ack: UnverifiedAcknowledgement? = null,
    ): InstallStep.Finished {
        val outcome = when {
            result is VerifyResult.Verified && result.entry != step.entry ->
                InstallOutcome.Rejected.WrongModel("verified as '${result.entry.id}', expected '${step.entry.id}'")
            result is VerifyResult.Mismatch && result.expected != step.entry.sha256 ->
                InstallOutcome.Rejected.WrongModel("checked against a digest that is not '${step.entry.id}'")
            result is VerifyResult.UnknownSideload || result is VerifyResult.UnverifiedRefused ->
                InstallOutcome.Rejected.WrongModel("a download was classified as a sideload")
            else -> outcomeOf(result, ack)
        }
        return InstallStep.Finished(outcome)
    }

    /**
     * Maps any [VerifyResult] to its outcome. Only [VerifyResult.Verified], or an
     * [VerifyResult.UnknownSideload] that comes with [ack], produce [InstallOutcome.Installed].
     * The result must come from [ModelVerifier]; this function cannot check that it did.
     */
    public fun outcomeOf(result: VerifyResult, ack: UnverifiedAcknowledgement?): InstallOutcome = when (result) {
        is VerifyResult.Verified -> InstallOutcome.Installed.Verified(result.entry)
        is VerifyResult.Mismatch -> InstallOutcome.Rejected.Mismatch(result.expected, result.actual)
        is VerifyResult.UnknownSideload ->
            if (ack != null) InstallOutcome.Installed.UnverifiedSideload(result.actual)
            else InstallOutcome.Rejected.AckMissing(result.actual)
        is VerifyResult.UnverifiedRefused -> InstallOutcome.Rejected.Unverified(result.actual)
        is VerifyResult.InvalidDigest -> InstallOutcome.Rejected.InvalidDigest(result.actual)
    }
}
