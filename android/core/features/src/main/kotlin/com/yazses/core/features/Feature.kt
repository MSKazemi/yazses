package com.yazses.core.features

import java.util.Collections

/**
 * The shipped flavours of the Android app (ADR-MOB-009 §2).
 *
 * `FOSS` is the F-Droid / Accrescent / GitHub build built from source only; `FULL` is the
 * build that may use upstream binary artefacts for the optional engines.
 */
public enum class Flavour { FOSS, FULL }

/**
 * Recommendation tier, mirroring the desktop's `system/features.py` tiers.
 *
 * Declaration order is the display order used by [FeatureRegistry.groupedByTier].
 */
public enum class Tier { CORE, DEFAULT_ON, RECOMMENDED, OPTIONAL, EXPERIMENTAL }

/**
 * Whether a feature can actually run in this build.
 *
 * The two non-[Available] cases are different and must stay different
 * (`system/backends.py`): a missing optional dependency is fixed by supplying it, while a
 * feature that was never shipped in this flavour cannot be fixed by anything the user does.
 */
public sealed interface Availability {
    /** The code and its dependencies are present in this build. */
    public data object Available : Availability

    /** The code is shipped, but a dependency it needs is absent. [reason] says which and why. */
    public data class MissingOptionalDependency(val reason: String) : Availability

    /** This flavour was never built with the feature. Installing anything will not change it. */
    public data class NotInThisBuild(val flavour: Flavour) : Availability
}

/**
 * One user-facing capability and the config writes that toggle it.
 *
 * Config keys are `section.key` strings (the same names as the desktop `config.toml`), mapped
 * to their string value. [onWrites] is what enabling writes, [offWrites] what disabling writes.
 * Both must be non-empty and name the same keys, so a feature always declares what toggling
 * it touches.
 */
public class Feature(
    public val slug: String,
    public val displayName: String,
    public val enabled: Boolean,
    public val tier: Tier,
    public val availability: Availability,
    onWrites: Map<String, String>,
    offWrites: Map<String, String>,
) {
    /** An unmodifiable copy: mutating the map the caller passed in later cannot change this feature. */
    public val onWrites: Map<String, String> = frozenCopy(onWrites)

    /** An unmodifiable copy, as [onWrites]. */
    public val offWrites: Map<String, String> = frozenCopy(offWrites)

    init {
        require(slug.isNotBlank()) { "feature slug must not be blank" }
        require(onWrites.isNotEmpty() && offWrites.isNotEmpty()) {
            "feature '$slug' must declare at least one config key for on and off"
        }
        require(onWrites.keys == offWrites.keys) {
            "feature '$slug' on/off writes must name the same config keys"
        }
    }

    override fun toString(): String = "Feature(slug=$slug, enabled=$enabled, availability=$availability)"
}

/**
 * An unmodifiable copy of [source]. `Map.toMap()` is not enough: it returns a mutable map for two or
 * more entries and an immutable singleton for one, so the mutability would depend on the size.
 */
internal fun frozenCopy(source: Map<String, String>): Map<String, String> =
    Collections.unmodifiableMap(LinkedHashMap(source))
