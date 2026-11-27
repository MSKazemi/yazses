package com.yazses.core.audio

import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class CaptureLoopTest {

    /** A stream driven by scripted reads. With no step queued, a read returns 0. */
    private class FakeStream(private val onStart: () -> Boolean = { true }) : PcmStream {
        val steps = LinkedBlockingQueue<(ShortArray) -> Int>()
        val releases = AtomicInteger()
        val released = CountDownLatch(1)

        @Volatile
        var reader: Thread? = null

        override val bufferSamples: Int = 4

        override fun start(): Boolean = onStart()

        override fun read(into: ShortArray): Int {
            reader = Thread.currentThread()
            val step = steps.poll(2, TimeUnit.MILLISECONDS) ?: return 0
            return step(into)
        }

        override fun release() {
            releases.incrementAndGet()
            released.countDown()
        }
    }

    private val chunks = LinkedBlockingQueue<FloatArray>()
    private val stops = LinkedBlockingQueue<CaptureStopReason>()

    private fun loop(vararg streams: FakeStream): CaptureLoop {
        val remaining = ArrayDeque(streams.toList())
        return CaptureLoop({ remaining.removeFirst() }, { chunks.add(it) }, { stops.add(it) })
    }

    private fun nextStop(): CaptureStopReason? = stops.poll(5, TimeUnit.SECONDS)

    @Test
    fun `audio is delivered as floats and a requested stop releases the stream once`() {
        val stream = FakeStream()
        stream.steps.add { into ->
            into[0] = 16_384
            into[1] = -32_768
            2
        }
        val loop = loop(stream)

        loop.start()
        assertTrue(loop.isRunning)
        assertContentEquals(floatArrayOf(0.5f, -1f), chunks.poll(5, TimeUnit.SECONDS))
        loop.stop()

        assertFalse(loop.isRunning)
        // stop() waited for the thread, so both are already true.
        assertEquals(1, stream.releases.get())
        assertEquals(CaptureStopReason.REQUESTED, stops.poll())
        loop.stop()
        assertNull(stops.poll())
    }

    @Test
    fun `any negative read ends the capture instead of spinning`() {
        for (code in listOf(PcmStream.READ_FAILED, -3, -99)) {
            val stream = FakeStream()
            stream.steps.add { code }
            val loop = loop(stream)

            loop.start()

            assertEquals(CaptureStopReason.ERROR, nextStop(), "code $code")
            assertEquals(1, stream.releases.get())
            assertFalse(loop.isRunning)
        }
    }

    @Test
    fun `a dead stream is reported as preempted`() {
        val stream = FakeStream()
        stream.steps.add { PcmStream.READ_DEAD }
        loop(stream).start()

        assertEquals(CaptureStopReason.PREEMPTED, nextStop())
        assertEquals(1, stream.releases.get())
    }

    @Test
    fun `a failed open is reported and does not wedge the next start`() {
        val good = FakeStream()
        var attempts = 0
        val loop = CaptureLoop(
            open = {
                attempts++
                require(attempts > 1) { "this device cannot capture" }
                good
            },
            onChunk = {},
            onStopped = { stops.add(it) },
        )

        loop.start()
        assertEquals(CaptureStopReason.ERROR, stops.poll())
        assertFalse(loop.isRunning)

        loop.start()
        assertTrue(loop.isRunning)
        loop.stop()
        assertEquals(CaptureStopReason.REQUESTED, stops.poll())
        assertEquals(1, good.releases.get())
    }

    @Test
    fun `a security exception on open is a lost permission`() {
        val loop = CaptureLoop(
            open = { throw SecurityException("no RECORD_AUDIO") },
            onChunk = {},
            onStopped = { stops.add(it) },
        )

        loop.start()

        assertEquals(CaptureStopReason.PERMISSION_LOST, stops.poll())
        assertFalse(loop.isRunning)
    }

    @Test
    fun `a stream that does not start recording is released`() {
        val refusing = listOf<() -> Boolean>(
            { false },
            { throw IllegalStateException("startRecording failed") },
        )
        for (onStart in refusing) {
            val stream = FakeStream(onStart)
            val loop = loop(stream)

            loop.start()

            assertEquals(CaptureStopReason.ERROR, stops.poll())
            assertEquals(1, stream.releases.get())
            assertFalse(loop.isRunning)
        }
    }

    @Test
    fun `permission lost during a read releases the stream`() {
        val stream = FakeStream()
        stream.steps.add { throw SecurityException("revoked") }
        loop(stream).start()

        assertEquals(CaptureStopReason.PERMISSION_LOST, nextStop())
        assertEquals(1, stream.releases.get())
    }

    @Test
    fun `a chunk handler that throws ends the capture and releases the stream`() {
        val stream = FakeStream()
        stream.steps.add { 1 }
        val loop = CaptureLoop(
            open = { stream },
            onChunk = { error("consumer bug") },
            onStopped = { stops.add(it) },
        )

        loop.start()

        assertEquals(CaptureStopReason.ERROR, nextStop())
        assertEquals(1, stream.releases.get())
    }

    @Test
    fun `a second start while running opens nothing`() {
        val stream = FakeStream()
        val loop = loop(stream) // only one stream: a second open would throw

        loop.start()
        loop.start()
        loop.stop()

        assertEquals(CaptureStopReason.REQUESTED, stops.poll())
        assertNull(stops.poll())
    }

    @Test
    fun `stop from the chunk handler does not wait for its own thread`() {
        val stream = FakeStream()
        stream.steps.add { 1 }
        lateinit var loop: CaptureLoop
        loop = CaptureLoop(
            open = { stream },
            onChunk = { loop.stop() },
            onStopped = { stops.add(it) },
            // Far longer than nextStop() waits, so a self-join would fail the test.
            stopTimeoutMs = 60_000L,
        )

        loop.start()

        assertEquals(CaptureStopReason.REQUESTED, nextStop())
        assertEquals(1, stream.releases.get())
    }

    @Test
    fun `a capture can be restarted from the stop callback`() {
        val first = FakeStream()
        first.steps.add { PcmStream.READ_DEAD }
        val second = FakeStream()
        val remaining = ArrayDeque(listOf(first, second))
        val restarted = CountDownLatch(1)
        lateinit var loop: CaptureLoop
        loop = CaptureLoop(
            open = { remaining.removeFirst() },
            onChunk = {},
            onStopped = {
                if (it == CaptureStopReason.PREEMPTED) {
                    loop.start()
                    restarted.countDown()
                }
                stops.add(it)
            },
        )

        loop.start()

        assertTrue(restarted.await(5, TimeUnit.SECONDS))
        assertEquals(CaptureStopReason.PREEMPTED, nextStop())
        assertTrue(loop.isRunning)
        loop.stop()
        assertEquals(CaptureStopReason.REQUESTED, nextStop())
        assertEquals(1, second.releases.get())
    }

    @Test
    fun `a thread that outlives a timed-out stop cannot touch the next capture`() {
        val stuck = FakeStream()
        val entered = CountDownLatch(1)
        val unblock = CountDownLatch(1)
        stuck.steps.add { into ->
            entered.countDown()
            unblock.await()
            into[0] = 1
            1
        }
        val next = FakeStream()
        val remaining = ArrayDeque(listOf(stuck, next))
        val loop = CaptureLoop(
            open = { remaining.removeFirst() },
            onChunk = { chunks.add(it) },
            onStopped = { stops.add(it) },
            stopTimeoutMs = 20L,
        )

        loop.start()
        assertTrue(entered.await(5, TimeUnit.SECONDS))
        loop.stop() // times out: the read is still blocked
        loop.start()
        unblock.countDown()
        assertTrue(stuck.released.await(5, TimeUnit.SECONDS))
        val oldThread = assertNotNull(stuck.reader)
        oldThread.join(5_000L)
        assertFalse(oldThread.isAlive)

        assertTrue(loop.isRunning, "the old thread must not stop the new capture")
        assertEquals(0, next.releases.get())
        assertNull(chunks.poll(), "late audio from the old capture must be dropped")
        assertNull(stops.poll(), "the replaced capture must not report a stop")
        loop.stop()
        assertEquals(CaptureStopReason.REQUESTED, nextStop())
        assertEquals(1, next.releases.get())
        assertEquals(1, stuck.releases.get())
    }

    @Test
    fun `a zero stop timeout is rejected because join would wait forever`() {
        assertFailsWith<IllegalArgumentException> {
            CaptureLoop(open = { FakeStream() }, onChunk = {}, stopTimeoutMs = 0L)
        }
    }
}
