package com.yazses.core.session

import com.yazses.core.vad.CalibratedRmsGate
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.fail

/**
 * Seeded fuzz of [ActivationDriver] in hold and in toggle mode. Each sequence is a random mix
 * of presses, releases, ticks, cancels, and decode results (real and stray, including late
 * ones), with the secure flag flipping at random times. The seed is fixed, so any failure
 * reproduces exactly; the failure message prints the last operations.
 *
 * Invariants, checked after every call:
 *  (a) no StartCapture while the most recent secure observation is secure;
 *  (b) no Decode for a burst that saw a secure observation;
 *  (c) after cancel(), and after a release that is drained, a normal-field press starts capture;
 *  (d) a press on an idle session with the key up always starts capture;
 *  (e) one call returns no more effects than the bounded queue can produce.
 *
 * (e) is a bound on the effects of one call, not a direct read of the queue. The queue's own
 * bound is pinned by HoldSessionTest.
 */
class ActivationFuzzTest {

    private val loud = FloatArray(16) { 0.5f }
    private val silent = FloatArray(16)

    @Test
    fun `hold driver keeps every invariant over seeded random sequences`() {
        val rnd = Random(20_261_025)
        repeat(SEQUENCES) { index -> Run(hold = true, rnd = rnd, index = index).execute() }
    }

    @Test
    fun `toggle driver keeps every invariant over seeded random sequences`() {
        val rnd = Random(20_261_026)
        repeat(SEQUENCES) { index -> Run(hold = false, rnd = rnd, index = index).execute() }
    }

