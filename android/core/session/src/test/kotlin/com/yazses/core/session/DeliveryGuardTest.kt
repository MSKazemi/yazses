package com.yazses.core.session

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class DeliveryGuardTest {

    @Test
    fun `decoded text is delivered while decoding`() {
        val decision = DeliveryGuard.decide(SessionState.Decoding, "hello", fieldIsSecure = false)
        assertEquals("hello", assertIs<DeliveryGuard.Decision.Deliver>(decision).text)
    }

    @Test
    fun `nothing is delivered during idle`() {
        val decision = DeliveryGuard.decide(SessionState.Idle, "hello", fieldIsSecure = false)
        assertEquals(DeliveryGuard.Refusal.NOT_DECODING, assertIs<DeliveryGuard.Decision.Refuse>(decision).reason)
    }

    @Test
    fun `a password field refuses even good text`() {
        val decision = DeliveryGuard.decide(SessionState.Decoding, "hunter2", fieldIsSecure = true)
        assertEquals(DeliveryGuard.Refusal.SECURE_FIELD, assertIs<DeliveryGuard.Decision.Refuse>(decision).reason)
    }

    @Test
    fun `empty and whitespace text is refused`() {
        for (text in listOf("", "   ", "\n\t")) {
            val decision = DeliveryGuard.decide(SessionState.Decoding, text, fieldIsSecure = false)
            assertEquals(DeliveryGuard.Refusal.BLANK_TEXT, assertIs<DeliveryGuard.Decision.Refuse>(decision).reason)
        }
    }
}
