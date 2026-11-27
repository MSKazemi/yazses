package com.yazses.core.audio

import kotlin.concurrent.thread

/**
 * Why capture stopped. The caller has to tell these apart: two of them are the
 * user's doing and one is a fault, and showing "recording failed" for a revoked
 * permission sends someone hunting for a bug that is not there.
 */
public enum class CaptureStopReason {
    /** [CaptureLoop.stop] was called. */
    REQUESTED,

    /** The microphone permission is missing, or went away mid-session. */
    PERMISSION_LOST,

    /** Another app took the microphone. */
    PREEMPTED,

    /** The recorder could not be opened or started, or reading from it failed. */
    ERROR,
}

/**
 * One open microphone stream. The platform implements it; tests fake it.
 *
 * Every method may throw: a `SecurityException` is reported as
 * [CaptureStopReason.PERMISSION_LOST], any other runtime exception as
 * [CaptureStopReason.ERROR].
 */
public interface PcmStream {
    /** How many samples to ask for in one [read]. Positive. */
    public val bufferSamples: Int

    /** Starts recording. False when the device did not enter the recording state. */
    public fun start(): Boolean

    /**
     * Blocks until audio is available and copies it into [into]. Returns the number of
     * samples read (0 or more), or a negative code: [READ_DEAD] when the session is gone,
     * any other negative value for a failed read.
     */
    public fun read(into: ShortArray): Int

    /** Stops recording and frees the device. Called exactly once by [CaptureLoop]. */
    public fun release()

    public companion object {
        /** A read failed. */
        public const val READ_FAILED: Int = -1

        /** The stream is dead: another owner took the microphone. */
        public const val READ_DEAD: Int = -2
    }
}

/**
 * Runs one capture at a time on a dedicated thread, and guarantees that every stream it
 * opens is released, whatever goes wrong.
 *
 * Each [start] is its own session with its own stream and stop flag. That is what keeps a
 * capture thread that outlived a timed-out [stop] from touching the next recording: it
 * releases only its own stream, its late audio is dropped, and it does not report a stop
 * for a recording that has already been replaced.
 *
 * Apart from that replaced case, every [start] that is not ignored ends in exactly one
 * [onStopped] call. It runs on the capture thread, or on the caller's thread when the
 * stream could not be opened or started. The loop is already idle when it runs, so it may
 * call [start] again.
 *
 * @param open opens a new stream. It must free whatever it half-built before throwing.
 * @param onChunk receives audio on the capture thread and must return promptly. If it
 *   throws a runtime exception the capture ends with [CaptureStopReason.ERROR].
 * @param onStopped told why a capture ended, after its stream was released.
 * @param stopTimeoutMs how long [stop] waits for the capture thread. Positive.
 */
public class CaptureLoop(
    private val open: () -> PcmStream,
    private val onChunk: (FloatArray) -> Unit,
    private val onStopped: (CaptureStopReason) -> Unit = {},
    private val stopTimeoutMs: Long = DEFAULT_STOP_TIMEOUT_MS,
) {
    init {
        // Thread.join(0) waits forever.
        require(stopTimeoutMs > 0) { "stopTimeoutMs must be > 0, was $stopTimeoutMs" }
    }

    private class Session {
        @Volatile
        var stopRequested: Boolean = false

        @Volatile
        var worker: Thread? = null
    }

    private val lock = Any()

    /** The session that owns the loop, or null when idle. Guarded by [lock]. */
    private var current: Session? = null

    /** True from [start] until [stop] is called or the capture ends by itself. */
    public val isRunning: Boolean
        get() = synchronized(lock) { current?.stopRequested == false }

    /** Starts a capture. Ignored while one is running. */
    public fun start() {
        val session = Session()
        synchronized(lock) {
            if (current?.stopRequested == false) return
            current = session
        }

        var stream: PcmStream? = null
        val failure: CaptureStopReason? = try {
            val opened = open()
            stream = opened
            if (opened.start()) null else CaptureStopReason.ERROR
        } catch (_: SecurityException) {
            CaptureStopReason.PERMISSION_LOST
        } catch (_: RuntimeException) {
            CaptureStopReason.ERROR
        }
        val ready = stream
        if (failure != null || ready == null) {
            finish(session, ready, failure ?: CaptureStopReason.ERROR)
            return
        }

        val worker = thread(start = false, isDaemon = true, name = THREAD_NAME) {
            capture(session, ready)
        }
        session.worker = worker
        worker.start()
    }

    /**
     * Stops the running capture and waits up to `stopTimeoutMs` for its stream to be
     * released. Safe to call twice, when idle, and from [onChunk] (it does not wait for
     * its own thread).
     */
    public fun stop() {
        val session = synchronized(lock) {
            val active = current ?: return
            if (active.stopRequested) return
            active.stopRequested = true
            active
        }
        val worker = session.worker ?: return
        if (worker === Thread.currentThread()) return
        try {
            worker.join(stopTimeoutMs)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
    }

    private fun capture(session: Session, stream: PcmStream) {
        var reason = CaptureStopReason.REQUESTED
        try {
            val pcm = ShortArray(stream.bufferSamples)
            while (!session.stopRequested) {
                val read = stream.read(pcm)
                if (read < 0) {
                    // An error that follows a stop request is the stop, not a fault.
                    if (!session.stopRequested) {
                        reason = if (read == PcmStream.READ_DEAD) {
                            CaptureStopReason.PREEMPTED
                        } else {
                            CaptureStopReason.ERROR
                        }
                    }
                    break
                }
                // The chunk in flight when stop() was called is still delivered: it is the
                // end of the utterance. Audio from a replaced session is not.
                if (read > 0 && isCurrent(session)) onChunk(toFloats(pcm, read))
            }
        } catch (_: SecurityException) {
            reason = CaptureStopReason.PERMISSION_LOST
        } catch (_: RuntimeException) {
            reason = CaptureStopReason.ERROR
        } finally {
            finish(session, stream, reason)
        }
    }

    private fun isCurrent(session: Session): Boolean = synchronized(lock) { current === session }

    private fun finish(session: Session, stream: PcmStream?, reason: CaptureStopReason) {
        try {
            stream?.release()
        } catch (_: RuntimeException) {
            // Nothing more can be done with a stream that will not release, and the
            // caller still has to hear that the capture ended.
        }
        val replaced = synchronized(lock) {
            session.stopRequested = true
            if (current === session) {
                current = null
                false
            } else {
                true
            }
        }
        if (!replaced) onStopped(reason)
    }

    public companion object {
        /** How long [stop] waits for the capture thread by default. */
        public const val DEFAULT_STOP_TIMEOUT_MS: Long = 500L

        private const val THREAD_NAME = "yazses-capture"
    }
}
