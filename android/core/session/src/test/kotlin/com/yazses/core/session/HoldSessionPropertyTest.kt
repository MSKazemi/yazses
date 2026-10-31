package com.yazses.core.session

import com.yazses.core.vad.CalibratedRmsGate
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.fail

/**
 * Seeded property test of [HoldSession] on its own, without [ActivationDriver] (issue #676).
 *
 * Each sequence is a random mix of press, release, tick, decoded, decode-failed, delivered,
 * cancel, invalidate, undo and field-report events, with the secure-field flag flipping at
 * random, against a session whose debounce is drawn from {0, 1, 500} ms. A per-sequence share of
 * steps (0, 15 or 40 %) instead takes the next event of an ordinary burst, so delivery and undo
 * are reached often while the 0 % sequences stay fully adversarial. The seed is fixed, so a
 * failure reproduces exactly; the message names the seed and sequence and prints the last
 * operations.
 *
 * Invariants, checked after every step:
 *  (q) the key-event queue never holds more than [HoldSession.MAX_QUEUED_EVENTS] events;
 *  (c) after cancel() the session is idle with an empty queue, and a normal-field press at a
 *      later time, ticked to the debounce, starts capture (the session can never wedge);
 *  (s) a press in a secure field never emits StartCapture, no call emits StartCapture while the
 *      most recent field report was secure, and the session is never Holding or Capturing then;
 *  (u) undo() returns a given insert at most once, and only the insert a model of the session
 *      says is still undoable (a clipboard delivery or an invalidation forgets it).
 *
 * The test also fails if the generator reached any situation those invariants depend on (a full
 * queue, a cancel while busy, a stale insert followed by undo, ...) fewer than [MIN_COVERAGE]
 * times: a property never exercised is not evidence.
 */
class HoldSessionPropertyTest {

    @Test
    fun `hold session keeps every invariant over seeded random sequences`() {
        val rnd = Random(SEED)
        val seen = Coverage()
        repeat(SEQUENCES) { index -> Run(rnd, index, seen).execute() }
        println("HoldSessionPropertyTest coverage: $seen")
        // A property test whose generator never reaches a state proves nothing about it.
        seen.requireReached()
    }

    /** How often the generator reached each situation the invariants depend on. */
    private class Coverage {
        var queueFull = 0 // the queue held MAX_QUEUED_EVENTS events
        var cancelWhileBusy = 0 // cancel() from Decoding or Delivering
        var cancelWhileCapturing = 0
        var secureAbortOfCapture = 0 // a secure report stopped a running capture
        var insertDelivered = 0
        var clipboardDelivered = 0
        var undoHit = 0 // undo() returned an insert
        var undoAfterClipboard = 0 // undo() after an insert that a clipboard delivery made stale

        fun requireReached() {
            val counts = mapOf(
                "queueFull" to queueFull,
                "cancelWhileBusy" to cancelWhileBusy,
                "cancelWhileCapturing" to cancelWhileCapturing,
                "secureAbortOfCapture" to secureAbortOfCapture,
                "insertDelivered" to insertDelivered,
                "clipboardDelivered" to clipboardDelivered,
                "undoHit" to undoHit,
                "undoAfterClipboard" to undoAfterClipboard,
            )
            val missed = counts.filterValues { it < MIN_COVERAGE }
            if (missed.isNotEmpty()) fail("the generator reached too rarely (< $MIN_COVERAGE): $missed; all: $counts")
        }

        override fun toString(): String =
            "queueFull=$queueFull cancelWhileBusy=$cancelWhileBusy cancelWhileCapturing=$cancelWhileCapturing " +
                "secureAbortOfCapture=$secureAbortOfCapture insertDelivered=$insertDelivered " +
                "clipboardDelivered=$clipboardDelivered undoHit=$undoHit undoAfterClipboard=$undoAfterClipboard"
    }

