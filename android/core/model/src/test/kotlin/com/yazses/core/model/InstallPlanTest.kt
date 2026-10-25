package com.yazses.core.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue

class InstallPlanTest {

    // Synthetic fixtures: SHA-256("hello") and SHA-256("abc"). Not real model digests.
    private val helloSha = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    private val abcSha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    private val hello = ModelEntry(
        id = "synthetic-hello", displayName = "Synthetic hello", engine = "whisper.cpp",
        sizeBytes = 5, sha256 = helloSha, licence = "MIT", url = "https://example.invalid/hello.bin",
    )
    private val other = ModelEntry(
        id = "synthetic-other", displayName = "Synthetic other", engine = "whisper.cpp",
        sizeBytes = 3, sha256 = abcSha, licence = "MIT", url = "https://example.invalid/other.bin",
    )
    private val catalogue = ModelCatalogue.parse(
        """{"schemaVersion": 1, "models": [
           {"id": "synthetic-hello", "displayName": "Synthetic hello", "engine": "whisper.cpp",
            "sizeBytes": 5, "sha256": "$helloSha", "licence": "MIT", "url": "https://example.invalid/hello.bin"},
           {"id": "synthetic-other", "displayName": "Synthetic other", "engine": "whisper.cpp",
            "sizeBytes": 3, "sha256": "$abcSha", "licence": "MIT", "url": "https://example.invalid/other.bin"}
           ]}""",
    )

    private val ack = UnverifiedAcknowledgement

    private fun downloadedHello(): InstallStep.Verifying =
        InstallPlan.downloaded(InstallPlan.begin(catalogue, hello))

    @Test
    fun `a download goes to a temporary name carrying the id and the first 12 digest characters`() {
        val step = InstallPlan.begin(catalogue, hello)
        assertEquals(InstallStep.Downloading(hello, "synthetic-hello.2cf24dba5fb0.part"), step)
        assertTrue(step.tempName != hello.id)
    }

    @Test
    fun `a catalogue that changes the digest under the same id gets a different temporary name`() {
        // Stale bytes from the old digest must never resume into the new model.
        val changed = ModelCatalogue.parse(
            """{"schemaVersion": 1, "models": [{"id": "synthetic-hello", "displayName": "Synthetic hello",
               "engine": "whisper.cpp", "sizeBytes": 3, "sha256": "$abcSha", "licence": "MIT",
               "url": "https://example.invalid/hello.bin"}]}""",
        )
        val before = InstallPlan.begin(catalogue, hello).tempName
        val after = InstallPlan.begin(changed, changed.byId("synthetic-hello")!!).tempName
        assertEquals("synthetic-hello.ba7816bf8f01.part", after)
        assertTrue(before != after, "both digests produced $before")
    }

    @Test
    fun `no temporary name equals any catalogue id, so a download cannot overwrite a model`() {
        for (entry in catalogue.models) {
            val temp = InstallPlan.begin(catalogue, entry).tempName
            assertTrue(catalogue.models.none { it.id == temp }, "$temp is a catalogue id")
            assertTrue(temp.endsWith(ModelCatalogue.TEMP_SUFFIX))
        }
    }

    @Test
    fun `a download of an entry the catalogue does not list cannot begin`() {
        assertFailsWith<IllegalArgumentException> {
            InstallPlan.begin(catalogue, hello.copy(sha256 = "a".repeat(64)))
        }
    }

    @Test
    fun `a download of a non-https entry cannot begin, by the catalogue's own url rule`() {
        assertFailsWith<IllegalArgumentException> {
            InstallPlan.begin(catalogue, hello.copy(url = "http://example.invalid/hello.bin"))
        }
    }

    @Test
    fun `downloading completes into verifying with the same entry and temporary name`() {
        val started = InstallPlan.begin(catalogue, hello)
        assertEquals(InstallStep.Verifying(hello, started.tempName), InstallPlan.downloaded(started))
    }

    @Test
    fun `a verified download finishes as installed`() {
        val finished = InstallPlan.verified(downloadedHello(), VerifyResult.Verified(hello))
        val installed = assertIs<InstallOutcome.Installed.Verified>(finished.outcome)
        assertEquals(hello, installed.entry)
    }

    @Test
    fun `a mismatched download is rejected as a security event, and is not installed`() {
        val finished = InstallPlan.verified(downloadedHello(), VerifyResult.Mismatch(helloSha, abcSha))
        assertIs<InstallOutcome.Rejected.Mismatch>(finished.outcome)
        val asAny: Any = finished.outcome
        assertTrue(asAny !is InstallOutcome.Installed, "a mismatch was installed")
    }

