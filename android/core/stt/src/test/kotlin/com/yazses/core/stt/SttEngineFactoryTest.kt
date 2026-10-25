package com.yazses.core.stt

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotSame
import kotlin.test.assertTrue

class SttEngineFactoryTest {

    private val factory = SttEngineFactory(
        mapOf(
            "whisper-cpp" to { FakeSttEngine(id = "whisper-cpp") },
            "sherpa-onnx" to { FakeSttEngine(id = "sherpa-onnx") },
        ),
    )

    @Test
    fun `a registered id resolves to its engine`() {
        val engine = factory.create("whisper-cpp")
        assertEquals("whisper-cpp", engine.id)
    }

    @Test
    fun `lookup ignores case and surrounding whitespace, as the desktop does`() {
        assertEquals("sherpa-onnx", factory.create("  Sherpa-ONNX ").id)
    }

    @Test
    fun `an unknown id is rejected with the requested name and the known ids`() {
        val error = assertFailsWith<UnknownSttEngineException> { factory.create("faster-whisper") }
        assertEquals("faster-whisper", error.requested)
        assertEquals(setOf("sherpa-onnx", "whisper-cpp"), error.known)
        assertTrue(error.message!!.contains("faster-whisper"), error.message)
        assertTrue(error.message!!.contains("sherpa-onnx, whisper-cpp"), error.message)
    }

    @Test
    fun `an empty name is rejected, never defaulted`() {
        assertFailsWith<UnknownSttEngineException> { factory.create("") }
    }

    @Test
    fun `an empty registry says so instead of listing nothing`() {
        val error = assertFailsWith<UnknownSttEngineException> {
            SttEngineFactory(emptyMap()).create("whisper-cpp")
        }
        assertTrue(error.message!!.endsWith("none"), error.message)
    }

    @Test
    fun `each create builds a fresh engine through its constructor`() {
        val first = factory.create("whisper-cpp")
        val second = factory.create("whisper-cpp")
        assertNotSame(first, second)
    }

    @Test
    fun `knownIds lists the registered ids sorted`() {
        assertEquals(listOf("sherpa-onnx", "whisper-cpp"), factory.knownIds.toList())
    }
}
