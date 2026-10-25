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

    /** True from a key-down until the next [onRelease] or [cancel]. */
    private var keyDown = false

    /**
     * True when a secure refusal (or a secure abort) happened while the key was down. Set after
     * each call; cleared by the next [onRelease], which is the key's onHoldEnd, or by [cancel].
     * While it is set, every [onPress] (a key-repeat of the refused press) starts nothing.
     */
    private var refusedWhileDown = false

    /**
     * Why the most recent burst ended. Null until a burst ends, and cleared by the next start.
     * [EndCause.SECURE_ABORT] is set when a secure field ends a burst.
     */
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
    ): List<SessionEffect> = call {
        keyDown = true
        if (refusedWhileDown) {
            // A key-repeat of a refused press starts nothing, but the field it reports still
            // reaches the session: a secure report keeps the session's secure state current.
            session.observeField(fieldIsSecure)
        } else if (fieldIsSecure) {
            session.onPress(atMs, fieldIsSecure = true)
        } else {
            // A tap while the session is idle is always a start, even if the session was
            // cancelled behind the driver's back and the source still remembers a running burst.
            if (session.isIdle) source.reset()
            apply(source.onHoldStart(atMs), atMs, snapshot)
        }
    }

    /**
     * The activation gesture ended at [atMs]: the key came up. A toggle source ignores it,
     * but the key is released here for both modes, which clears a refused-press block.
     */
    public fun onRelease(atMs: Long, samples: FloatArray): List<SessionEffect> = call {
        keyDown = false
        refusedWhileDown = false
        apply(source.onHoldEnd(atMs), atMs) { samples }
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
    ): List<SessionEffect> = call {
        if (fieldIsSecure == true) {
            session.onTick(nowMs, fieldIsSecure = true)
        } else {
            apply(source.onTick(nowMs), nowMs, snapshot) + session.onTick(nowMs, fieldIsSecure)
        }
    }

    /** The decoder produced [text]. Passed through to [HoldSession.onDecoded]. */
    public fun onDecoded(text: String, fieldIsSecure: Boolean, nowMs: Long): List<SessionEffect> =
        call { session.onDecoded(text, fieldIsSecure, nowMs) }

    /** The decoder failed. Passed through to [HoldSession.onDecodeFailed]. */
    public fun onDecodeFailed(nowMs: Long, fieldIsSecure: Boolean? = null): List<SessionEffect> =
        call { session.onDecodeFailed(nowMs, fieldIsSecure) }

    /** The text was inserted, or went to the clipboard. Passed through to [HoldSession.onDelivered]. */
    public fun onDelivered(inserted: Boolean, nowMs: Long, fieldIsSecure: Boolean? = null): List<SessionEffect> =
        call { session.onDelivered(inserted, nowMs, fieldIsSecure) }

    /**
     * Abandons the burst in the session and forgets the source's gesture. Cancel is for a key-up
     * that can no longer arrive, so it also clears the key state and the refused-press block:
     * the next press is a new press.
     */
    public fun cancel(nowMs: Long): List<SessionEffect> {
        source.reset()
        keyDown = false
        refusedWhileDown = false
        return session.cancel(nowMs)
    }

    /**
     * Runs one session call and then the bookkeeping: [sync] needs the state from before the
     * call, to tell a secure abort of a live burst from a refusal with nothing running.
     */
    private inline fun call(block: () -> List<SessionEffect>): List<SessionEffect> {
        val before = session.state
        return sync(before, block())
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
     * the key is down sets [refusedWhileDown]. A secure refusal that ends a live burst (Holding,
     * Capturing or Decoding) sets [lastEndCause] to [EndCause.SECURE_ABORT].
     */
    private fun sync(before: SessionState, effects: List<SessionEffect>): List<SessionEffect> {
        val secureRefusal = effects.contains(SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD))
        if (session.isIdle) source.reset()
        if (keyDown && secureRefusal) refusedWhileDown = true
        if (secureRefusal && before != SessionState.Idle && session.isIdle) {
            lastEndCause = EndCause.SECURE_ABORT
        }
        return effects
    }

    private companion object {
        private val NO_AUDIO: () -> FloatArray = { FloatArray(0) }
    }
}
