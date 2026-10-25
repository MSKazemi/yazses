package com.yazses.core.stt

import java.util.concurrent.Callable
import java.util.concurrent.CancellationException
import java.util.concurrent.ExecutionException
import java.util.concurrent.FutureTask
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.ThreadFactory
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit

/**
 * Runs decode requests for one [SttEngine]: strictly one at a time, in submission
 * order, on a single dedicated daemon thread named `yazses-decode`.
 *
 * A native engine is not thread-safe and one decode must never overlap another
 * (architecture.md §4). The single thread gives that guarantee without a lock held
 * across a decode. Work is never run on `Dispatchers.Default` or the caller's thread.
 *
 * Failure isolation: an exception thrown by the engine fails only the handle of the
 * request that caused it. The thread keeps running and later requests are unaffected.
 *
 * Cancellation has two cases, and the native decode cannot be interrupted in either:
 * - A request that has not started is removed from the queue and never reaches the engine.
 * - A request already running is marked cancelled. Its handle reports cancelled at once and
 *   its result is discarded. The engine call itself still runs to completion, because
 *   [SttEngine] has no in-flight cancel yet. Requests submitted after it wait for that
 *   call to return before they start.
 *
 * Closing: [close] refuses new work, cancels queued requests, lets the running decode
 * finish, calls [SttEngine.close] exactly once on the decode thread, and waits until
 * that thread has ended.
 *
 * The pcm arrays passed to the submit methods must not be modified until their handle
 * is done.
 *
 * Pure JVM: `java.util.concurrent` only, no coroutines, so it runs on API 26.
 *
 * @param engine the engine to drive. The dispatcher owns it and closes it.
 */
public class DecodeDispatcher(private val engine: SttEngine) : AutoCloseable {

    private val lock = Any()

    /** Requests submitted and not yet claimed by the worker. Guarded by [lock]. */
    private val queued = LinkedHashSet<FutureTask<Transcript>>()

    /** Guarded by [lock]. Set once by the first [close]. */
    private var closed = false

    @Volatile
    private var workerThread: Thread? = null

    private val executor = ThreadPoolExecutor(
        1,
        1,
        0L,
        TimeUnit.MILLISECONDS,
        LinkedBlockingQueue(),
        ThreadFactory { runnable ->
            Thread(runnable, THREAD_NAME).also {
                it.isDaemon = true
                workerThread = it
            }
        },
    )

    /**
     * Queue a whole-utterance decode ([SttEngine.transcribe]).
     *
     * After [close], returns a handle that is already failed: [DecodeHandle.await]
     * throws [ExecutionException] whose cause is an [IllegalStateException].
     */
    public fun submitTranscribe(pcm: FloatArray, opts: DecodeOptions): DecodeHandle =
        submit { engine.transcribe(pcm, opts) }

    /**
     * Queue a streaming-window decode ([SttEngine.decodeWindow]). Same ordering and
     * failure rules as [submitTranscribe].
     */
    public fun submitDecodeWindow(pcm: FloatArray, opts: DecodeOptions): DecodeHandle =
        submit { engine.decodeWindow(pcm, opts) }

    /**
     * Stop accepting work and release the engine. Blocks until the running decode (if
     * any) has returned, the engine has been closed and the decode thread has ended.
     *
     * Idempotent: later calls wait for the same shutdown and do not close the engine
     * again. Must not be called from the decode thread, because it would wait for itself.
     *
     * @throws IllegalStateException when called from the decode thread.
     * @throws RuntimeException the engine's own exception if [SttEngine.close] threw.
     *   Only the first call sees it.
     */
    override fun close() {
        check(Thread.currentThread() !== workerThread) {
            "DecodeDispatcher.close() must not be called from the $THREAD_NAME thread"
        }
        val cancelled: List<FutureTask<Transcript>>
        var closeTask: FutureTask<Unit>? = null
        synchronized(lock) {
            if (closed) {
                cancelled = emptyList()
            } else {
                closed = true
                cancelled = queued.toList()
                queued.clear()
                cancelled.forEach { it.cancel(false) }
                closeTask = FutureTask(Callable { engine.close() }).also { executor.execute(it) }
                executor.shutdown()
            }
        }
        cancelled.forEach { executor.remove(it) }
        executor.awaitTermination(Long.MAX_VALUE, TimeUnit.MILLISECONDS)
        workerThread?.join()
        closeTask?.let { task ->
            try {
                task.get()
            } catch (failure: ExecutionException) {
                throw failure.cause ?: failure
            }
        }
    }

    private fun submit(decode: () -> Transcript): DecodeHandle {
        synchronized(lock) {
            if (closed) {
                val rejected = FutureTask(Callable<Transcript> {
                    throw IllegalStateException("DecodeDispatcher is closed; the request was not run")
                })
                rejected.run()
                return DecodeHandle(rejected, ::cancelRequest)
            }
            lateinit var job: FutureTask<Transcript>
            job = FutureTask(Callable {
                // Claim the request. If cancel() or close() got to it first it is not
                // queued any more, so the engine is not called.
                val claimed = synchronized(lock) { queued.remove(job) }
                if (!claimed) throw CancellationException("request was cancelled before it started")
                decode()
            })
            queued.add(job)
            executor.execute(job)
            return DecodeHandle(job, ::cancelRequest)
        }
    }

    /**
     * Removes [job] from the queue if it has not started, and cancels it. The
     * claim and the cancel happen under one lock, so a request is either not run
     * or run to completion, never half of both.
     *
     * @return true when this call cancelled a request that was not already done.
     */
    private fun cancelRequest(job: FutureTask<Transcript>): Boolean {
        val wasQueued: Boolean
        val cancelled: Boolean
        synchronized(lock) {
            wasQueued = queued.remove(job)
            cancelled = job.cancel(false)
        }
        if (wasQueued) executor.remove(job)
        return cancelled
    }

    private companion object {
        const val THREAD_NAME = "yazses-decode"
    }
}

/**
 * The caller's view of one submitted decode.
 *
 * [await] throws [java.util.concurrent.TimeoutException] when the result is not ready
 * in time, [CancellationException] when the request was cancelled, and
 * [ExecutionException] (whose cause is the engine's exception) when the engine failed.
 */
public class DecodeHandle internal constructor(
    private val job: FutureTask<Transcript>,
    private val cancelJob: (FutureTask<Transcript>) -> Boolean,
) {
    /**
     * True once the request has a result, failed, or been cancelled. A cancelled
     * request reports true at once, even while its native decode is still running on
     * the dispatcher thread.
     */
    public val isDone: Boolean get() = job.isDone

    /**
     * Block up to [timeoutMs] milliseconds for the transcript.
     *
     * @throws java.util.concurrent.TimeoutException when no result arrived in time.
     * @throws CancellationException when the request was cancelled.
     * @throws ExecutionException when the engine threw; the cause is the engine's exception.
     */
    public fun await(timeoutMs: Long): Transcript = job.get(timeoutMs, TimeUnit.MILLISECONDS)

    /**
     * Cancel this request. A queued request never reaches the engine. A running request
     * has its result discarded, but its native decode cannot be interrupted yet.
     *
     * @return true when this call cancelled the request; false when it had already
     *   completed, failed or been cancelled.
     */
    public fun cancel(): Boolean = cancelJob(job)
}
