package com.yazses.core.features

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
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

    // --- availability states -------------------------------------------------

    @Test
    fun `an available feature keeps Available and is reported as such`() {
        val registry = FeatureRegistry(listOf(feature("a")))
        assertEquals(Availability.Available, registry.find("a")?.availability)
    }

    @Test
    fun `a missing optional dependency carries its reason`() {
        val missing = Availability.MissingOptionalDependency("needs onnxruntime")
        val registry = FeatureRegistry(listOf(feature("a", availability = missing)))
        assertEquals("needs onnxruntime", (registry.find("a")?.availability as Availability.MissingOptionalDependency).reason)
    }

    @Test
    fun `NotInThisBuild names the flavour and is distinct from a missing dependency`() {
        val notHere = Availability.NotInThisBuild(Flavour.FOSS)
        assertEquals(Flavour.FOSS, (notHere as Availability.NotInThisBuild).flavour)
        assertEquals(false, notHere == Availability.MissingOptionalDependency("x"))
    }

    // --- toggle --------------------------------------------------------------

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
    fun `toggle does not mutate the registry`() {
        val registry = FeatureRegistry(listOf(feature("a")))
        registry.toggle("a", on = true)
        assertEquals(false, registry.find("a")?.enabled)
    }

    @Test
    fun `toggle refuses a NotInThisBuild feature in both directions`() {
        val registry = FeatureRegistry(
            listOf(feature("diar", availability = Availability.NotInThisBuild(Flavour.FOSS))),
        )
        for (on in listOf(true, false)) {
            val refused = assertIs<ToggleResult.Refused>(registry.toggle("diar", on))
            assertEquals(ToggleError.NotInThisBuild("diar", Flavour.FOSS), refused.error)
        }
    }

    @Test
    fun `toggle refuses a feature with a missing optional dependency`() {
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
