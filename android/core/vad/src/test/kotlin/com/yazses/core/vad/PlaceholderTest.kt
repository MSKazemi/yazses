package com.yazses.core.vad

import kotlin.test.Test
import kotlin.test.assertEquals

class PlaceholderTest {
    @Test
    fun `module is wired into the build`() {
        assertEquals("core/vad", Placeholder.MODULE)
    }
}
