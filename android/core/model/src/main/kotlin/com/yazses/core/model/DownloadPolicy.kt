package com.yazses.core.model

/** The network the device is on, as reported by a platform layer injected from outside. */
public enum class NetworkKind { UNMETERED, METERED, NONE }

/**
 * The user's download settings.
 *
 * Defaults: [wifiOnly] is true (ADR-MOB-006 §3, "Wi-Fi-only by default"). Turning it off is
 * what allows a metered (mobile data) download. [allowOnLowBattery] is false. ADR-MOB-006
 * does not mention battery; this default is an inference, chosen so that a download never
 * starts silently on a nearly dead phone.
 */
public data class DownloadSettings(
    val wifiOnly: Boolean = true,
    val allowOnLowBattery: Boolean = false,
)

/** What the download job should do right now. */
public sealed interface DownloadDecision {
    public object Start : DownloadDecision

    /** Not now: the condition may clear by itself, so the job stays queued. */
    public data class Wait(val reason: WaitReason) : DownloadDecision

    /** Never, for this request: retrying cannot change the answer. */
    public data class Refuse(val reason: RefuseReason) : DownloadDecision
}

public enum class WaitReason {
    /** The user has not tapped to start this download yet (ADR-MOB-006 section 2). */
    NEEDS_CONFIRMATION,
    NO_NETWORK,
    WAITING_FOR_WIFI,
    BATTERY_LOW,
}

public sealed interface RefuseReason {
    /** The URL fails the catalogue's own https/host rule ([ModelCatalogue]). */
    public data class UnsafeSource(val problem: String) : RefuseReason

    /** The entry is not, field for field, an entry of the catalogue it claims to come from. */
    public object NotInCatalogue : RefuseReason

    /**
     * The last attempt for this id ended in a checksum mismatch. A mismatch is a security event
     * and is never retried automatically (ADR-MOB-006 section 3). The caller must clear the id
     * only through a deliberate user action, which this module does not model.
     */
    public object PREVIOUS_MISMATCH : RefuseReason
}

/** Pure download policy (ADR-MOB-006 §3). Nothing here starts, schedules or performs I/O. */
public object DownloadPolicy {

    /**
     * Decides whether [entry] may be downloaded now, in this order:
     *
     * 1. Refusals, which no setting or network can override: an unsafe URL, an entry that is not
     *    the catalogue's own, and an id in [previousMismatchFor].
     * 2. [userConfirmed]: false gives [WaitReason.NEEDS_CONFIRMATION]. ADR-MOB-006 section 2
     *    requires an explicit tap before the first download, and that includes mobile data. The
     *    caller sets it to true only after the user has seen the size and tapped, and it must
     *    never be inferred from a settings switch.
     * 3. The network and battery conditions.
     *
     * There is no default for [userConfirmed] or [previousMismatchFor], so a caller cannot
     * forget them. The policy stores nothing: the caller supplies the mismatch set from its own
     * record of past attempts.
     */
    public fun decide(
        catalogue: ModelCatalogue,
        entry: ModelEntry,
        settings: DownloadSettings,
        network: NetworkKind,
        batteryLow: Boolean,
        userConfirmed: Boolean,
        previousMismatchFor: Set<String>,
    ): DownloadDecision {
        ModelCatalogue.urlProblem(entry.url)?.let { return DownloadDecision.Refuse(RefuseReason.UnsafeSource(it)) }
        if (catalogue.byId(entry.id) != entry) return DownloadDecision.Refuse(RefuseReason.NotInCatalogue)
        if (entry.id in previousMismatchFor) return DownloadDecision.Refuse(RefuseReason.PREVIOUS_MISMATCH)
        if (!userConfirmed) return DownloadDecision.Wait(WaitReason.NEEDS_CONFIRMATION)
        return when {
            network == NetworkKind.NONE -> DownloadDecision.Wait(WaitReason.NO_NETWORK)
            network == NetworkKind.METERED && settings.wifiOnly -> DownloadDecision.Wait(WaitReason.WAITING_FOR_WIFI)
            batteryLow && !settings.allowOnLowBattery -> DownloadDecision.Wait(WaitReason.BATTERY_LOW)
            else -> DownloadDecision.Start
        }
    }
}
