package com.yazses.core.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue

class ResumePlanTest {

    private val size = 1_000L

    @Test
    fun `no partial file means a fresh download, whether or not ranges work`() {
        assertEquals(ResumePlan.FromStart, ResumePlan.plan(0, size, serverSupportsRanges = true))
        assertEquals(ResumePlan.FromStart, ResumePlan.plan(0, size, serverSupportsRanges = false))
    }

    @Test
    fun `a partial file is resumed at its length when the server honours ranges`() {
        assertEquals(ResumePlan.ResumeFrom(1L), ResumePlan.plan(1, size, serverSupportsRanges = true))
        assertEquals(ResumePlan.ResumeFrom(400L), ResumePlan.plan(400, size, serverSupportsRanges = true))
    }

    @Test
    fun `one byte short of the declared size is still resumable, at size minus one`() {
        assertEquals(
            ResumePlan.ResumeFrom(size - 1),
            ResumePlan.plan(size - 1, size, serverSupportsRanges = true),
        )
    }

    @Test
    fun `a partial file is restarted from zero when ranges are not supported`() {
        assertEquals(ResumePlan.FromStart, ResumePlan.plan(400, size, serverSupportsRanges = false))
        assertEquals(ResumePlan.FromStart, ResumePlan.plan(size - 1, size, serverSupportsRanges = false))
    }

    @Test
    fun `a partial file exactly the declared size is already complete, with or without ranges`() {
        assertEquals(ResumePlan.AlreadyComplete, ResumePlan.plan(size, size, serverSupportsRanges = true))
        assertEquals(ResumePlan.AlreadyComplete, ResumePlan.plan(size, size, serverSupportsRanges = false))
    }

    @Test
    fun `a partial file one byte longer than the declared size is corrupt`() {
        assertEquals(
            ResumePlan.Corrupt(partialBytes = size + 1, expectedBytes = size),
            ResumePlan.plan(size + 1, size, serverSupportsRanges = true),
        )
    }

    @Test
    fun `a partial file far longer than the declared size is corrupt, never resumed`() {
        val plan = ResumePlan.plan(size * 10, size, serverSupportsRanges = true)
        assertIs<ResumePlan.Corrupt>(plan)
    }

    @Test
    fun `no plan ever resumes at or past the declared size`() {
        for (partial in 0L..(size + 3)) {
            for (ranges in listOf(true, false)) {
                val plan = ResumePlan.plan(partial, size, ranges)
                if (plan is ResumePlan.ResumeFrom) {
                    assertTrue(plan.offset in 1 until size, "offset ${plan.offset} for partial $partial")
                }
            }
        }
    }

    @Test
    fun `a declared size that is not positive is a programming error`() {
        assertFailsWith<IllegalArgumentException> { ResumePlan.plan(0, 0, true) }
        assertFailsWith<IllegalArgumentException> { ResumePlan.plan(0, -1, true) }
    }

    @Test
    fun `a negative partial length is a programming error`() {
        assertFailsWith<IllegalArgumentException> { ResumePlan.plan(-1, size, true) }
    }
}
