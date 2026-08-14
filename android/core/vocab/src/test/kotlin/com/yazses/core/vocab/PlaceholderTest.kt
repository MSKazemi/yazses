package com.yazses.core.vocab

import kotlin.test.Test
import kotlin.test.assertEquals

class PlaceholderTest {
    @Test
    fun `module is wired into the build`() {
        assertEquals("core/vocab", Placeholder.MODULE)
    }
}
