// Decides whether decoded text may be inserted into the focused field. No I/O.
//
// Password-field refusal is ADR-MOB-004/architecture.md §6 ("Password field focused:
// mic disabled, reason shown"). Blank text is refused rather than typed: a blank
// decode is how an empty field or a `[BLANK_AUDIO]`-style artefact reaches the user.
package com.yazses.core.session

public object DeliveryGuard {

    /** The verdict. A refusal always carries its reason. */
    public sealed interface Decision {
        public class Deliver(public val text: String) : Decision
        public data class Refuse(val reason: Refusal) : Decision
    }

    public enum class Refusal {
        /** Text arrived while the session was not decoding a burst (for example Idle). */
        NOT_DECODING,

        /** The focused field is a password or secure field. */
        SECURE_FIELD,

        /** The text is empty or whitespace only. */
        BLANK_TEXT,
    }

    /**
     * Checks in this order: the session must be decoding, the field must not be secure,
     * and the text must not be blank.
     */
    public fun decide(state: SessionState, text: String, fieldIsSecure: Boolean): Decision = when {
        state != SessionState.Decoding -> Decision.Refuse(Refusal.NOT_DECODING)
        fieldIsSecure -> Decision.Refuse(Refusal.SECURE_FIELD)
        text.isBlank() -> Decision.Refuse(Refusal.BLANK_TEXT)
        else -> Decision.Deliver(text)
    }
}
