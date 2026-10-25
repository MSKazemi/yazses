package com.yazses.core.features

/**
 * Why [FeatureRegistry.toggle] refused to change a feature.
 *
 * A refusal is a value, not an exception, so the caller has to handle it; the registry never
 * reports success for a change this build cannot deliver.
 */
public sealed interface ToggleError {
    public val slug: String

    /** No feature with this slug is registered. */
    public data class UnknownFeature(override val slug: String) : ToggleError

    /** The feature was never built into this flavour. */
    public data class NotInThisBuild(override val slug: String, val flavour: Flavour) : ToggleError

    /** The feature is shipped, but a dependency it needs is missing. */
    public data class MissingOptionalDependency(override val slug: String, val reason: String) : ToggleError
}

/** The outcome of [FeatureRegistry.toggle]: either the exact config writes, or a typed refusal. */
public sealed interface ToggleResult {
    /** The config writes that make the feature [on]. Pure data; nothing has been written. */
    public data class Writes(val slug: String, val on: Boolean, val writes: Map<String, String>) : ToggleResult

    public data class Refused(val error: ToggleError) : ToggleResult
}

/**
 * The registry of user-facing features for this build. Pure: no I/O, no Android types.
 *
 * It is built from an injected list so the app supplies the data and tests supply their own.
 * [toggle] only computes the config writes; the caller persists them.
 */
public class FeatureRegistry(features: List<Feature>) {
    private val ordered: List<Feature> = features.toList()
    private val bySlug: Map<String, Feature>

    init {
        val duplicates = ordered.groupBy { it.slug }.filterValues { it.size > 1 }.keys
        require(duplicates.isEmpty()) { "duplicate feature slugs: ${duplicates.sorted().joinToString()}" }
        bySlug = ordered.associateBy { it.slug }
    }

    /** Every feature, in the order it was registered. */
    public val features: List<Feature> get() = ordered

    /** The feature with [slug], or null when none is registered. */
    public fun find(slug: String): Feature? = bySlug[slug]

    /** Features grouped by tier, tiers in [Tier] declaration order, empty tiers omitted. */
    public fun groupedByTier(): Map<Tier, List<Feature>> =
        ordered.groupBy { it.tier }.toSortedMap(compareBy { it.ordinal })

    /**
     * The config writes that set [slug] to [on], or a typed refusal.
     *
     * Refuses with [ToggleError.NotInThisBuild] or [ToggleError.MissingOptionalDependency] when the
     * feature cannot run in this build, because writing its keys would claim a change that
     * does nothing. Enabling and disabling are both refused for such a feature, since the
     * state it would report is not one the build can honour.
     */
    public fun toggle(slug: String, on: Boolean): ToggleResult {
        val feature = bySlug[slug] ?: return ToggleResult.Refused(ToggleError.UnknownFeature(slug))
        return when (val availability = feature.availability) {
            is Availability.Available ->
                ToggleResult.Writes(slug, on, if (on) feature.onWrites else feature.offWrites)
            is Availability.NotInThisBuild ->
                ToggleResult.Refused(ToggleError.NotInThisBuild(slug, availability.flavour))
            is Availability.MissingOptionalDependency ->
                ToggleResult.Refused(ToggleError.MissingOptionalDependency(slug, availability.reason))
        }
    }
}
