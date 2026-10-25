package com.yazses.core.session

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class UndoLastInsertTest {

    @Test
    fun `nothing to undo before any insert`() {
        assertNull(UndoLastInsert().undo())
    }

    @Test
    fun `undo returns the last insert exactly once`() {
        val undo = UndoLastInsert()
        undo.remember("hello")
        assertEquals(UndoLastInsert.Insert(id = 1L, length = 5), undo.undo())
        assertNull(undo.undo())
    }

    @Test
    fun `a newer insert replaces the older one`() {
        val undo = UndoLastInsert()
        undo.remember("first")
        undo.remember("second")
        assertEquals(UndoLastInsert.Insert(id = 2L, length = 6), undo.undo())
    }

    @Test
    fun `invalidate forgets the remembered insert so undo returns nothing`() {
        val undo = UndoLastInsert()
        undo.remember("hello")
        undo.invalidate()
        assertNull(undo.undo())
    }

    @Test
    fun `length counts UTF-16 code units as the input connection does`() {
        val undo = UndoLastInsert()
        undo.remember("😀") // one emoji, two UTF-16 units
        assertEquals(2, undo.undo()?.length)
    }
}
