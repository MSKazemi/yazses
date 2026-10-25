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

public enum class WaitReason { NO_NETWORK, WAITING_FOR_WIFI, BATTERY_LOW }

public sealed interface RefuseReason {
    /** The URL fails the catalogue's own https/host rule ([ModelCatalogue]). */
    public data class UnsafeSource(val problem: String) : RefuseReason

    /** The entry is not, field for field, an entry of the catalogue it claims to come from. */
    public object NotInCatalogue : RefuseReason
}

/** Pure download policy (ADR-MOB-006 §3). Nothing here starts, schedules or performs I/O. */
public object DownloadPolicy {

    /**
     * Decides whether [entry] may be downloaded now. Source checks come first and cannot be
     * overridden by any network or setting: a request that is refused is refused everywhere.
     */
    public fun decide(
        catalogue: ModelCatalogue,
        entry: ModelEntry,
        settings: DownloadSettings,
        network: NetworkKind,
        batteryLow: Boolean,
    ): DownloadDecision {
        ModelCatalogue.urlProblem(entry.url)?.let { return DownloadDecision.Refuse(RefuseReason.UnsafeSource(it)) }
        if (catalogue.byId(entry.id) != entry) return DownloadDecision.Refuse(RefuseReason.NotInCatalogue)
        return when {
            network == NetworkKind.NONE -> DownloadDecision.Wait(WaitReason.NO_NETWORK)
            network == NetworkKind.METERED && settings.wifiOnly -> DownloadDecision.Wait(WaitReason.WAITING_FOR_WIFI)
            batteryLow && !settings.allowOnLowBattery -> DownloadDecision.Wait(WaitReason.BATTERY_LOW)
            else -> DownloadDecision.Start
        }
    }
}
