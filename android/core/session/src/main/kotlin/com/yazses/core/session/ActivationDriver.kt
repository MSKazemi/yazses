// Feeds an ActivationSource's edges into a HoldSession. Pure Kotlin, no clock, no audio.
//
// Every source reaches the session through this one path, so after activation the session
// treats hold, toggle and any later source identically: same debounce rules (set on the
// session), same queue, same secure-field refusal, same silent-burst discard.
package com.yazses.core.session

/**
 * @param session the burst state machine. A toggle source needs a session with
 *   `debounceMs = 0`: a tap is the activation, and the hold debounce does not apply to it
 *   (ADR-MOB-004 §1 scopes the debounce to press-and-hold).
 * @param source the gesture source. Swapping it changes how a burst starts and ends, and
 *   nothing else.
 */
public class ActivationDriver(
    private val session: HoldSession,
    private val source: ActivationSource,
) {
    /**
     * The activation gesture began at [atMs]. A press in a secure field is refused before the
     * source sees it, so a refused tap changes no source state.
     *
     * [snapshot] returns the audio recorded so far. It is only called when a toggle tap
     * stops the burst.
     */
    public fun onPress(
        atMs: Long,
        fieldIsSecure: Boolean = false,
        snapshot: () -> FloatArray = NO_AUDIO,
    ): List<SessionEffect> {
        if (fieldIsSecure && session.state != SessionState.Capturing) {
            return session.onPress(atMs, fieldIsSecure = true)
        }
        return apply(source.onHoldStart(atMs), atMs, snapshot)
    }

    /** The activation gesture ended at [atMs]. A toggle source ignores it. */
    public fun onRelease(atMs: Long, samples: FloatArray): List<SessionEffect> =
        apply(source.onHoldEnd(atMs), atMs) { samples }

    /**
     * Time advanced to [nowMs]. The caller must call this while a burst may be running, as
     * it does for [HoldSession.onTick]. [snapshot] is called only when the cap fires.
     */
    public fun onTick(nowMs: Long, snapshot: () -> FloatArray = NO_AUDIO): List<SessionEffect> =
        apply(source.onTick(nowMs), nowMs, snapshot) + session.onTick(nowMs)

    /** The decoder produced [text]. Passed through to [HoldSession.onDecoded]. */
    public fun onDecoded(text: String, fieldIsSecure: Boolean, nowMs: Long): List<SessionEffect> =
        session.onDecoded(text, fieldIsSecure, nowMs)

    /** The decoder failed. Passed through to [HoldSession.onDecodeFailed]. */
    public fun onDecodeFailed(nowMs: Long): List<SessionEffect> = session.onDecodeFailed(nowMs)

    /** The text was inserted, or went to the clipboard. Passed through to [HoldSession.onDelivered]. */
    public fun onDelivered(inserted: Boolean, nowMs: Long): List<SessionEffect> =
        session.onDelivered(inserted, nowMs)

    /** Abandons the burst in the session and forgets the source's gesture. */
    public fun cancel(nowMs: Long): List<SessionEffect> {
        source.reset()
        return session.cancel(nowMs)
    }

    private fun apply(
        edges: List<ActivationEdge>,
        atMs: Long,
        snapshot: () -> FloatArray,
    ): List<SessionEffect> {
        val out = mutableListOf<SessionEffect>()
        for (edge in edges) {
            out += when (edge) {
                // A start is a key-down. The debounce, if any, is the session's own rule.
                ActivationEdge.HoldStart -> session.onPress(atMs) + session.onTick(atMs)
                // An end is a key-up carrying the audio. Every cause ends the burst the same way.
                is ActivationEdge.HoldEnd -> session.onRelease(atMs, snapshot())
            }
        }
        return out
    }

    private companion object {
        private val NO_AUDIO: () -> FloatArray = { FloatArray(0) }
    }
}
