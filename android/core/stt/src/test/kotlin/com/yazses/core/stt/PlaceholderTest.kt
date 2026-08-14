package com.yazses.core.stt

import kotlin.test.Test
import kotlin.test.assertEquals

class PlaceholderTest {
    @Test
    fun `module is wired into the build`() {
        assertEquals("core/stt", Placeholder.MODULE)
    }
}
