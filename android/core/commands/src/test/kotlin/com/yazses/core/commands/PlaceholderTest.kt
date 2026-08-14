package com.yazses.core.commands

import kotlin.test.Test
import kotlin.test.assertEquals

class PlaceholderTest {
    @Test
    fun `module is wired into the build`() {
        assertEquals("core/commands", Placeholder.MODULE)
    }
}