    @Test
    fun `the mismatch report carries the catalogue digest and the actual digest`() {
        val finished = InstallPlan.verified(downloadedHello(), VerifyResult.Mismatch(helloSha, abcSha))
        val rejected = assertIs<InstallOutcome.Rejected.Mismatch>(finished.outcome)
        assertEquals(helloSha, rejected.expected)
        assertEquals(abcSha, rejected.actual)
    }

    @Test
    fun `an invalid digest fails closed and is not installed`() {
        val finished = InstallPlan.verified(downloadedHello(), VerifyResult.InvalidDigest("nope"))
        assertIs<InstallOutcome.Rejected.InvalidDigest>(finished.outcome)
    }

    @Test
    fun `an unknown sideload without the explicit acknowledgement is not installed`() {
        val outcome = InstallPlan.outcomeOf(VerifyResult.UnknownSideload(abcSha), ack = null)
        assertIs<InstallOutcome.Rejected.AckMissing>(outcome)
    }

    @Test
    fun `an unknown sideload with the explicit acknowledgement is installed, flagged as unverified`() {
        val outcome = InstallPlan.outcomeOf(VerifyResult.UnknownSideload(abcSha), ack)
        val installed = assertIs<InstallOutcome.Installed.UnverifiedSideload>(outcome)
        assertEquals(abcSha, installed.sha256)
    }

    @Test
    fun `an unverified refusal stays refused even when an acknowledgement is passed`() {
        val outcome = InstallPlan.outcomeOf(VerifyResult.UnverifiedRefused(abcSha), ack)
        assertIs<InstallOutcome.Rejected.Unverified>(outcome)
    }

    @Test
    fun `a download that verifies as a different model is refused, not installed`() {
        val finished = InstallPlan.verified(downloadedHello(), VerifyResult.Verified(other))
        assertIs<InstallOutcome.Rejected.WrongModel>(finished.outcome)
    }

    @Test
    fun `a mismatch against a different model's digest is refused as the wrong model`() {
        val finished = InstallPlan.verified(downloadedHello(), VerifyResult.Mismatch(abcSha, helloSha))
        assertIs<InstallOutcome.Rejected.WrongModel>(finished.outcome)
    }

    @Test
    fun `a sideload result can never finish a download step`() {
        val asSideload = InstallPlan.verified(downloadedHello(), VerifyResult.UnknownSideload(abcSha), ack)
        assertIs<InstallOutcome.Rejected.WrongModel>(asSideload.outcome)
        val asRefusal = InstallPlan.verified(downloadedHello(), VerifyResult.UnverifiedRefused(abcSha), ack)
        assertIs<InstallOutcome.Rejected.WrongModel>(asRefusal.outcome)
    }

    @Test
    fun `no verify result can reach installed on a mismatch, a bad digest or an unacknowledged sideload`() {
        val results = listOf<VerifyResult>(
            VerifyResult.Mismatch(helloSha, abcSha),
            VerifyResult.InvalidDigest("nope"),
            VerifyResult.UnknownSideload(abcSha),
            VerifyResult.UnverifiedRefused(abcSha),
            VerifyResult.Verified(hello),
        )
        for (result in results) {
            for (passed in listOf<UnverifiedAcknowledgement?>(null, ack)) {
                val outcome = InstallPlan.outcomeOf(result, passed)
                val mustNotInstall = result !is VerifyResult.Verified &&
                    !(result is VerifyResult.UnknownSideload && passed != null)
                if (mustNotInstall) {
                    assertTrue(outcome !is InstallOutcome.Installed, "$result (ack=$passed) installed")
                }
            }
        }
    }

    @Test
    fun `every verify result has an explicit outcome, with no fall-through`() {
        // Exhaustive `when` over the sealed type: a new VerifyResult variant fails to compile here.
        for (result in listOf<VerifyResult>(
            VerifyResult.Verified(hello),
            VerifyResult.Mismatch(helloSha, abcSha),
            VerifyResult.UnknownSideload(abcSha),
            VerifyResult.UnverifiedRefused(abcSha),
            VerifyResult.InvalidDigest("nope"),
        )) {
            val outcome = InstallPlan.outcomeOf(result, ack)
            val ok = when (result) {
                is VerifyResult.Verified -> outcome is InstallOutcome.Installed.Verified
                is VerifyResult.Mismatch -> outcome is InstallOutcome.Rejected.Mismatch
                is VerifyResult.UnknownSideload -> outcome is InstallOutcome.Installed.UnverifiedSideload
                is VerifyResult.UnverifiedRefused -> outcome is InstallOutcome.Rejected.Unverified
                is VerifyResult.InvalidDigest -> outcome is InstallOutcome.Rejected.InvalidDigest
            }
            assertTrue(ok, "$result mapped to $outcome")
        }
    }
}
