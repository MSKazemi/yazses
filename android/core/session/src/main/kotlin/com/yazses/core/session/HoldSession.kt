// Hold-to-talk burst state machine: debounce, silent-burst discard, delivery.
//
// Port of the desktop's hold semantics:
//   - debounce: a key must be held >= N ms before a burst starts
//     (src/yazses/hotkeys/hold_detector.py `HoldDetector.check`, `>=`);
//   - a release with no burst in progress is ignored
//     (src/yazses/core/daemon.py `_on_hold_end`, "Hold released with no recording");
//   - a key-down while a burst is already running is a key-repeat and is ignored
//     (src/yazses/hotkeys/evdev_hold.py `_handle_event`, `if self._recording: return`);
//   - input that arrives while the previous burst is decoding waits its turn: the
//     desktop decodes synchronously on the hotkey thread, so events queue behind it
//     and are then processed as they are dequeued (evdev_hold.py `run`).
//
// Pure Kotlin. No clock is read here: every event carries the timestamp the caller
// observed, so a test drives time with plain numbers.
package com.yazses.core.session

import com.yazses.core.vad.VoiceActivityGate

/** Where one hold-to-talk burst is. */
public sealed interface SessionState {
    /** Nothing held, nothing running. */
    public data object Idle : SessionState

    /** A key is down but has not yet been held for the debounce. No capture runs. */
    public data class Holding(val pressedAtMs: Long) : SessionState

    /** The debounce passed; the caller is recording audio. */
    public data object Capturing : SessionState

    /** The captured audio cleared the gate and is being transcribed. */
    public data object Decoding : SessionState

    /** The decoded text was approved and is being inserted into the field. */
    public data class Delivering(val text: String) : SessionState
}

/** What the caller must do in response to a state change. */
public sealed interface SessionEffect {
    /** Start recording. Audio captured from here on belongs to the burst. */
    public data object StartCapture : SessionEffect

    /** Stop recording. The samples go back in through [HoldSession.onRelease]. */
    public data object StopCapture : SessionEffect

    /** Transcribe [samples]; report the outcome with onDecoded or onDecodeFailed. */
    public class Decode(public val samples: FloatArray) : SessionEffect

    /** Insert [text] into the focused field; report the outcome with onDelivered. */
    public class Deliver(public val text: String) : SessionEffect

    /** The burst was below the voice gate. Nothing is transcribed or typed. */
    public data object NothingHeard : SessionEffect

    /** The decoder failed. Nothing is delivered. */
    public data object DecodeFailed : SessionEffect

    /** The decoded text was not allowed into the field. */
    public data class Refused(val reason: DeliveryGuard.Refusal) : SessionEffect
}

/**
 * The hold-to-talk burst state machine.
 *
 * Every method returns the [SessionEffect]s the caller must act on, in order. The
 * session owns no audio, no decoder and no injector.
 *
 * @param gate decides whether a captured burst contains speech at all.
 * @param debounceMs how long a key must stay down before a burst starts. The desktop
 *   default is `[hotkey] hold_threshold_ms = 500` (src/yazses/config.py).
 */
