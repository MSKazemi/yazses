package com.yazses.core.vad

/**
 * Decides whether a captured burst contains speech at all.
 *
 * The interface exists so the gate can be swapped (a neural VAD, a personal
 * voiceprint gate) without anything upstream knowing.
 */
public fun interface VoiceActivityGate {
    /** True when [samples] should be discarded rather than transcribed. */
    public fun isSilent(samples: FloatArray): Boolean
}

/**
 * The calibrated RMS gate: `mean(|audio|) < threshold` is silence.
 *
 * **Mean, not peak, and that is the whole design.** A door slam or a keyboard
 * click has a high peak and contributes almost nothing to the mean, so it does
 * not make a burst worth transcribing.
 *
 * The threshold is per-user because rooms and microphones differ by orders of
 * magnitude. Too high and quiet speech is silently discarded; too low and room
 * tone is transcribed as words nobody said. That is why it is calibrated rather
 * than guessed, and why the desktop ships a `mic-level` command to set it.
 *
 * Behaviour is pinned by `contract/vectors` — the same JSON the desktop asserts
 * against.
 */
public class CalibratedRmsGate(
    private val threshold: Float = DEFAULT_THRESHOLD,
) : VoiceActivityGate {

    override fun isSilent(samples: FloatArray): Boolean {
        // No samples cannot contain speech. Handing an empty buffer to a
        // recogniser is how a confident hallucination gets typed into someone's
        // document.
        if (samples.isEmpty()) return true
        var sum = 0.0
        for (s in samples) sum += kotlin.math.abs(s.toDouble())
        return (sum / samples.size) < threshold
    }

    public companion object {
        /** Matches the desktop's `[accessibility] vad_threshold` default. */
        public const val DEFAULT_THRESHOLD: Float = 0.0005f
    }
}
