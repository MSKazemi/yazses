// Feeds an ActivationSource's edges into a HoldSession. Pure Kotlin, no clock, no audio.
//
// Every source reaches the session through this one path, so after activation the session
// treats hold, toggle and any later source identically: same debounce rules (set on the
// session), same queue, same secure-field abort, same silent-burst discard.
package com.yazses.core.session

/**
 * @param session the burst state machine. A toggle source needs a session with
 *   `debounceMs = 0`: a tap is the activation, and the hold debounce does not apply to it
 *   (ADR-MOB-004 §1 scopes the debounce to press-and-hold).
 * @param source the gesture source. Swapping it changes how a burst starts and ends, and
 *   nothing else.
 *
 * Callers report every key-up with [onRelease], for both modes. That call is what ends a
 * refused key-repeat block (see [onPress]).
 */
public class ActivationDriver(
    private val session: HoldSession,
    private val source: ActivationSource,
) {
    init {
        require(source !is ToggleSource || session.debounceMs == 0L) {
            "a ToggleSource needs a session with debounceMs = 0: a tap has no debounce, and a " +
                "non-zero one would swallow the tap (session debounceMs was ${session.debounceMs})"
        }
    }

    /** True from a key-down until the next [onRelease]. */
    private var keyDown = false

    /**
     * True when a secure refusal (or a secure abort) happened while the key was down. Set by
     * [sync]; cleared by the next [onRelease], which is the key's onHoldEnd. While it is set,
     * every [onPress] (a key-repeat of the refused press) is ignored, so a refused key cannot
     * start a burst in a normal field until it has been released once.
     */
    private var refusedWhileDown = false

    /** Why the most recent burst ended. Null until a burst ends, and cleared by the next start. */
    public var lastEndCause: EndCause? = null
        private set

    /**
     * The activation gesture began at [atMs]. A press in a secure field is refused before the
     * source sees it, and the stop of a running burst is also refused: a secure field never
     * lets a burst reach Decoding.
     *
     * [snapshot] returns the audio recorded so far. It is only called when a toggle tap or
     * cap stops a burst in a normal field.
     */
    public fun onPress(
        atMs: Long,
        fieldIsSecure: Boolean = false,
        snapshot: () -> FloatArray = NO_AUDIO,
    ): List<SessionEffect> {
        keyDown = true
        if (refusedWhileDown) return emptyList() // key-repeat of a refused press
        if (fieldIsSecure) return sync(session.onPress(atMs, fieldIsSecure = true))
        // A tap while the session is idle is always a start, even if the session was
        // cancelled behind the driver's back and the source still remembers a running burst.
        if (session.isIdle) source.reset()
        return sync(apply(source.onHoldStart(atMs), atMs, snapshot))
    }

    /**
     * The activation gesture ended at [atMs]: the key came up. A toggle source ignores it,
     * but the key is released here for both modes, which clears a refused-press block.
     */
    public fun onRelease(atMs: Long, samples: FloatArray): List<SessionEffect> {
        keyDown = false
        refusedWhileDown = false
        return sync(apply(source.onHoldEnd(atMs), atMs) { samples })
    }

    /**
     * Time advanced to [nowMs]. The caller must call this while a burst may be running, as
     * it does for [HoldSession.onTick]. [snapshot] is called only when the cap fires in a
     * normal field. A secure report aborts the burst first, so the cap cannot decode it.
     */
    public fun onTick(
        nowMs: Long,
        snapshot: () -> FloatArray = NO_AUDIO,
        fieldIsSecure: Boolean? = null,
    ): List<SessionEffect> {
        if (fieldIsSecure == true) return sync(session.onTick(nowMs, fieldIsSecure = true))
        return sync(apply(source.onTick(nowMs), nowMs, snapshot) + session.onTick(nowMs, fieldIsSecure))
    }

    /** The decoder produced [text]. Passed through to [HoldSession.onDecoded]. */
    public fun onDecoded(text: String, fieldIsSecure: Boolean, nowMs: Long): List<SessionEffect> =
        sync(session.onDecoded(text, fieldIsSecure, nowMs))

    /** The decoder failed. Passed through to [HoldSession.onDecodeFailed]. */
    public fun onDecodeFailed(nowMs: Long, fieldIsSecure: Boolean? = null): List<SessionEffect> =
        sync(session.onDecodeFailed(nowMs, fieldIsSecure))

    /** The text was inserted, or went to the clipboard. Passed through to [HoldSession.onDelivered]. */
    public fun onDelivered(inserted: Boolean, nowMs: Long, fieldIsSecure: Boolean? = null): List<SessionEffect> =
        sync(session.onDelivered(inserted, nowMs, fieldIsSecure))

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
                ActivationEdge.HoldStart -> {
                    lastEndCause = null
                    session.onPress(atMs) + session.onTick(atMs)
                }
                // An end is a key-up carrying the audio. Every cause ends the burst the same
                // way; the cause is kept for the UI to say why the mic closed.
                is ActivationEdge.HoldEnd -> {
                    lastEndCause = edge.cause
                    session.onRelease(atMs, snapshot())
                }
            }
        }
        return out
    }

    /**
     * Runs after every call. A session that has returned to Idle holds no burst, so the source
     * must not remember one; resetting is idempotent for both sources. A secure refusal while
     * the key is down sets [refusedWhileDown].
     */
    private fun sync(effects: List<SessionEffect>): List<SessionEffect> {
        if (session.isIdle) source.reset()
        if (keyDown && effects.contains(SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD))) {
            refusedWhileDown = true
        }
        return effects
    }

    private companion object {
        private val NO_AUDIO: () -> FloatArray = { FloatArray(0) }
    }
}
