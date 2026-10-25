package com.yazses.core.features

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertSame

class FeatureRegistryTest {

    private fun feature(
        slug: String,
        tier: Tier = Tier.OPTIONAL,
        availability: Availability = Availability.Available,
        enabled: Boolean = false,
    ) = Feature(
        slug = slug,
        displayName = slug.uppercase(),
        enabled = enabled,
        tier = tier,
        availability = availability,
        onWrites = mapOf("section.$slug" to "true"),
        offWrites = mapOf("section.$slug" to "false"),
    )

    /** A deep copy of everything the registry exposes, so later mutation cannot hide in a shared reference. */
    private fun snapshot(registry: FeatureRegistry): Pair<List<List<Any?>>, Map<Tier, List<String>>> =
        registry.features.map { f ->
            listOf(f.slug, f.enabled, f.tier, f.availability, f.onWrites.toMap(), f.offWrites.toMap())
        } to registry.groupedByTier().mapValues { (_, v) -> v.map { it.slug } }

    // --- availability decides the outcome of switching on --------------------

    @Test
    fun `availability alone decides the outcome of switching on, one state at a time`() {
        val registry = FeatureRegistry(
            listOf(
                feature("ok"),
                feature("vad", availability = Availability.MissingOptionalDependency("needs onnxruntime")),
                feature("diar", availability = Availability.NotInThisBuild(Flavour.FULL)),
            ),
        )
        assertIs<ToggleResult.Writes>(registry.toggle("ok", on = true))
        assertEquals(
            ToggleResult.Refused(ToggleError.MissingOptionalDependency("vad", "needs onnxruntime")),
            registry.toggle("vad", on = true),
        )
        assertEquals(
            ToggleResult.Refused(ToggleError.NotInThisBuild("diar", Flavour.FULL)),
            registry.toggle("diar", on = true),
        )
    }

    @Test
    fun `a NotInThisBuild refusal carries the flavour the build was made as`() {
        val registry = FeatureRegistry(
            listOf(feature("diar", availability = Availability.NotInThisBuild(Flavour.FULL))),
        )
        val error = assertIs<ToggleResult.Refused>(registry.toggle("diar", on = true)).error
        val notInBuild = assertIs<ToggleError.NotInThisBuild>(error)
        assertEquals(Flavour.FULL, notInBuild.flavour)
    }

    @Test
    fun `a NotInThisBuild refusal is a different error from a missing dependency`() {
        val registry = FeatureRegistry(
            listOf(
                feature("diar", availability = Availability.NotInThisBuild(Flavour.FOSS)),
                feature("vad", availability = Availability.MissingOptionalDependency("needs onnxruntime")),
            ),
        )
        val notHere = assertIs<ToggleResult.Refused>(registry.toggle("diar", on = true)).error
        val missing = assertIs<ToggleResult.Refused>(registry.toggle("vad", on = true)).error
        assertNotEquals(notHere, missing)
    }

    // --- toggle: writes ------------------------------------------------------

    @Test
    fun `toggling an available feature returns exactly its on writes`() {
        val registry = FeatureRegistry(listOf(feature("a")))
        val result = assertIs<ToggleResult.Writes>(registry.toggle("a", on = true))
        assertEquals(mapOf("section.a" to "true"), result.writes)
        assertEquals(true, result.on)
    }

    @Test
    fun `toggling off returns exactly the off writes`() {
        val registry = FeatureRegistry(listOf(feature("a", enabled = true)))
        val result = assertIs<ToggleResult.Writes>(registry.toggle("a", on = false))
        assertEquals(mapOf("section.a" to "false"), result.writes)
    }

    @Test
    fun `a sequence of toggles leaves the registry snapshot identical`() {
        val registry = FeatureRegistry(
            listOf(
                feature("a"),
                feature("vad", availability = Availability.MissingOptionalDependency("needs onnxruntime")),
                feature("diar", availability = Availability.NotInThisBuild(Flavour.FOSS)),
                feature("exp", tier = Tier.EXPERIMENTAL),
            ),
        )
        val before = snapshot(registry)
        registry.toggle("a", on = true)
        registry.toggle("a", on = false)
        registry.toggle("vad", on = true)
        registry.toggle("diar", on = false)
        registry.toggle("exp", on = true)
        registry.toggle("exp", on = true, confirmed = true)
        registry.toggle("nope", on = true)
        assertEquals(before, snapshot(registry))
    }

