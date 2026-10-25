package com.yazses.core.stt

import org.junit.jupiter.api.RepeatedTest
import java.util.concurrent.Callable
import java.util.concurrent.CancellationException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Engine double for the dispatcher tests. Each request is identified by pcm[0].
 * Every decode records when it starts, which thread runs it, and how many decodes
 * are active at once, so the tests assert on what the engine actually saw.
 * A decode can be held on a latch, and an id can be made to throw.
 */
private class RecordingEngine : SttEngine {
    override val id: String = "recording"

    /** Ids in the order their decodes started. */
    val started = LinkedBlockingQueue<Int>()
    val startedIds = ConcurrentLinkedQueue<Int>()
    val decodeThreads = ConcurrentLinkedQueue<Thread>()
    val active = AtomicInteger()
    val maxActive = AtomicInteger()
    val decodesFinished = AtomicInteger()
    val closeCalls = AtomicInteger()
    val closeThreads = ConcurrentLinkedQueue<Thread>()
    val decodesWhenClosed = AtomicInteger(-1)
    val usedAfterClose = AtomicInteger()

    val gates = ConcurrentHashMap<Int, CountDownLatch>()
    val failing = ConcurrentHashMap.newKeySet<Int>()

    fun hold(id: Int): CountDownLatch = CountDownLatch(1).also { gates[id] = it }

    private fun decode(pcm: FloatArray): Transcript {
        val id = pcm[0].toInt()
        if (closeCalls.get() > 0) usedAfterClose.incrementAndGet()
        val now = active.incrementAndGet()
        maxActive.accumulateAndGet(now) { a, b -> maxOf(a, b) }
        decodeThreads.add(Thread.currentThread())
        startedIds.add(id)
        started.add(id)
        try {
            gates[id]?.let { gate ->
                check(gate.await(10, TimeUnit.SECONDS)) { "gate for $id was never released" }
            }
            repeat(5) { Thread.yield() }
            if (id in failing) throw IllegalStateException("boom $id")
            return Transcript(text = "decoded-$id")
        } finally {
            active.decrementAndGet()
            decodesFinished.incrementAndGet()
        }
    }

    override fun transcribe(pcm: FloatArray, opts: DecodeOptions): Transcript = decode(pcm)

    override fun decodeWindow(pcm: FloatArray, opts: DecodeOptions): Transcript = decode(pcm)

    override fun close() {
        closeCalls.incrementAndGet()
        closeThreads.add(Thread.currentThread())
        decodesWhenClosed.set(decodesFinished.get())
    }
}

private fun request(id: Int): FloatArray = floatArrayOf(id.toFloat())

private const val WAIT_MS = 10_000L

private fun RecordingEngine.awaitStarted(id: Int) {
    while (true) {
        val next = started.poll(WAIT_MS, TimeUnit.MILLISECONDS)
            ?: error("decode $id never started")
        if (next == id) return
    }
}

class DecodeDispatcherTest {