    private inner class Run(private val hold: Boolean, private val rnd: Random, private val index: Int) {
        private val session = HoldSession(CalibratedRmsGate(), debounceMs = if (hold) 500L else 0L)
        private val driver = ActivationDriver(
            session,
            if (hold) HoldKeySource() else ToggleSource(maxBurstMs = 1_500L),
        )

        private var now = 0L
        private var keyDown = false
        private var lastSecure = false // the most recent secure observation the session was given
        private var inBurst = false
        private var tainted = false // a secure observation arrived during the current burst
        private val trace = ArrayList<String>()

        fun execute() {
            repeat(STEPS) { step() }
            cancelAndProbe("end of sequence")
            releaseAndProbe()
        }

        private fun step() {
            now += rnd.nextLong(0, 700)
            when (rnd.nextInt(100)) {
                in 0 until 22 -> press()
                in 22 until 40 -> release()
                in 40 until 60 -> tick()
                in 60 until 68 -> decoded()
                in 68 until 74 -> decodeFailed()
                in 74 until 80 -> delivered()
                in 80 until 84 -> cancelAndProbe("random cancel")
                else -> tick()
            }
        }

        private fun flag(): Boolean = rnd.nextInt(4) == 0

        private fun optionalFlag(): Boolean? = when (rnd.nextInt(3)) {
            0 -> null
            1 -> false
            else -> true
        }

        private fun pickAudio(): FloatArray = if (rnd.nextInt(5) == 0) silent else loud

        private fun snapshot(): () -> FloatArray {
            val audio = pickAudio()
            return { audio }
        }

        private fun observe(secure: Boolean?) {
            if (secure == null) return
            lastSecure = secure
            if (secure && inBurst) tainted = true
        }

        private fun press() {
            val secure = flag()
            val mustStart = !secure && session.isIdle && !keyDown
            keyDown = true
            observe(secure)
            var effects = driver.onPress(now, secure, snapshot())
            record("press(secure=$secure)", effects)
            if (mustStart) {
                now += 500
                observe(false)
                val ticked = driver.onTick(now, snapshot(), fieldIsSecure = false)
                effects = effects + ticked
                record("tick(false) after idle press", ticked)
                if (SessionEffect.StartCapture !in effects) {
                    violation("(d) a press on an idle session with the key up did not start capture")
                }
            }
            check(effects)
        }

        private fun release() {
            keyDown = false
            val effects = driver.onRelease(now, pickAudio())
            record("release", effects)
            check(effects)
        }

        private fun tick() {
            val secure = optionalFlag()
            observe(secure)
            val effects = driver.onTick(now, snapshot(), secure)
            record("tick(secure=$secure)", effects)
            check(effects)
        }

        private fun decoded() {
            val secure = flag()
            observe(secure)
            val effects = driver.onDecoded("x", secure, now)
            record("late onDecoded(secure=$secure)", effects)
            check(effects)
        }

        private fun decodeFailed() {
            val secure = optionalFlag()
            observe(secure)
            val effects = driver.onDecodeFailed(now, secure)
            record("onDecodeFailed(secure=$secure)", effects)
            check(effects)
        }

        private fun delivered() {
            val secure = optionalFlag()
            observe(secure)
            val inserted = rnd.nextBoolean()
            val effects = driver.onDelivered(inserted, now, secure)
            record("onDelivered(inserted=$inserted, secure=$secure)", effects)
            check(effects)
        }

        /** (c): cancel abandons the burst; a normal-field press must then start capture. */
        private fun cancelAndProbe(label: String) {
            val cancelled = driver.cancel(now)
            record("cancel ($label)", cancelled)
            check(cancelled)
            keyDown = false
            inBurst = false
            probeStart("after cancel ($label)")
        }

        /** (c) after a release: drain any decode the release started, then cancel and probe. */
        private fun releaseAndProbe() {
            if (!hold) return
            keyDown = false
            check(driver.onRelease(now, silent))
            repeat(DRAIN_LIMIT) {
                when (session.state) {
                    SessionState.Decoding -> check(driver.onDecoded("x", false, now).also { record("drain decode", it) })
                    is SessionState.Delivering -> check(driver.onDelivered(true, now).also { record("drain deliver", it) })
                    else -> Unit
                }
            }
            if (session.state == SessionState.Decoding || session.state is SessionState.Delivering) {
                violation("(c) a release left the session wedged in ${session.state}")
            }
            cancelAndProbe("after release")
        }

        private fun probeStart(label: String) {
            keyDown = true
            observe(false)
            var effects = driver.onPress(now, false, snapshot())
            record("probe press ($label)", effects)
            if (hold) {
                now += 500
                val ticked = driver.onTick(now, snapshot(), fieldIsSecure = false)
                effects = effects + ticked
                record("probe tick ($label)", ticked)
            }
            if (SessionEffect.StartCapture !in effects) {
                violation("(c) a normal-field press did not start capture $label")
            }
            check(effects)
        }

        /** Checks (a), (b) and (e) over one call's effects, in order. */
        private fun check(effects: List<SessionEffect>) {
            if (effects.size > MAX_EFFECTS_PER_CALL) {
                violation("(e) one call returned ${effects.size} effects, above the bound $MAX_EFFECTS_PER_CALL")
            }
            for (effect in effects) {
                when (effect) {
                    SessionEffect.StartCapture -> {
                        if (lastSecure) violation("(a) StartCapture while the last secure observation is secure")
                        inBurst = true
                        tainted = false
                    }
                    is SessionEffect.Decode -> {
                        if (tainted) violation("(b) Decode for a burst that saw a secure observation")
                    }
                    SessionEffect.StopCapture -> inBurst = false
                    else -> Unit
                }
            }
        }

        private fun record(op: String, effects: List<SessionEffect>) {
            trace += "t=$now $op -> $effects"
        }

        private fun violation(message: String): Nothing {
            val tail = trace.takeLast(20).joinToString("\n  ")
            fail("sequence $index (${if (hold) "hold" else "toggle"}): $message\n  $tail")
        }
    }

    private companion object {
        const val SEQUENCES = 4_000
        const val STEPS = 60
        const val DRAIN_LIMIT = 6
        const val MAX_EFFECTS_PER_CALL = 3 * HoldSession.MAX_QUEUED_EVENTS + 4
    }
}