    private inner class Run(private val rnd: Random, private val index: Int, private val seen: Coverage) {
        private val debounce = DEBOUNCES[rnd.nextInt(DEBOUNCES.size)]
        private val session = HoldSession(CalibratedRmsGate(), debounceMs = debounce)

        // 0 keeps the sequence fully adversarial (and lets a stuck decode fill the queue); the
        // higher rates complete enough bursts to exercise delivery and undo.
        private val followThroughPercent = FOLLOW_THROUGH_PERCENTS[rnd.nextInt(FOLLOW_THROUGH_PERCENTS.size)]

        private var now = 0L
        private var lastSecure = false // the most recent field report the session was given

        // Undo model: what undo() must return next, and every insert id it has ever returned.
        private var expectedUndo: UndoLastInsert.Insert? = null
        private var nextInsertId = 1L
        private var staleInsert = false // an insert was followed by a clipboard delivery; undo must not return it
        private val undone = HashSet<Long>()

        private val trace = ArrayDeque<String>(TRACE_TAIL)

        fun execute() {
            repeat(STEPS) { step() }
            cancelAndProbe("end of sequence")
        }

        private fun step() {
            now += rnd.nextLong(0, 700)
            // A purely uniform mix rarely completes two bursts in one sequence, so some steps take
            // the event a real user and decoder would produce next. The rest stay adversarial.
            if (rnd.nextInt(100) < followThroughPercent) {
                followThrough()
                checkQueue()
                return
            }
            when (rnd.nextInt(100)) {
                in 0 until 20 -> press()
                in 20 until 36 -> release()
                in 36 until 54 -> tick()
                in 54 until 64 -> decoded()
                in 64 until 70 -> decodeFailed()
                in 70 until 80 -> delivered()
                in 80 until 85 -> cancelAndProbe("random cancel")
                in 85 until 90 -> invalidate()
                in 90 until 95 -> undo()
                else -> observeField()
            }
            checkQueue()
        }

        /** The next event of an ordinary burst for the current state, in a normal field. */
        private fun followThrough() {
            when (session.state) {
                SessionState.Idle -> {
                    observed(false)
                    val effects = session.onPress(now, fieldIsSecure = false)
                    record("follow: onPress(secure=false)", effects)
                    check(effects)
                }
                is SessionState.Holding -> {
                    now += debounce
                    val effects = session.onTick(now, fieldIsSecure = null)
                    record("follow: onTick(secure=null)", effects)
                    check(effects)
                }
                SessionState.Capturing -> {
                    val effects = session.onRelease(now, LOUD)
                    record("follow: onRelease(loud)", effects)
                    check(effects)
                }
                SessionState.Decoding -> {
                    observed(false)
                    val effects = session.onDecoded("hi", fieldIsSecure = false, nowMs = now)
                    record("follow: onDecoded(\"hi\", secure=false)", effects)
                    check(effects)
                }
                is SessionState.Delivering -> delivered()
            }
        }

        private fun optionalFlag(): Boolean? = when (rnd.nextInt(3)) {
            0 -> null
            1 -> false
            else -> true
        }

        private fun observed(secure: Boolean?) {
            if (secure != null) lastSecure = secure
        }

        private fun pickAudio(): FloatArray = if (rnd.nextInt(5) == 0) SILENT else LOUD

        private fun press() {
            val secure = rnd.nextInt(4) == 0
            observed(secure)
            val effects = session.onPress(now, secure)
            record("onPress(secure=$secure)", effects)
            if (secure && SessionEffect.StartCapture in effects) {
                violation("(s) a secure-field press emitted StartCapture")
            }
            check(effects)
        }

        private fun release() {
            val effects = session.onRelease(now, pickAudio())
            record("onRelease", effects)
            check(effects)
        }

        private fun tick() {
            val secure = optionalFlag()
            observed(secure)
            val effects = session.onTick(now, secure)
            record("onTick(secure=$secure)", effects)
            check(effects)
        }

        private fun decoded() {
            val secure = rnd.nextInt(4) == 0
            val text = TEXTS[rnd.nextInt(TEXTS.size)]
            observed(secure)
            val effects = session.onDecoded(text, secure, now)
            record("onDecoded(\"$text\", secure=$secure)", effects)
            check(effects)
        }

        private fun decodeFailed() {
            val secure = optionalFlag()
            observed(secure)
            val effects = session.onDecodeFailed(now, secure)
            record("onDecodeFailed(secure=$secure)", effects)
            check(effects)
        }

        private fun delivered() {
            val secure = optionalFlag()
            val inserted = rnd.nextBoolean()
            val before = session.state
            observed(secure)
            val effects = session.onDelivered(inserted, now, secure)
            record("onDelivered(inserted=$inserted, secure=$secure) from $before", effects)
            // Only a delivery that was in flight changes what can be undone.
            if (before is SessionState.Delivering) {
                if (inserted) seen.insertDelivered++ else seen.clipboardDelivered++
                staleInsert = !inserted && (expectedUndo != null || staleInsert)
                expectedUndo = if (inserted) UndoLastInsert.Insert(nextInsertId++, before.text.length) else null
            }
            check(effects)
        }

        private fun observeField() {
            val secure = rnd.nextInt(3) == 0
            observed(secure)
            val effects = session.observeField(secure)
            record("observeField(secure=$secure)", effects)
            check(effects)
        }

        private fun invalidate() {
            session.invalidateUndo()
            staleInsert = false
            record("invalidateUndo", emptyList())
            expectedUndo = null
        }

        private fun undo() {
            val insert = session.undo.undo()
            record("undo -> $insert", emptyList())
            if (insert != null) seen.undoHit++
            if (staleInsert) seen.undoAfterClipboard++
            staleInsert = false
            if (insert != null && !undone.add(insert.id)) {
                violation("(u) undo returned insert ${insert.id} a second time")
            }
            if (insert != expectedUndo) {
                violation("(u) undo returned $insert, the model expected $expectedUndo")
            }
            expectedUndo = null
        }

        /** (c): cancel abandons everything; a later normal-field press must then start capture. */
        private fun cancelAndProbe(label: String) {
            when (session.state) {
                SessionState.Decoding, is SessionState.Delivering -> seen.cancelWhileBusy++
                SessionState.Capturing -> seen.cancelWhileCapturing++
                else -> Unit
            }
            val cancelled = session.cancel(now)
            record("cancel ($label)", cancelled)
            check(cancelled)
            if (!session.isIdle) violation("(c) cancel left the session in ${session.state}")
            checkQueue()
            if (session.queuedEventCount != 0) {
                violation("(c) cancel left ${session.queuedEventCount} queued events")
            }

            now += 1 + rnd.nextLong(0, 50)
            lastSecure = false
            val pressed = session.onPress(now, fieldIsSecure = false)
            record("probe press ($label)", pressed)
            check(pressed)
            now += debounce
            val ticked = session.onTick(now, fieldIsSecure = false)
            record("probe tick ($label)", ticked)
            check(ticked)
            if (SessionEffect.StartCapture !in pressed + ticked) {
                violation("(c) a normal-field press after cancel did not start capture ($label)")
            }
            if (session.state != SessionState.Capturing) {
                violation("(c) the probe press after cancel left the session in ${session.state}")
            }
            checkQueue()
        }

        /** (s) over one call's effects and the state it left. */
        private fun check(effects: List<SessionEffect>) {
            if (SessionEffect.StartCapture in effects && lastSecure) {
                violation("(s) StartCapture while the most recent field report was secure")
            }
            // Stronger than "no StartCapture": the mic is never recording, or arming to record,
            // while the most recent field report says a secure field is focused.
            val state = session.state
            if (lastSecure && (state == SessionState.Capturing || state is SessionState.Holding)) {
                violation("(s) the session is in $state while the most recent field report was secure")
            }
            if (SessionEffect.StopCapture in effects &&
                SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD) in effects
            ) {
                seen.secureAbortOfCapture++
            }
        }