public class HoldSession(
    private val gate: VoiceActivityGate,
    private val debounceMs: Long = DEFAULT_DEBOUNCE_MS,
) {
    init {
        require(debounceMs >= 0) { "debounceMs must be >= 0, was $debounceMs" }
    }

    /** The current state. Read-only from outside. */
    public var state: SessionState = SessionState.Idle
        private set

    /** The last inserted text, for a single undo. Filled by [onDelivered]. */
    public val undo: UndoLastInsert = UndoLastInsert()

    /** Key events that arrived while a burst was decoding or delivering. */
    private val queued = ArrayDeque<Kind>()

    private enum class Kind { PRESS, RELEASE }

    /** The key went down at [atMs]. */
    public fun onPress(atMs: Long): List<SessionEffect> = input(Kind.PRESS, atMs, NO_SAMPLES)

    /**
     * The key came up at [atMs]. [samples] is the audio recorded since
     * [SessionEffect.StartCapture], or empty when no capture ran.
     */
    public fun onRelease(atMs: Long, samples: FloatArray): List<SessionEffect> =
        input(Kind.RELEASE, atMs, samples)

    /** Time advanced to [nowMs] while the key is still down. Starts the burst at the debounce. */
    public fun onTick(nowMs: Long): List<SessionEffect> = advanceHold(nowMs)

    /**
     * The decoder produced [text] for the burst. [fieldIsSecure] is whether the focused
     * field is a password or secure field. [nowMs] is when the caller observed this.
     */
    public fun onDecoded(text: String, fieldIsSecure: Boolean, nowMs: Long): List<SessionEffect> {
        val out = mutableListOf<SessionEffect>()
        when (val decision = DeliveryGuard.decide(state, text, fieldIsSecure)) {
            is DeliveryGuard.Decision.Deliver -> {
                state = SessionState.Delivering(text)
                out += SessionEffect.Deliver(text)
            }
            is DeliveryGuard.Decision.Refuse -> {
                if (state == SessionState.Decoding) state = SessionState.Idle
                out += SessionEffect.Refused(decision.reason)
            }
        }
        return out + pump(nowMs)
    }

    /** The decoder failed on this burst. */
    public fun onDecodeFailed(nowMs: Long): List<SessionEffect> {
        val out = mutableListOf<SessionEffect>()
        if (state == SessionState.Decoding) {
            state = SessionState.Idle
            out += SessionEffect.DecodeFailed
        }
        return out + pump(nowMs)
    }

    /**
     * The caller finished inserting the text. [inserted] is false when the text went to
     * the clipboard instead (no input connection). Only an insert is undoable.
     */
    public fun onDelivered(inserted: Boolean, nowMs: Long): List<SessionEffect> {
        val delivering = state as? SessionState.Delivering
        if (delivering != null) {
            if (inserted) undo.remember(delivering.text)
            state = SessionState.Idle
        }
        return pump(nowMs)
    }

    private fun input(kind: Kind, atMs: Long, samples: FloatArray): List<SessionEffect> {
        if (state.isBusy()) {
            // Dedupe consecutive repeats so an auto-repeating key does not flood the queue.
            if (queued.lastOrNull() != kind) queued.addLast(kind)
            return emptyList()
        }
        return handle(kind, atMs, samples) + pump(atMs)
    }

    private fun handle(kind: Kind, atMs: Long, samples: FloatArray): List<SessionEffect> {
        val out = mutableListOf<SessionEffect>()
        when (kind) {
            Kind.PRESS -> {
                if (state == SessionState.Idle) state = SessionState.Holding(atMs)
                // A press during Holding or Capturing is a key-repeat and changes nothing.
                out += advanceHold(atMs)
            }
            Kind.RELEASE -> {
                // A release late enough to have passed the debounce is a burst, even if
                // no tick arrived in between.
                out += advanceHold(atMs)
                when (state) {
                    // A tap: released before the debounce. Nothing was ever started.
                    is SessionState.Holding -> state = SessionState.Idle
                    SessionState.Capturing -> out += finishCapture(samples)
                    else -> Unit
                }
            }
        }
        return out
    }

    private fun advanceHold(nowMs: Long): List<SessionEffect> {
        val holding = state as? SessionState.Holding ?: return emptyList()
        if (nowMs - holding.pressedAtMs >= debounceMs) {
            state = SessionState.Capturing
            return listOf(SessionEffect.StartCapture)
        }
        return emptyList()
    }

    private fun finishCapture(samples: FloatArray): List<SessionEffect> {
        if (gate.isSilent(samples)) {
            state = SessionState.Idle
            return listOf(SessionEffect.StopCapture, SessionEffect.NothingHeard)
        }
        state = SessionState.Decoding
        return listOf(SessionEffect.StopCapture, SessionEffect.Decode(samples))
    }

    /**
     * Replays queued key events, stamped at [nowMs]. The desktop stamps a queued event
     * when it is dequeued, not when it happened, so a press and release that queued up
     * behind a decode come out as a tap rather than a phantom burst.
     */
    private fun pump(nowMs: Long): List<SessionEffect> {
        val out = mutableListOf<SessionEffect>()
        while (queued.isNotEmpty() && !state.isBusy()) {
            out += handle(queued.removeFirst(), nowMs, NO_SAMPLES)
        }
        return out
    }

    private fun SessionState.isBusy(): Boolean =
        this == SessionState.Decoding || this is SessionState.Delivering

    public companion object {
        /** The desktop default: `[hotkey] hold_threshold_ms = 500`. */
        public const val DEFAULT_DEBOUNCE_MS: Long = 500L

        private val NO_SAMPLES = FloatArray(0)
    }
}
