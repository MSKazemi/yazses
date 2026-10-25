// The record of the last inserted text, so the IME can undo it exactly once. Pure.
package com.yazses.core.session

/**
 * Remembers the last insert. [undo] hands it back once and forgets it, so a second
 * undo does nothing. A newer insert replaces the older one.
 */
public class UndoLastInsert {

    /**
     * One insert. [id] is unique per [UndoLastInsert]. [length] is in UTF-16 code units,
     * which is what `InputConnection.deleteSurroundingText` counts.
     */
    public data class Insert(public val id: Long, public val length: Int)

    private var last: Insert? = null
    private var nextId: Long = 1L

    /** Records [text] as the last insert. Returns the record. */
    public fun remember(text: String): Insert {
        val insert = Insert(id = nextId++, length = text.length)
        last = insert
        return insert
    }

    /** Returns the last insert and clears it. Null when there is nothing to undo. */
    public fun undo(): Insert? {
        val insert = last
        last = null
        return insert
    }
}
