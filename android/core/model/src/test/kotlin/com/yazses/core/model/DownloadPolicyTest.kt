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

    private fun decide(
        settings: DownloadSettings = DownloadSettings(),
        network: NetworkKind = NetworkKind.UNMETERED,
        batteryLow: Boolean = false,
        entry: ModelEntry = hello,
    ) = DownloadPolicy.decide(catalogue, entry, settings, network, batteryLow)

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
    fun `a metered network starts once the user turns wifi-only off`() {
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
}
