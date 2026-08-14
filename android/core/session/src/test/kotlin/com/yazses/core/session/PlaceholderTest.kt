package com.yazses.core.session

import kotlin.test.Test
import kotlin.test.assertEquals

class PlaceholderTest {
    @Test
    fun `module is wired into the build`() {
        assertEquals("core/session", Placeholder.MODULE)
    }
}
