package com.yazses.platform.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Why capture stopped. The caller has to tell these apart: two of them are the
 * user's doing and one is a fault, and showing "recording failed" for a revoked
 * permission sends someone hunting for a bug that is not there.
 */
public enum class CaptureStopReason {
    /** [MicrophoneCapture.stop] was called. */
    REQUESTED,

    /** The microphone permission went away mid-session. */
    PERMISSION_LOST,

    /** Another app took the microphone. */
    PREEMPTED,

    /** `AudioRecord` reported an error. */
    ERROR,
}

/**
 * Thin `AudioRecord` shim: 16 kHz mono PCM16 on a dedicated thread.
 *
 * Two properties matter more than anything else here.
 *
 * **The capture thread never blocks on decode.** It reads into the buffer and
 * hands chunks to [onChunk], which must return promptly; anything slow belongs on
 * another dispatcher. A capture thread stalled behind a decode drops audio, and
 * dropped audio is a missing word the user has no way to know about.
 *
 * **It stops cleanly when the microphone is taken away.** Permission revoked
 * mid-session and another app grabbing the mic both look like read errors, and
 * both must end with a stop and a reason rather than a crash inside an IME — an
 * ANR in a keyboard takes the user's ability to type with it.
 *
 * The samples are normalised to `FloatArray` in −1..1 because that is what
 * `:core:vad` and `:core:stt` accept, and converting once here keeps the
 * PCM16 detail out of every module downstream.
 */
public class MicrophoneCapture(
    private val sampleRate: Int = 16_000,
    private val onChunk: (FloatArray) -> Unit,
    private val onStopped: (CaptureStopReason) -> Unit = {},
) {
    private val running = AtomicBoolean(false)
    private var recorder: AudioRecord? = null
    private var worker: Thread? = null

    public val isRunning: Boolean get() = running.get()

    /**
     * Minimum buffer the device demands, floored to something that does not wake
     * the thread absurdly often. `AudioRecord` fails to initialise below its own
     * minimum, and that minimum varies wildly between devices.
     */
    private fun bufferSize(): Int {
        val minimum = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        require(minimum > 0) { "this device cannot capture 16 kHz mono PCM16" }
        return maxOf(minimum, sampleRate / 10 * 2) // ~100 ms of 16-bit samples
    }

    /** Start capturing. Caller must already hold `RECORD_AUDIO`. */
    @SuppressLint("MissingPermission")
    public fun start() {
        if (!running.compareAndSet(false, true)) return

        val size = bufferSize()
        val record = AudioRecord(
            // VOICE_RECOGNITION asks the platform for the processing chain tuned
            // for speech rather than for a phone call or a video: no aggressive
            // AGC, no comfort noise. It is the difference between a clean
            // transcript and one full of clipped openings.
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            size,
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            running.set(false)
            onStopped(CaptureStopReason.ERROR)
            return
        }
        recorder = record
        record.startRecording()

        worker = thread(name = "yazses-capture", isDaemon = true) {
            val pcm = ShortArray(size / 2)
            var reason = CaptureStopReason.REQUESTED
            try {
                while (running.get()) {
                    when (val read = record.read(pcm, 0, pcm.size)) {
                        AudioRecord.ERROR_INVALID_OPERATION,
                        AudioRecord.ERROR_BAD_VALUE,
                        AudioRecord.ERROR_DEAD_OBJECT,
                        -> {
                            // A dead object is the platform telling us the
                            // session is gone: the mic was taken, or the
                            // permission was revoked. Either way, stop.
                            reason = if (read == AudioRecord.ERROR_DEAD_OBJECT) {
                                CaptureStopReason.PREEMPTED
                            } else {
                                CaptureStopReason.ERROR
                            }
                            break
                        }
                        else -> if (read > 0) onChunk(toFloats(pcm, read))
                    }
                }
            } catch (_: SecurityException) {
                // Permission revoked while we held the stream.
                reason = CaptureStopReason.PERMISSION_LOST
            } finally {
                teardown()
                onStopped(reason)
            }
        }
    }

    /** Stop capturing and release the device. Safe to call twice. */
    public fun stop() {
        if (!running.compareAndSet(true, false)) return
        worker?.join(STOP_TIMEOUT_MS)
        worker = null
    }

    private fun teardown() {
        running.set(false)
        recorder?.runCatching {
            if (recordingState == AudioRecord.RECORDSTATE_RECORDING) stop()
            release()
        }
        recorder = null
    }

    private companion object {
        const val STOP_TIMEOUT_MS = 500L
    }
}

/**
 * PCM16 to normalised floats.
 *
 * Kept top-level and pure so it is unit-testable without a device — the one part
 * of this file that can be.
 */
public fun toFloats(pcm: ShortArray, count: Int = pcm.size): FloatArray =
    FloatArray(count) { i -> pcm[i] / 32768f }