    // --- switching OFF is always allowed for a known feature (item 2) --------

    @Test
    fun `switching OFF a NotInThisBuild feature is allowed and writes the off keys`() {
        val registry = FeatureRegistry(
            listOf(feature("diar", enabled = true, availability = Availability.NotInThisBuild(Flavour.FOSS))),
        )
        val result = assertIs<ToggleResult.Writes>(registry.toggle("diar", on = false))
        assertEquals(false, result.on)
        assertEquals(mapOf("section.diar" to "false"), result.writes)
    }

    @Test
    fun `switching OFF a feature with a missing optional dependency is allowed`() {
        val registry = FeatureRegistry(
            listOf(
                feature(
                    "vad",
                    enabled = true,
                    availability = Availability.MissingOptionalDependency("needs onnxruntime"),
                ),
            ),
        )
        val result = assertIs<ToggleResult.Writes>(registry.toggle("vad", on = false))
        assertEquals(mapOf("section.vad" to "false"), result.writes)
    }

    @Test
    fun `switching ON a NotInThisBuild feature is still refused`() {
        val registry = FeatureRegistry(
            listOf(feature("diar", availability = Availability.NotInThisBuild(Flavour.FOSS))),
        )
        val refused = assertIs<ToggleResult.Refused>(registry.toggle("diar", on = true))
        assertEquals(ToggleError.NotInThisBuild("diar", Flavour.FOSS), refused.error)
    }

    @Test
    fun `switching ON a feature with a missing optional dependency is still refused`() {
        val registry = FeatureRegistry(
            listOf(feature("vad", availability = Availability.MissingOptionalDependency("needs onnxruntime"))),
        )
        val refused = assertIs<ToggleResult.Refused>(registry.toggle("vad", on = true))
        assertEquals(ToggleError.MissingOptionalDependency("vad", "needs onnxruntime"), refused.error)
    }

    @Test
    fun `toggle of an unknown slug is a typed refusal, not an exception`() {
        val registry = FeatureRegistry(listOf(feature("a")))
        val refused = assertIs<ToggleResult.Refused>(registry.toggle("nope", on = true))
        assertEquals(ToggleError.UnknownFeature("nope"), refused.error)
        val refusedOff = assertIs<ToggleResult.Refused>(registry.toggle("nope", on = false))
        assertEquals(ToggleError.UnknownFeature("nope"), refusedOff.error)
    }

    // --- experimental features need explicit confirmation (item 3) -----------

    @Test
    fun `enabling an experimental feature without confirmation needs confirmation and writes nothing`() {
        val registry = FeatureRegistry(listOf(feature("exp", tier = Tier.EXPERIMENTAL)))
        assertEquals(ToggleResult.NeedsConfirmation("exp"), registry.toggle("exp", on = true))
        assertEquals(ToggleResult.NeedsConfirmation("exp"), registry.toggle("exp", on = true, confirmed = false))
    }

    @Test
    fun `enabling an experimental feature with confirmed = true returns its on writes`() {
        val registry = FeatureRegistry(listOf(feature("exp", tier = Tier.EXPERIMENTAL)))
        val result = assertIs<ToggleResult.Writes>(registry.toggle("exp", on = true, confirmed = true))
        assertEquals(true, result.on)
        assertEquals(mapOf("section.exp" to "true"), result.writes)
    }

    @Test
    fun `disabling an experimental feature never needs confirmation`() {
        val registry = FeatureRegistry(listOf(feature("exp", tier = Tier.EXPERIMENTAL, enabled = true)))
        val result = assertIs<ToggleResult.Writes>(registry.toggle("exp", on = false))
        assertEquals(mapOf("section.exp" to "false"), result.writes)
    }

    @Test
    fun `an unavailable experimental feature is refused rather than asked to confirm`() {
        val registry = FeatureRegistry(
            listOf(
                feature(
                    "exp",
                    tier = Tier.EXPERIMENTAL,
                    availability = Availability.NotInThisBuild(Flavour.FOSS),
                ),
            ),
        )
        val refused = assertIs<ToggleResult.Refused>(registry.toggle("exp", on = true))
        assertEquals(ToggleError.NotInThisBuild("exp", Flavour.FOSS), refused.error)
    }

