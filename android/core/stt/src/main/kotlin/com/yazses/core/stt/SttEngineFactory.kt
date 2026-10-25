package com.yazses.core.stt

/**
 * Thrown when the requested engine name is unknown or empty.
 *
 * Carries the requested name and the ids that are registered, so the message can
 * say what to change. Never caught and replaced with a silent default: an
 * unknown engine is an error the user must see.
 */
public class UnknownSttEngineException(
    public val requested: String,
    public val known: Set<String>,
) : IllegalArgumentException(
    "Unknown STT engine \"$requested\" (`[stt] engine`). This build provides: " +
        known.sorted().joinToString(", ").ifEmpty { "none" },
)

/**
 * Resolves an engine name to a live [SttEngine].
 *
 * The names here are this module's engine ids (`whisper-cpp`, `sherpa-onnx`). They
 * are NOT the desktop's `[stt] engine` values (`faster-whisper`, `parakeet`,
 * `moonshine`). The desktop falls back to faster-whisper when it meets an unknown
 * name; this factory refuses an unknown or empty name with
 * [UnknownSttEngineException] and never picks a default.
 *
 * Pure: it holds no engine class of its own. The concrete constructors arrive
 * through [registry], so `:core:stt` never references whisper.cpp or
 * sherpa-onnx and `:feature:*` code depends only on this seam.
 *
 * Lookup normalises the name the same way the desktop does (trim, lowercase), so
 * `" Whisper-CPP "` resolves the same as `"whisper-cpp"`. Two registry keys that
 * normalise to the same id are rejected at construction.
 *
 * @param registry engine id -> constructor. Each constructor captures whatever
 *   model path or settings the engine needs. Its engine must report an [SttEngine.id]
 *   equal to the key it is registered under.
 * @throws IllegalArgumentException when two keys normalise to the same id, or a key is blank.
 */
public class SttEngineFactory(
    registry: Map<String, () -> SttEngine>,
) {
    private val constructors: Map<String, () -> SttEngine> = run {
        val rawKeyFor = HashMap<String, String>()
        val normalised = LinkedHashMap<String, () -> SttEngine>()
        for ((key, constructor) in registry) {
            val id = normalise(key)
            require(id.isNotEmpty()) { "registry key \"$key\" is blank after trimming" }
            val earlier = rawKeyFor.put(id, key)
            require(earlier == null) {
                "registry keys \"$earlier\" and \"$key\" both normalise to \"$id\"; " +
                    "register each engine under exactly one key"
            }
            normalised[id] = constructor
        }
        normalised
    }

    /** The engine ids this factory can build, sorted. */
    public val knownIds: Set<String> get() = constructors.keys.toSortedSet()

    /**
     * Build the engine named by [engineName].
     *
     * @throws UnknownSttEngineException when no constructor is registered for the name,
     *   including an empty name.
     * @throws IllegalStateException when the constructed engine reports an [SttEngine.id]
     *   other than the normalised name. That engine is closed before this is thrown.
     */
    public fun create(engineName: String): SttEngine {
        val id = normalise(engineName)
        val constructor = constructors[id]
            ?: throw UnknownSttEngineException(engineName, knownIds)
        val engine = constructor()
        if (engine.id != id) {
            engine.close()
            throw IllegalStateException(
                "engine registered as \"$id\" reports id \"${engine.id}\"; " +
                    "an engine's id must equal the key it is registered under",
            )
        }
        return engine
    }

    private companion object {
        fun normalise(name: String): String = name.trim().lowercase()
    }
}
