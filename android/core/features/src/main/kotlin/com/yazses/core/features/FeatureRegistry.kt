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

/**
 * The outcome of [FeatureRegistry.toggle]: the exact config writes, a typed refusal, or a request
 * for an explicit confirmation before an experimental feature is enabled.
 */
public sealed interface ToggleResult {
    /**
     * The config writes that set the feature to [on]. Pure data; nothing has been written.
     * [writes] is an unmodifiable copy, so the caller cannot change what the registry would write.
     */
    public class Writes(public val slug: String, public val on: Boolean, writes: Map<String, String>) : ToggleResult {
        public val writes: Map<String, String> = frozenCopy(writes)

        override fun equals(other: Any?): Boolean =
            other is Writes && other.slug == slug && other.on == on && other.writes == writes

        override fun hashCode(): Int = (slug.hashCode() * 31 + on.hashCode()) * 31 + writes.hashCode()

        override fun toString(): String = "Writes(slug=$slug, on=$on, writes=$writes)"
    }

    public data class Refused(val error: ToggleError) : ToggleResult

    /**
     * Enabling an [Tier.EXPERIMENTAL] feature needs an explicit confirmation. Nothing is written;
     * call [FeatureRegistry.toggle] again with `confirmed = true` once the user has agreed.
     */
    public data class NeedsConfirmation(val slug: String) : ToggleResult
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
     * The config writes that set [slug] to [on], or a typed refusal, or [ToggleResult.NeedsConfirmation].
     *
     * - Switching **off** a known feature is always allowed, whatever its availability: a user
     *   whose imported config has it on must be able to turn it off in a build that lacks it.
     * - Switching **on** is refused with [ToggleError.NotInThisBuild] or
     *   [ToggleError.MissingOptionalDependency] when the feature cannot run in this build, because
     *   writing its keys would claim a change that does nothing.
     * - Switching **on** an [Tier.EXPERIMENTAL] feature returns [ToggleResult.NeedsConfirmation]
     *   unless [confirmed] is true. Switching off never needs confirmation.
     */
    public fun toggle(slug: String, on: Boolean, confirmed: Boolean = false): ToggleResult {
        val feature = bySlug[slug] ?: return ToggleResult.Refused(ToggleError.UnknownFeature(slug))
        if (!on) return ToggleResult.Writes(slug, on = false, writes = feature.offWrites)
        when (val availability = feature.availability) {
            is Availability.Available -> Unit
            is Availability.NotInThisBuild ->
                return ToggleResult.Refused(ToggleError.NotInThisBuild(slug, availability.flavour))
            is Availability.MissingOptionalDependency ->
                return ToggleResult.Refused(ToggleError.MissingOptionalDependency(slug, availability.reason))
        }
        if (feature.tier == Tier.EXPERIMENTAL && !confirmed) return ToggleResult.NeedsConfirmation(slug)
        return ToggleResult.Writes(slug, on = true, writes = feature.onWrites)
    }
}