    // --- defensive copies (item 4) --------------------------------------------

    @Test
    fun `mutating the maps passed to the constructor afterwards does not change toggle output`() {
        val on = mutableMapOf("section.a" to "true")
        val off = mutableMapOf("section.a" to "false")
        val registry = FeatureRegistry(
            listOf(
                Feature(
                    slug = "a",
                    displayName = "A",
                    enabled = false,
                    tier = Tier.OPTIONAL,
                    availability = Availability.Available,
                    onWrites = on,
                    offWrites = off,
                ),
            ),
        )
        on["section.a"] = "hacked"
        on["section.extra"] = "x"
        off["section.a"] = "hacked"

        assertEquals(mapOf("section.a" to "true"), assertIs<ToggleResult.Writes>(registry.toggle("a", on = true)).writes)
        assertEquals(mapOf("section.a" to "false"), assertIs<ToggleResult.Writes>(registry.toggle("a", on = false)).writes)
    }

    @Test
    fun `mutating the writes returned by toggle does not change what the registry writes next`() {
        val registry = FeatureRegistry(listOf(feature("a")))
        val first = assertIs<ToggleResult.Writes>(registry.toggle("a", on = true))
        @Suppress("UNCHECKED_CAST")
        val alias = first.writes as MutableMap<String, String>
        // The writes are an unmodifiable copy: a write through the alias must be rejected, not applied.
        assertFailsWith<UnsupportedOperationException> { alias["section.a"] = "hacked" }

        val second = assertIs<ToggleResult.Writes>(registry.toggle("a", on = true))
        assertEquals(mapOf("section.a" to "true"), second.writes)
    }

    // --- lookup --------------------------------------------------------------

    @Test
    fun `find returns the registered feature by slug and null otherwise`() {
        val a = feature("a")
        val registry = FeatureRegistry(listOf(a, feature("b")))
        assertSame(a, registry.find("a"))
        assertNull(registry.find("missing"))
    }

    // --- grouping ------------------------------------------------------------

    @Test
    fun `groupedByTier orders tiers by declaration and keeps registration order within a tier`() {
        val registry = FeatureRegistry(
            listOf(
                feature("opt-1", tier = Tier.OPTIONAL),
                feature("on-1", tier = Tier.DEFAULT_ON),
                feature("opt-2", tier = Tier.OPTIONAL),
                feature("exp-1", tier = Tier.EXPERIMENTAL),
            ),
        )
        val grouped = registry.groupedByTier()
        assertEquals(listOf(Tier.DEFAULT_ON, Tier.OPTIONAL, Tier.EXPERIMENTAL), grouped.keys.toList())
        assertEquals(listOf("opt-1", "opt-2"), grouped.getValue(Tier.OPTIONAL).map { it.slug })
    }

    @Test
    fun `groupedByTier omits tiers with no features`() {
        val registry = FeatureRegistry(listOf(feature("a", tier = Tier.RECOMMENDED)))
        assertEquals(listOf(Tier.RECOMMENDED), registry.groupedByTier().keys.toList())
    }

    // --- unique slugs --------------------------------------------------------

    @Test
    fun `duplicate slugs are rejected at construction`() {
        assertFailsWith<IllegalArgumentException> {
            FeatureRegistry(listOf(feature("a"), feature("a")))
        }
    }

    @Test
    fun `a feature must declare config keys for on and off`() {
        assertFailsWith<IllegalArgumentException> {
            Feature(
                slug = "bare",
                displayName = "Bare",
                enabled = false,
                tier = Tier.OPTIONAL,
                availability = Availability.Available,
                onWrites = emptyMap(),
                offWrites = emptyMap(),
            )
        }
    }

    @Test
    fun `on and off writes must name the same keys`() {
        assertFailsWith<IllegalArgumentException> {
            Feature(
                slug = "skewed",
                displayName = "Skewed",
                enabled = false,
                tier = Tier.OPTIONAL,
                availability = Availability.Available,
                onWrites = mapOf("s.a" to "true"),
                offWrites = mapOf("s.b" to "false"),
            )
        }
    }
}