        /** (q) read straight from the session. */
        private fun checkQueue() {
            val size = session.queuedEventCount
            if (size == HoldSession.MAX_QUEUED_EVENTS) seen.queueFull++
            if (size > HoldSession.MAX_QUEUED_EVENTS) {
                violation("(q) $size queued events, above the bound ${HoldSession.MAX_QUEUED_EVENTS}")
            }
        }

        private fun record(op: String, effects: List<SessionEffect>) {
            if (trace.size == TRACE_TAIL) trace.removeFirst()
            trace.addLast("t=$now $op -> $effects [state=${session.state}, queued=${session.queuedEventCount}]")
        }

        private fun violation(message: String): Nothing {
            val tail = trace.joinToString("\n  ")
            fail("seed $SEED, sequence $index (debounce=$debounce ms, follow-through=$followThroughPercent%): $message\n  $tail")
        }
    }

    private companion object {
        const val SEED = 20_261_030
        const val SEQUENCES = 3_000
        const val STEPS = 80
        const val TRACE_TAIL = 25
        const val MIN_COVERAGE = 50
        val FOLLOW_THROUGH_PERCENTS = intArrayOf(0, 15, 40)
        val DEBOUNCES = longArrayOf(0L, 1L, HoldSession.DEFAULT_DEBOUNCE_MS)
        val TEXTS = arrayOf("hi", "hello world", "", "   ", "ü😀")
        val LOUD = FloatArray(16) { 0.5f }
        val SILENT = FloatArray(16)
    }
}
