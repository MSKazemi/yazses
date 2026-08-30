package com.yazses.core.commands

/** What a recognised utterance is asking for. */
public enum class IntentType(public val wire: String) {
    DICTATE("dictate"),
    NAVIGATE("navigate"),
    EDIT("edit"),
    REFACTOR("refactor"),
    TERMINAL("terminal"),
    MACRO("macro"),
}

/** A classified utterance. [rawText] is what was said, unmodified. */
public data class CommandIntent(
    val intent: IntentType,
    val action: String,
    val args: Map<String, String> = emptyMap(),
    val rawText: String = "",
)

/** Spelled-out numbers, so "go to line forty" and "go to line 40" agree. */
private val NUMBER_WORDS = mapOf(
    "one" to "1", "two" to "2", "three" to "3", "four" to "4", "five" to "5",
    "six" to "6", "seven" to "7", "eight" to "8", "nine" to "9", "ten" to "10",
)

private val NUMBER_WORD_PATTERN =
    Regex("""\b(${NUMBER_WORDS.keys.joinToString("|")})\b""", RegexOption.IGNORE_CASE)

private fun normaliseNumberWords(text: String): String =
    NUMBER_WORD_PATTERN.replace(text) { NUMBER_WORDS.getValue(it.groupValues[1].lowercase()) }

/**
 * Sentence punctuation Whisper adds to short utterances ("Undo." / "Save file.")
 * which would otherwise break the anchored patterns.
 *
 * Stripped from both ends only — interior punctuation like `main.py` survives.
 */
private const val OUTER_PUNCT = " \t\r\n.,!?;:\"'`…"

private fun stripOuterPunctuation(text: String): String =
    text.trim().trim { it in OUTER_PUNCT }.trim()

/** One grammar rule. [argNames] map capture groups to argument names, in order. */
private data class Rule(
    val pattern: Regex,
    val intent: IntentType,
    val action: String,
    val argNames: List<String> = emptyList(),
)

private fun rule(pattern: String, intent: IntentType, action: String, vararg args: String) =
    Rule(Regex(pattern, RegexOption.IGNORE_CASE), intent, action, args.toList())

/**
 * Evaluated in order; first match wins.
 *
 * Every pattern is anchored at both ends. That is the whole safety property: an
 * unanchored rule turns a sentence that merely contains the words into a command,
 * and "click undo" or "delete that file when you are done" stops being typed.
 */
