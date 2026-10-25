package com.yazses.core.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class DownloadPolicyTest {

    // Synthetic fixture: the digest is SHA-256("hello"), not a real model's.
    private val helloSha = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    private val hello = ModelEntry(
        id = "synthetic-hello", displayName = "Synthetic hello", engine = "whisper.cpp",
        sizeBytes = 5, sha256 = helloSha, licence = "MIT", url = "https://example.invalid/hello.bin",
    )
    private val catalogue = ModelCatalogue.parse(
        """{"schemaVersion": 1, "models": [{"id": "synthetic-hello", "displayName": "Synthetic hello",
           "engine": "whisper.cpp", "sizeBytes": 5, "sha256": "$helloSha", "licence": "MIT",
           "url": "https://example.invalid/hello.bin"}]}""",
    )

    // Test helper only: production callers must pass every argument, see DownloadPolicy.decide.
    private fun decide(
        settings: DownloadSettings = DownloadSettings(),
        network: NetworkKind = NetworkKind.UNMETERED,
        batteryLow: Boolean = false,
        entry: ModelEntry = hello,
        userConfirmed: Boolean = true,
        previousMismatchFor: Set<String> = emptySet(),
    ) = DownloadPolicy.decide(
        catalogue, entry, settings, network, batteryLow, userConfirmed, previousMismatchFor,
    )

    @Test
    fun `wifi-only is the default, as ADR-MOB-006 section 3 requires`() {
        assertTrue(DownloadSettings().wifiOnly)
    }

    @Test
    fun `an unmetered network starts a download under the default settings`() {
        assertEquals(DownloadDecision.Start, decide())
    }

    @Test
    fun `a metered network waits under the default wifi-only setting`() {
        assertEquals(DownloadDecision.Wait(WaitReason.WAITING_FOR_WIFI), decide(network = NetworkKind.METERED))
    }

    @Test
    fun `a metered network starts once the user turns wifi-only off and has confirmed`() {
        assertEquals(
            DownloadDecision.Start,
            decide(settings = DownloadSettings(wifiOnly = false), network = NetworkKind.METERED),
        )
    }

    @Test
    fun `no network waits, whatever the settings say`() {
        assertEquals(DownloadDecision.Wait(WaitReason.NO_NETWORK), decide(network = NetworkKind.NONE))
        assertEquals(
            DownloadDecision.Wait(WaitReason.NO_NETWORK),
            decide(settings = DownloadSettings(wifiOnly = false), network = NetworkKind.NONE),
        )
    }

    @Test
    fun `a low battery waits by default`() {
        assertEquals(DownloadDecision.Wait(WaitReason.BATTERY_LOW), decide(batteryLow = true))
    }

    @Test
    fun `a low battery starts when the user allows it`() {
        assertEquals(
            DownloadDecision.Start,
            decide(settings = DownloadSettings(allowOnLowBattery = true), batteryLow = true),
        )
    }

    @Test
    fun `an entry that is not the catalogue's own is refused, even on wifi`() {
        val forged = hello.copy(sha256 = "a".repeat(64))
        assertEquals(DownloadDecision.Refuse(RefuseReason.NotInCatalogue), decide(entry = forged))
    }

    @Test
    fun `a non-https url is refused by the catalogue's own url rule, before anything else`() {
        val plainHttp = hello.copy(url = "http://example.invalid/hello.bin")
        val decision = decide(network = NetworkKind.NONE, entry = plainHttp)
        assertIs<DownloadDecision.Refuse>(decision)
        val reason = assertIs<RefuseReason.UnsafeSource>(decision.reason)
        assertTrue("https://" in reason.problem, "got ${reason.problem}")
    }

    @Test
    fun `a loopback url is refused even when it is not in the catalogue`() {
        val loopback = hello.copy(url = "https://127.0.0.1/hello.bin")
        assertIs<DownloadDecision.Refuse>(decide(entry = loopback))
    }

    // ADR-MOB-006 section 2: nothing is downloaded before an explicit tap.

    @Test
    fun `nothing starts before the user confirms, on an unmetered network`() {
        assertEquals(
            DownloadDecision.Wait(WaitReason.NEEDS_CONFIRMATION),
            decide(userConfirmed = false),
        )
    }

    @Test
    fun `mobile data does not start on the strength of a wifi-only switch alone`() {
        assertEquals(
            DownloadDecision.Wait(WaitReason.NEEDS_CONFIRMATION),
            decide(settings = DownloadSettings(wifiOnly = false), network = NetworkKind.METERED, userConfirmed = false),
        )
    }

    @Test
    fun `confirmation is checked before the network, so no-network is not reported first`() {
        assertEquals(
            DownloadDecision.Wait(WaitReason.NEEDS_CONFIRMATION),
            decide(network = NetworkKind.NONE, userConfirmed = false),
        )
    }

    @Test
    fun `confirmation is checked before the battery`() {
        assertEquals(
            DownloadDecision.Wait(WaitReason.NEEDS_CONFIRMATION),
            decide(batteryLow = true, userConfirmed = false),
        )
    }

    @Test
    fun `a refused source is refused before confirmation is asked for`() {
        val plainHttp = hello.copy(url = "http://example.invalid/hello.bin")
        assertIs<DownloadDecision.Refuse>(decide(entry = plainHttp, userConfirmed = false))
        assertEquals(
            DownloadDecision.Refuse(RefuseReason.NotInCatalogue),
            decide(entry = hello.copy(sha256 = "a".repeat(64)), userConfirmed = false),
        )
    }

    @Test
    fun `a confirmed request on no network waits for the network, not for confirmation`() {
        assertEquals(DownloadDecision.Wait(WaitReason.NO_NETWORK), decide(network = NetworkKind.NONE, userConfirmed = true))
    }

    // ADR-MOB-006 section 3 and the mismatch rule: a mismatch is never retried.

    @Test
    fun `an id whose last attempt was a mismatch is refused, even confirmed and on wifi`() {
        assertEquals(
            DownloadDecision.Refuse(RefuseReason.PREVIOUS_MISMATCH),
            decide(previousMismatchFor = setOf("synthetic-hello")),
        )
    }

    @Test
    fun `a mismatch for another id does not refuse this one`() {
        assertEquals(DownloadDecision.Start, decide(previousMismatchFor = setOf("some-other-model")))
    }

    @Test
    fun `a previous mismatch outranks the confirmation wait`() {
        assertEquals(
            DownloadDecision.Refuse(RefuseReason.PREVIOUS_MISMATCH),
            decide(previousMismatchFor = setOf("synthetic-hello"), userConfirmed = false),
        )
    }

    @Test
    fun `an empty set of previous mismatches refuses nothing`() {
        assertEquals(DownloadDecision.Start, decide(previousMismatchFor = emptySet()))
    }
}