    @Test
    fun `transcribe and decodeWindow both run on the engine and return its transcript`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        val a = dispatcher.submitTranscribe(request(1), DecodeOptions())
        val b = dispatcher.submitDecodeWindow(request(2), DecodeOptions())
        assertEquals("decoded-1", a.await(WAIT_MS).text)
        assertEquals("decoded-2", b.await(WAIT_MS).text)
        dispatcher.close()
    }

    @RepeatedTest(20)
    fun `many submitters on several threads never overlap two decodes`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        val submitters = Executors.newFixedThreadPool(8)
        try {
            val handles = (0 until 8).map { t ->
                submitters.submit(Callable {
                    (0 until 25).map { i -> dispatcher.submitTranscribe(request(t * 100 + i), DecodeOptions()) }
                })
            }.flatMap { it.get(WAIT_MS, TimeUnit.MILLISECONDS) }
            assertEquals(200, handles.size)
            for (handle in handles) handle.await(WAIT_MS)
            assertEquals(1, engine.maxActive.get(), "two decodes were active at once")
            assertEquals(200, engine.decodesFinished.get())
            assertEquals(200, engine.startedIds.toSet().size, "a request was lost or decoded twice")
        } finally {
            submitters.shutdownNow()
            dispatcher.close()
        }
    }

    @Test
    fun `requests run in submission order`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        // Hold request 0 so 1..9 are all queued before any of them can start.
        val gate = engine.hold(0)
        val handles = (0..9).map { dispatcher.submitTranscribe(request(it), DecodeOptions()) }
        gate.countDown()
        handles.forEach { it.await(WAIT_MS) }
        assertEquals((0..9).toList(), engine.startedIds.toList())
        dispatcher.close()
    }

    @Test
    fun `cancelling a queued request means the engine never decodes it`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        val gate = engine.hold(0)
        val first = dispatcher.submitTranscribe(request(0), DecodeOptions())
        engine.awaitStarted(0)
        val queued = dispatcher.submitTranscribe(request(2), DecodeOptions())
        val after = dispatcher.submitTranscribe(request(3), DecodeOptions())

        assertTrue(queued.cancel(), "a queued request must be cancellable")
        assertTrue(queued.isDone)
        assertFailsWith<CancellationException> { queued.await(WAIT_MS) }

        gate.countDown()
        assertEquals("decoded-0", first.await(WAIT_MS).text)
        assertEquals("decoded-3", after.await(WAIT_MS).text)
        assertEquals(listOf(0, 3), engine.startedIds.toList())
        dispatcher.close()
    }

    @Test
    fun `cancelling a running request discards its result and the next request still runs`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        val gate = engine.hold(0)
        val running = dispatcher.submitTranscribe(request(0), DecodeOptions())
        engine.awaitStarted(0)

        assertTrue(running.cancel())
        assertFailsWith<CancellationException> { running.await(WAIT_MS) }

        val next = dispatcher.submitTranscribe(request(1), DecodeOptions())
        gate.countDown()
        assertEquals("decoded-1", next.await(WAIT_MS).text)
        // The discarded decode finished on the same thread before request 1 started.
        assertEquals(listOf(0, 1), engine.startedIds.toList())
        assertEquals(1, engine.maxActive.get())
        assertFailsWith<CancellationException> { running.await(WAIT_MS) }
        dispatcher.close()
    }

    @Test
    fun `a completed request cannot be cancelled`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        val done = dispatcher.submitTranscribe(request(5), DecodeOptions())
        assertEquals("decoded-5", done.await(WAIT_MS).text)
        assertFalse(done.cancel())
        assertEquals("decoded-5", done.await(WAIT_MS).text)
        dispatcher.close()
    }

    @Test
    fun `an engine exception fails only its own request and keeps the thread and order`() {
        val engine = RecordingEngine()
        engine.failing.add(1)
        val dispatcher = DecodeDispatcher(engine)
        val ok0 = dispatcher.submitTranscribe(request(0), DecodeOptions())
        val bad = dispatcher.submitTranscribe(request(1), DecodeOptions())
        val ok2 = dispatcher.submitDecodeWindow(request(2), DecodeOptions())

        assertEquals("decoded-0", ok0.await(WAIT_MS).text)
        val failure = assertFailsWith<ExecutionException> { bad.await(WAIT_MS) }
        assertEquals("boom 1", (failure.cause as IllegalStateException).message)
        assertEquals("decoded-2", ok2.await(WAIT_MS).text)

        assertEquals(listOf(0, 1, 2), engine.startedIds.toList())
        assertEquals(1, engine.decodeThreads.toSet().size, "the failure must not replace the thread")
        dispatcher.close()
    }

    @Test
    fun `decodes run on one daemon thread named yazses-decode`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        dispatcher.submitTranscribe(request(0), DecodeOptions()).await(WAIT_MS)
        val thread = engine.decodeThreads.single()
        assertEquals("yazses-decode", thread.name)
        assertTrue(thread.isDaemon)
        dispatcher.close()
    }

    @Test
    fun `close cancels queued work, lets the running decode finish, then closes the engine once on the decode thread`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        val gate = engine.hold(0)
        val running = dispatcher.submitTranscribe(request(0), DecodeOptions())
        engine.awaitStarted(0)
        val queued = dispatcher.submitTranscribe(request(1), DecodeOptions())

        // close() blocks until the running decode returns, so it runs on its own thread.
        val closer = Thread { dispatcher.close() }
        closer.start()
        // Only a cancelled handle can produce this; it proves close() has begun.
        assertFailsWith<CancellationException> { queued.await(WAIT_MS) }

        gate.countDown()
        closer.join(WAIT_MS)
        assertFalse(closer.isAlive, "close() did not return")
        assertEquals("decoded-0", running.await(WAIT_MS).text)
        assertEquals(listOf(0), engine.startedIds.toList())
        assertEquals(1, engine.closeCalls.get())
        assertEquals(1, engine.decodesWhenClosed.get(), "engine.close ran before the last decode finished")
        assertEquals("yazses-decode", engine.closeThreads.single().name)
        assertEquals(0, engine.usedAfterClose.get())

        dispatcher.close()
        assertEquals(1, engine.closeCalls.get(), "a second close must not close the engine again")
    }

    @Test
    fun `close with no submissions still closes the engine once`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        dispatcher.close()
        dispatcher.close()
        assertEquals(1, engine.closeCalls.get())
        assertEquals(0, engine.decodesWhenClosed.get())
    }

    @Test
    fun `a submit after close returns a handle that already failed, and never reaches the engine`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        dispatcher.close()
        val late = dispatcher.submitTranscribe(request(7), DecodeOptions())
        assertTrue(late.isDone)
        val failure = assertFailsWith<ExecutionException> { late.await(WAIT_MS) }
        assertTrue(failure.cause is IllegalStateException, "cause was ${failure.cause}")
        assertEquals(0, engine.started.size)
        assertEquals(1, engine.closeCalls.get())
    }

    @Test
    fun `the decode thread terminates after close`() {
        val engine = RecordingEngine()
        val dispatcher = DecodeDispatcher(engine)
        dispatcher.submitTranscribe(request(0), DecodeOptions()).await(WAIT_MS)
        val thread = engine.decodeThreads.single()
        assertTrue(thread.isAlive)
        dispatcher.close()
        thread.join(WAIT_MS)
        assertFalse(thread.isAlive, "the yazses-decode thread leaked past close()")
    }
}