private val RULES: List<Rule> = listOf(
    // EDIT
    rule("""^delete\s+(?:the\s+)?last\s+(\d+)\s+words?$""", IntentType.EDIT, "delete_words", "n"),
    rule("""^delete\s+(?:the\s+)?last\s+word$""", IntentType.EDIT, "delete_words"),
    rule("""^delete\s+(?:the\s+)?last\s+(\d+)\s+lines?$""", IntentType.EDIT, "delete_lines", "n"),
    rule("""^delete\s+(?:the\s+)?last\s+line$""", IntentType.EDIT, "delete_lines"),
    rule("""^undo(?:\s+that)?$""", IntentType.EDIT, "undo"),
    rule("""^undo\s+(\d+)\s+times?$""", IntentType.EDIT, "undo_n", "n"),
    rule("""^save(?:\s+file)?(?:\s+now)?$""", IntentType.EDIT, "save"),
    rule("""^copy(?:\s+(?:that|this|line|selection))?$""", IntentType.EDIT, "copy"),
    rule("""^paste(?:\s+here)?$""", IntentType.EDIT, "paste"),
    // The two-word forms are the ones people actually say. Without them "comment
    // this line" matched no rule, and an unmatched utterance in command mode is
    // discarded -- so the phrase silently did nothing (desktop: 37997ae).
    rule(
        """^comment(?:\s+(?:this\s+line|the\s+line|this\s+selection|this|line|selection|out))?$""",
        IntentType.EDIT,
        "comment",
    ),
    rule("""^select\s+(\d+)\s+lines?$""", IntentType.EDIT, "select_lines", "n"),
    rule("""^select\s+(?:to\s+)?end$""", IntentType.EDIT, "select_to_end"),
    rule("""^select\s+all$""", IntentType.EDIT, "select_all"),
    // Keystrokes any command mode is expected to handle.
    rule("""^(?:press\s+)?(?:enter|return)$""", IntentType.EDIT, "press_enter"),
    rule("""^new\s+line$""", IntentType.EDIT, "press_enter"),
    rule("""^(?:press\s+)?tab$""", IntentType.EDIT, "press_tab"),
    rule("""^(?:press\s+)?(?:escape|esc)$""", IntentType.EDIT, "press_escape"),
    rule("""^(?:press\s+)?backspace$""", IntentType.EDIT, "press_backspace"),
    rule("""^cut(?:\s+(?:that|this|line|selection))?$""", IntentType.EDIT, "cut"),
    // NAVIGATE
    rule("""^go\s+to\s+line\s+(\d+)$""", IntentType.NAVIGATE, "go_to_line", "n"),
    rule("""^page\s+up$""", IntentType.NAVIGATE, "page_up"),
    rule("""^page\s+down$""", IntentType.NAVIGATE, "page_down"),
    rule("""^(?:go\s+to\s+)?(?:start|beginning)\s+of\s+(?:the\s+)?line$""", IntentType.NAVIGATE, "line_home"),
    rule("""^(?:go\s+to\s+)?end\s+of\s+(?:the\s+)?line$""", IntentType.NAVIGATE, "line_end"),
    rule("""^(?:go|move)\s+up$""", IntentType.NAVIGATE, "arrow_up"),
    rule("""^(?:go|move)\s+down$""", IntentType.NAVIGATE, "arrow_down"),
    rule("""^(?:go|move)\s+left$""", IntentType.NAVIGATE, "arrow_left"),
    rule("""^(?:go|move)\s+right$""", IntentType.NAVIGATE, "arrow_right"),
    rule("""^(?:go\s+to|jump\s+to|find)\s+(?:function|method|def)\s+(.+)$""", IntentType.NAVIGATE, "go_to_function", "name"),
    rule("""^(?:go\s+to|jump\s+to|find)\s+class\s+(.+)$""", IntentType.NAVIGATE, "go_to_class", "name"),
    rule("""^(?:go\s+to|open)\s+file\s+(.+)$""", IntentType.NAVIGATE, "go_to_file", "name"),
    // TERMINAL
    rule("""^run\s+(?:the\s+)?tests?$""", IntentType.TERMINAL, "run_tests"),
    rule("""^run\s+(?:the\s+)?build$""", IntentType.TERMINAL, "run_build"),
    rule("""^run\s+that$""", IntentType.TERMINAL, "run_last"),
    // Open-ended, and the reason the desktop gates it behind a command key: it
    // types the command AND presses Return, and `^run (.+)$` matches any
    // sentence starting with "run" because the sentence is the argument.
    rule("""^run\s+(.+)$""", IntentType.TERMINAL, "run_command", "cmd"),
    // REFACTOR / creation
    rule("""^rename\s+(?:this|symbol|it)\s+to\s+(.+)$""", IntentType.REFACTOR, "rename_symbol", "name"),
    rule("""^new\s+function\s+(?:called?\s+)?(.+)$""", IntentType.EDIT, "new_function", "name"),
    rule("""^new\s+class\s+(?:called?\s+)?(.+)$""", IntentType.EDIT, "new_class", "name"),
    rule("""^new\s+file\s+(?:called?\s+)?(.+)$""", IntentType.EDIT, "new_file", "name"),
)

/** A user macro matched as a whole utterance. */
public interface MacroTable {
    public fun match(text: String): String?
}

/**
 * Classify transcribed text as a command, or as plain dictation.
 *
 * **Dictation is the default and that is deliberate**: typing a command by
 * mistake is recoverable, executing dictation by mistake is not.
 *
 * Tier 0 is the optional user macro table (whole-utterance match); Tier 1 is the
 * regex grammar. The desktop's Tier 2 SLM router has no Android equivalent yet.
 */
public fun classify(text: String, macroTable: MacroTable? = null): CommandIntent {
    if (text.isBlank()) {
        return CommandIntent(IntentType.DICTATE, "inject", rawText = text)
    }

    macroTable?.match(text)?.let { trigger ->
        return CommandIntent(IntentType.MACRO, "expand", mapOf("trigger" to trigger), text)
    }

    val normalised = normaliseNumberWords(stripOuterPunctuation(text))

    for (r in RULES) {
        val m = r.pattern.matchEntire(normalised) ?: continue
        val args = r.argNames.mapIndexedNotNull { i, name ->
            m.groupValues.getOrNull(i + 1)?.trim()?.let { name to it }
        }.toMap()
        return CommandIntent(r.intent, r.action, args, text)
    }

    return CommandIntent(IntentType.DICTATE, "inject", rawText = text)
}
