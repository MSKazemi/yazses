package com.yazses.core.features

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Drift guard over the shipped registry data: it cannot quietly grow a broken entry. */
class BuiltInFeaturesTest {

    @Test
    fun `every built-in feature declares at least one config key for on and off`() {
        for (feature in BUILT_IN_FEATURES) {
            assertTrue(feature.onWrites.isNotEmpty(), "${feature.slug} has no on-writes")
            assertTrue(feature.offWrites.isNotEmpty(), "${feature.slug} has no off-writes")
        }
    }

    @Test
    fun `built-in slugs are unique`() {
        val slugs = BUILT_IN_FEATURES.map { it.slug }
        assertEquals(slugs.size, slugs.toSet().size, "duplicate slugs in $slugs")
    }

    @Test
    fun `every built-in feature ships off by default except the existing command grammar`() {
        val onByDefault = BUILT_IN_FEATURES.filter { it.enabled }.map { it.slug }
        assertEquals(listOf("commands"), onByDefault)
    }

    @Test
    fun `every built-in feature is available in this build`() {
        for (feature in BUILT_IN_FEATURES) {
            assertEquals(Availability.Available, feature.availability, feature.slug)
        }
    }

    @Test
    fun `the built-in registry resolves each shipped slug`() {
        val registry = builtInRegistry()
        for (feature in BUILT_IN_FEATURES) {
            assertTrue(registry.find(feature.slug) != null, feature.slug)
        }
        assertFalse(registry.find("silero-vad") != null, "no feature is listed before its code exists")
    }
}
