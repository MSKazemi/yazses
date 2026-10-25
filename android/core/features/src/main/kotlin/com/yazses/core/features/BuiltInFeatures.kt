package com.yazses.core.features

/**
 * The features the Android codebase actually has today. Kept deliberately small: a feature
 * is listed only when its code exists in a `:core:*` module, so nothing here is advertised
 * before it works (ADR-MOB-009 §7). Slugs and config keys match the desktop registry.
 *
 * Both entries are [Availability.Available] in both flavours because the code is pure Kotlin
 * with no optional dependency. Features that need an optional engine (Silero VAD, diarization)
 * are not listed until their code exists.
 */
public val BUILT_IN_FEATURES: List<Feature> = listOf(
    Feature(
        slug = "commands",
        displayName = "Voice commands",
        // Matches the desktop default; the Android grammar has no separate opt-in switch.
        enabled = true,
        tier = Tier.DEFAULT_ON,
        availability = Availability.Available,
        onWrites = mapOf("commands.enabled" to "true"),
        offWrites = mapOf("commands.enabled" to "false"),
    ),
    Feature(
        slug = "voice-punctuation",
        displayName = "Voice punctuation",
        // Off by default: the words also occur in ordinary speech (see VoicePunctuation.kt).
        enabled = false,
        tier = Tier.OPTIONAL,
        availability = Availability.Available,
        onWrites = mapOf("commands.voice_punctuation" to "true"),
        offWrites = mapOf("commands.voice_punctuation" to "false"),
    ),
)

/** A registry over [BUILT_IN_FEATURES]. */
public fun builtInRegistry(): FeatureRegistry = FeatureRegistry(BUILT_IN_FEATURES)
