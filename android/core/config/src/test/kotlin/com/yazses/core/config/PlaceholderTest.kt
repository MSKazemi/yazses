package com.yazses.core.config

import kotlin.test.Test
import kotlin.test.assertEquals

class PlaceholderTest {
    @Test
    fun `module is wired into the build`() {
        assertEquals("core/config", Placeholder.MODULE)
    }
}
