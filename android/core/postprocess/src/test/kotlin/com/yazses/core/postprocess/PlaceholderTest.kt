package com.yazses.core.postprocess

import kotlin.test.Test
import kotlin.test.assertEquals

class PlaceholderTest {
    @Test
    fun `module is wired into the build`() {
        assertEquals("core/postprocess", Placeholder.MODULE)
    }
}
