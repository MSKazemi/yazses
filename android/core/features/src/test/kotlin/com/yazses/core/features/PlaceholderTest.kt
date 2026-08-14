package com.yazses.core.features

import kotlin.test.Test
import kotlin.test.assertEquals

class PlaceholderTest {
    @Test
    fun `module is wired into the build`() {
        assertEquals("core/features", Placeholder.MODULE)
    }
}
