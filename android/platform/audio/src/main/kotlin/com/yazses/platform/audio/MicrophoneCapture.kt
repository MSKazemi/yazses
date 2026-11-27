package com.yazses.platform.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import com.yazses.core.audio.CaptureLoop
import com.yazses.core.audio.CaptureStopReason
import com.yazses.core.audio.PcmStream

/**
 * Thin `AudioRecord` shim: 16 kHz mono PCM16 on a dedicated thread.
 *
 * The threading, the stop rules and the guarantee that the recorder is always released
 * live in [CaptureLoop] (`:core:audio`), where they are unit-tested without a device.
 * This class only translates `AudioRecord` into a [PcmStream].
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
 */
public class MicrophoneCapture(
    private val sampleRate: Int = 16_000,
    onChunk: (FloatArray) -> Unit,
    onStopped: (CaptureStopReason) -> Unit = {},
) {
    private val loop = CaptureLoop(::openStream, onChunk, onStopped)

    public val isRunning: Boolean get() = loop.isRunning

    /** Start capturing. Caller must already hold `RECORD_AUDIO`. */
    public fun start() {
        loop.start()
    }

    /** Stop capturing and release the device. Safe to call twice. */
    public fun stop() {
        loop.stop()
    }

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

    @SuppressLint("MissingPermission")
    private fun openStream(): PcmStream {
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
            throw IllegalStateException("AudioRecord did not initialise")
        }
        return AudioRecordStream(record, size / 2)
    }
}

private class AudioRecordStream(
    private val record: AudioRecord,
    override val bufferSamples: Int,
) : PcmStream {

    override fun start(): Boolean {
        record.startRecording()
        return record.recordingState == AudioRecord.RECORDSTATE_RECORDING
    }

    override fun read(into: ShortArray): Int {
        val read = record.read(into, 0, into.size)
        // Every negative code ends the capture, including the generic AudioRecord.ERROR.
        // A dead object is the platform telling us the session is gone.
        return when {
            read >= 0 -> read
            read == AudioRecord.ERROR_DEAD_OBJECT -> PcmStream.READ_DEAD
            else -> PcmStream.READ_FAILED
        }
    }

    override fun release() {
        // A failing stop() must not skip release(), or the microphone stays held.
        record.runCatching {
            if (recordingState == AudioRecord.RECORDSTATE_RECORDING) stop()
        }
        record.release()
    }
}
