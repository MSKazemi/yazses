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

    /**
     * Stop recording. After a normal stop the samples go back in through [HoldSession.onRelease].
     * After a secure abort (emitted with [Refused]) the audio is discarded: nothing is decoded,
     * and the matching [HoldSession.onRelease] is ignored.
     */
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
    public val debounceMs: Long = DEFAULT_DEBOUNCE_MS,
) {
    init {
        require(debounceMs >= 0) { "debounceMs must be >= 0, was $debounceMs" }
    }

    /** The current state. Read-only from outside. */
    public var state: SessionState = SessionState.Idle
        private set

    /** True when no burst is held, captured, decoded or delivered. Cheap; no allocation. */
    public val isIdle: Boolean
        get() = state == SessionState.Idle

    /** The last inserted text, for a single undo. Filled by [onDelivered]. */
    public val undo: UndoLastInsert = UndoLastInsert()

    /** Key events that arrived while a burst was decoding or delivering. */
    private val queued = ArrayDeque<Kind>()

    /**
     * The field state the caller most recently reported, through onPress, onTick, onDecoded,
     * onDecodeFailed or onDelivered. Every path that can start a capture reads it.
     */
    private var fieldSecure = false

    private enum class Kind { PRESS, RELEASE }

    /**
     * The key went down at [atMs]. When [fieldIsSecure] is true (a password or secure
     * field is focused) the mic is refused: this returns [SessionEffect.Refused] with
     * [DeliveryGuard.Refusal.SECURE_FIELD], starts nothing, and queues nothing. The
     * matching release then has nothing to do.
     */
    public fun onPress(atMs: Long, fieldIsSecure: Boolean = false): List<SessionEffect> {
        fieldSecure = fieldIsSecure
        if (fieldIsSecure) {
            // A secure field aborts a burst that is waiting out its debounce or recording.
            val aborted = observe(true)
            return if (aborted.isEmpty()) listOf(SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)) else aborted
        }
        return input(Kind.PRESS, atMs, NO_SAMPLES)
    }

    /**
     * The key came up at [atMs]. [samples] is the audio recorded since
     * [SessionEffect.StartCapture], or empty when no capture ran.
     *
     * Capture starts only from [onTick]. The caller MUST call [onTick] while the key is
     * held, so a release past the debounce with no prior tick means no audio was ever
     * recorded: that burst reports [SessionEffect.NothingHeard] and decodes nothing.
     */
    public fun onRelease(atMs: Long, samples: FloatArray): List<SessionEffect> =
        input(Kind.RELEASE, atMs, samples)

    /**
     * Time advanced to [nowMs] while the key is still down. Starts the burst at the
     * debounce. Ticks are mandatory: a held key must be ticked, or its burst never records.
     */
    public fun onTick(nowMs: Long, fieldIsSecure: Boolean? = null): List<SessionEffect> =
        observe(fieldIsSecure) + advanceHold(nowMs)

    /**
     * Abandons whatever is in progress, from any state, and returns to [SessionState.Idle].
     * Use it when the key-up can no longer arrive (focus lost, IME hidden, mic taken) or
     * when a decode never reports back. It clears the queued key events. Emits
     * [SessionEffect.StopCapture] only when a capture was running. A decode result that
     * arrives after a cancel is ignored.
     */
    public fun cancel(nowMs: Long): List<SessionEffect> {
        val wasCapturing = state == SessionState.Capturing
        state = SessionState.Idle
        queued.clear()
        return if (wasCapturing) listOf(SessionEffect.StopCapture) else emptyList()
    }

    /**
     * Forgets the remembered insert, so [UndoLastInsert.undo] returns null. The caller
     * must call it when the user types or moves the cursor, because the recorded length
     * would then delete the user's own characters.
     */
    public fun invalidateUndo() {
        undo.invalidate()
    }

    /**
     * The decoder produced [text] for the burst. [fieldIsSecure] is whether the focused
     * field is a password or secure field. [nowMs] is when the caller observed this.
     *
     * A result that arrives while the session is [SessionState.Idle] (for example after a
     * [cancel]) is a stray and is ignored silently. A result during any other non-decoding
     * burst state is still refused with [DeliveryGuard.Refusal.NOT_DECODING].
     */
    public fun onDecoded(text: String, fieldIsSecure: Boolean, nowMs: Long): List<SessionEffect> {
        // Observe the field first: a stray result that reports a secure field while a new burst
        // is recording aborts that burst, exactly as a tick would (no audio is decoded).
        val aborted = observe(fieldIsSecure)
        if (aborted.isNotEmpty()) return aborted + pump(nowMs)
        if (state == SessionState.Idle) return pump(nowMs)
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
    public fun onDecodeFailed(nowMs: Long, fieldIsSecure: Boolean? = null): List<SessionEffect> {
        val out = mutableListOf<SessionEffect>()
        out += observe(fieldIsSecure)
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
    public fun onDelivered(inserted: Boolean, nowMs: Long, fieldIsSecure: Boolean? = null): List<SessionEffect> {
        val observed = observe(fieldIsSecure)
        val delivering = state as? SessionState.Delivering
        if (delivering != null) {
            // A clipboard-only delivery, or any later insert, makes the earlier insert
            // unsafe to undo: the cursor is no longer where that insert left it.
            if (inserted) undo.remember(delivering.text) else undo.invalidate()
            state = SessionState.Idle
        }
        return observed + pump(nowMs)
    }

    private fun input(kind: Kind, atMs: Long, samples: FloatArray): List<SessionEffect> {
        if (state.isBusy()) {
            // Dedupe consecutive repeats so an auto-repeating key does not flood the queue.
            // The bound is hard: a stuck decode with alternating events drops the oldest.
            if (queued.lastOrNull() != kind) {
                if (queued.size == MAX_QUEUED_EVENTS) queued.removeFirst()
                queued.addLast(kind)
            }
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
            Kind.RELEASE -> when (val current = state) {
                // Released before the debounce: a tap, nothing was ever started.
                // Released after the debounce but never ticked: capture never started,
                // so no audio exists to decode. Report it as heard nothing.
                is SessionState.Holding -> {
                    state = SessionState.Idle
                    if (atMs - current.pressedAtMs >= debounceMs) out += SessionEffect.NothingHeard
                }
                SessionState.Capturing -> out += finishCapture(samples)
                else -> Unit
            }
        }
        return out
    }

    /**
     * Reports the focused field on its own, without a key event. A secure report aborts a burst
     * that is waiting out its debounce or recording, exactly as the other entry points do, and
     * returns the same effects. A normal report only records the field.
     */
    public fun observeField(fieldIsSecure: Boolean): List<SessionEffect> = observe(fieldIsSecure)

    /**
     * Records the field state the caller just reported. A secure report aborts a burst that
     * is waiting out its debounce (Holding) or recording (Capturing) and returns to Idle.
     * The audio of an aborted capture is discarded, never decoded or delivered
     * (architecture.md §6: mic disabled in a password field).
     */
    private fun observe(fieldIsSecure: Boolean?): List<SessionEffect> {
        if (fieldIsSecure == null) return emptyList()
        fieldSecure = fieldIsSecure
        if (!fieldIsSecure) return emptyList()
        return when (state) {
            is SessionState.Holding -> {
                state = SessionState.Idle
                listOf(SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD))
            }
            SessionState.Capturing -> {
                state = SessionState.Idle
                listOf(SessionEffect.StopCapture, SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD))
            }
            else -> emptyList()
        }
    }

    private fun advanceHold(nowMs: Long): List<SessionEffect> {
        val holding = state as? SessionState.Holding ?: return emptyList()
        if (nowMs - holding.pressedAtMs >= debounceMs) {
            if (fieldSecure) {
                state = SessionState.Idle
                return listOf(SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD))
            }
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
            val kind = queued.removeFirst()
            // A press that waited behind a decode must not open the mic in a field that is
            // secure now. The queue remembers the key, not the field, so it is refused here.
            if (kind == Kind.PRESS && fieldSecure) {
                out += SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)
                continue
            }
            out += handle(kind, nowMs, NO_SAMPLES)
        }
        return out
    }

    private fun SessionState.isBusy(): Boolean =
        this == SessionState.Decoding || this is SessionState.Delivering

    public companion object {
        /** The desktop default: `[hotkey] hold_threshold_ms = 500`. */
        public const val DEFAULT_DEBOUNCE_MS: Long = 500L

        /** The most key events kept while a burst is decoding or delivering. The oldest is dropped beyond this. */
        public const val MAX_QUEUED_EVENTS: Int = 8

        private val NO_SAMPLES = FloatArray(0)
    }
}
