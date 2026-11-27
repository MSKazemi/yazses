package com.yazses.core.audio

/**
 * PCM16 to normalised floats in −1..1, the form `:core:vad` and `:core:stt` accept.
 * Converting once, at capture, keeps the PCM16 detail out of every module downstream.
 */
public fun toFloats(pcm: ShortArray, count: Int = pcm.size): FloatArray =
    FloatArray(count) { i -> pcm[i] / 32768f }
