package com.yazses.core.stt

/**
 * Thrown when `[stt] engine` names an engine this build does not register.
 *
 * Carries the requested id and the ids that are registered, so the message can
 * say what to change. Never caught and replaced with a silent default: an
 * unknown engine is an error the user must see (ADR-MOB-005 §1).
 */
public class UnknownSttEngineException(
    public val requested: String,
    public val known: Set<String>,
) : IllegalArgumentException(
    "Unknown STT engine \"$requested\" (`[stt] engine`). This build provides: " +
        known.sorted().joinToString(", ").ifEmpty { "none" },
)

/**
 * Resolves `[stt] engine` to a live [SttEngine].
 *
 * Pure: it holds no engine class of its own. The concrete constructors arrive
 * through [registry], so `:core:stt` never references whisper.cpp or
 * sherpa-onnx and `:feature:*` code depends only on this seam.
 *
 * Lookup normalises the name the way the desktop does (trim, lowercase), so
 * `" Whisper-CPP "` in a config file resolves the same as `"whisper-cpp"`.
 *
 * @param registry engine id -> constructor. Each constructor captures whatever
 *   model path or settings the engine needs.
 */
public class SttEngineFactory(
    registry: Map<String, () -> SttEngine>,
) {
    private val constructors: Map<String, () -> SttEngine> =
        registry.mapKeys { (key, _) -> normalise(key) }

    /** The engine ids this factory can build, sorted. */
    public val knownIds: Set<String> get() = constructors.keys.toSortedSet()

    /**
     * Build the engine named by [engineName].
     *
     * @throws UnknownSttEngineException when no constructor is registered for it.
     */
    public fun create(engineName: String): SttEngine {
        val constructor = constructors[normalise(engineName)]
            ?: throw UnknownSttEngineException(engineName, knownIds)
        return constructor()
    }

    private companion object {
        fun normalise(name: String): String = name.trim().lowercase()
    }
}
