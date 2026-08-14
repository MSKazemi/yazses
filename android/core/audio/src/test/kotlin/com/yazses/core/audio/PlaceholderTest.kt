package com.yazses.core.audio

import kotlin.test.Test
import kotlin.test.assertEquals

class PlaceholderTest {
    @Test
    fun `module is wired into the build`() {
        assertEquals("core/audio", Placeholder.MODULE)
    }
}
