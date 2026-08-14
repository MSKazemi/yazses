package com.yazses.core.audio

/**
 * Keeps the last N milliseconds of audio so the first word is never clipped.
 *
 * People with hypophonia (ALS, Parkinson's) often have delayed voice onset:
 * speech starts soft and ramps up, and without this the opening syllable is
 * simply missing from the transcript. Everyone benefits — the gap between
 * pressing the key and the microphone delivering samples is real on every
 * device — but for the users this project exists for it is the difference
 * between a usable transcript and a truncated one.
 *
 * Capture is injected: this buffer is fed chunks and knows nothing about the
 * microphone, which is what makes it testable without one.
 */
public class PreSpeechRingBuffer(
    paddingMs: Int = 300,
    sampleRate: Int = 16_000,
) {
    private val capacity: Int = paddingMs * sampleRate / 1000
    private val buffer = FloatArray(capacity)
    private var head = 0
    private var filled = false

    /** Feed a chunk while idle. Cheap enough to call from the capture thread. */
    public fun push(chunk: FloatArray) {
        if (capacity == 0 || chunk.isEmpty()) return

        if (chunk.size >= capacity) {
            // A chunk larger than the whole window: keep only its tail.
            chunk.copyInto(buffer, 0, chunk.size - capacity, chunk.size)
            head = 0
            filled = true
            return
        }
        val end = head + chunk.size
        if (end <= capacity) {
            chunk.copyInto(buffer, head)
        } else {
            val split = capacity - head
            chunk.copyInto(buffer, head, 0, split)
            chunk.copyInto(buffer, 0, split, chunk.size)
            filled = true
        }
        head = end % capacity
        if (head == 0) filled = true
    }

    /** The buffered audio, oldest sample first. */
    public fun get(): FloatArray {
        if (capacity == 0) return FloatArray(0)
        if (!filled) {
            if (head == 0) return FloatArray(0)
            return buffer.copyOfRange(0, head)
        }
        // Un-wrap: from head to the end, then the start up to head.
        return FloatArray(capacity) { i -> buffer[(head + i) % capacity] }
    }

    /** [audio] with the buffered pre-speech prepended. */
    public fun prependPadding(audio: FloatArray): FloatArray {
        val padding = get()
        if (padding.isEmpty()) return audio
        return padding + audio
    }

    public fun clear() {
        buffer.fill(0f)
        head = 0
        filled = false
    }
}
