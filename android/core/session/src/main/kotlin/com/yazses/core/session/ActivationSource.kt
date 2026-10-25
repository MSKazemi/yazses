// The activation seam: what turns a user's gesture into "start capture" and "stop capture".
//
// ADR-MOB-004 §7 ("The activation source is an interface, not a hard-wired listener"):
// the IME key, the media button, the bubble and a switch are all implementations. A source
// emits hold edges; the session behind it does not know which source produced them.
//
// Two pure implementations live here:
//   - HoldKeySource: press-and-hold (ADR-MOB-004 §1). Down starts, up ends.
//   - ToggleSource: tap to start, tap again to stop, with a hard cap (ADR-MOB-004 §2).
//
// No clock is read. Every call carries the timestamp the caller observed, and the cap is
// driven by onTick, so a test moves time with plain numbers.
package com.yazses.core.session

/** One edge a source asks the session to act on. */
public sealed interface ActivationEdge {
    /** Begin a burst: the session should treat this as a key-down. */
    public data object HoldStart : ActivationEdge

    /** End the burst: the session should treat this as a key-up, with the audio captured so far. */
    public data class HoldEnd(public val cause: EndCause) : ActivationEdge
}

/** Why a burst ended. Lets the UI say why the mic closed. */
public enum class EndCause {
    /** Hold mode: the finger came up. */
    KEY_UP,

    /** Toggle mode: the user tapped again. */
    SECOND_ACTIVATION,

    /** Toggle mode: the hard cap was reached and the burst was force-stopped. */
    CAP_REACHED,

    /** A secure field aborted the burst, and its audio was discarded (architecture.md §6). */
    SECURE_ABORT,
}

/**
 * A source of activation gestures. Each method returns the edges the session must receive,
 * in order. An empty list means "nothing to do".
 */
public interface ActivationSource {
    /** The activation gesture began: key down, or a tap. */
    public fun onHoldStart(atMs: Long): List<ActivationEdge>

    /** The activation gesture ended: key up. Toggle sources ignore it. */
    public fun onHoldEnd(atMs: Long): List<ActivationEdge>

    /** Time advanced to [nowMs]. Sources with a time limit emit their end edge here. */
    public fun onTick(nowMs: Long): List<ActivationEdge>

    /** Forgets any gesture in progress. Called when the session is cancelled. */
    public fun reset()
}

/** Press-and-hold. The burst lives exactly as long as the key is down (ADR-MOB-004 §1). */
public class HoldKeySource : ActivationSource {
    private var down = false

    override fun onHoldStart(atMs: Long): List<ActivationEdge> {
        if (down) return emptyList() // a key-repeat while held
        down = true
        return listOf(ActivationEdge.HoldStart)
    }

    override fun onHoldEnd(atMs: Long): List<ActivationEdge> {
        if (!down) return emptyList()
        down = false
        return listOf(ActivationEdge.HoldEnd(EndCause.KEY_UP))
    }

    override fun onTick(nowMs: Long): List<ActivationEdge> = emptyList()

    override fun reset() {
        down = false
    }
}

/**
 * Tap to start, tap again to stop (ADR-MOB-004 §2).
 *
 * A burst that runs for [maxBurstMs] is force-stopped by [onTick] with
 * [EndCause.CAP_REACHED]. The cap is measured from the activation that started the burst,
 * and it fires at exactly [maxBurstMs], not one millisecond later. Release events are
 * ignored: a toggle does not care when the finger leaves the key.
 *
 * @param maxBurstMs the hard cap. The default is the shared desktop key
 *   `[audio] max_record_seconds = 300`, per the ADR-MOB-004 erratum (2026-10).
 */
public class ToggleSource(public val maxBurstMs: Long = DEFAULT_MAX_BURST_MS) : ActivationSource {
    init {
        require(maxBurstMs > 0) { "maxBurstMs must be > 0, was $maxBurstMs" }
    }

    private var running = false
    private var startedAtMs = 0L

    override fun onHoldStart(atMs: Long): List<ActivationEdge> {
        if (!running) {
            running = true
            startedAtMs = atMs
            return listOf(ActivationEdge.HoldStart)
        }
        // A tap after the cap, with no tick in between, still reports the cap, not the tap.
        val cause = if (atMs - startedAtMs >= maxBurstMs) EndCause.CAP_REACHED else EndCause.SECOND_ACTIVATION
        running = false
        return listOf(ActivationEdge.HoldEnd(cause))
    }

    override fun onHoldEnd(atMs: Long): List<ActivationEdge> = emptyList()

    override fun onTick(nowMs: Long): List<ActivationEdge> {
        if (!running || nowMs - startedAtMs < maxBurstMs) return emptyList()
        running = false
        return listOf(ActivationEdge.HoldEnd(EndCause.CAP_REACHED))
    }

    override fun reset() {
        running = false
    }

    public companion object {
        /** `[audio] max_record_seconds = 300`, in milliseconds. */
        public const val DEFAULT_MAX_BURST_MS: Long = 300_000L
    }
}
