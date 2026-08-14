package com.yazses.core.contracttest

import com.yazses.core.commands.classify
import com.yazses.core.postprocess.DisfluencyConfig
import com.yazses.core.postprocess.applyVoicePunctuation
import com.yazses.core.postprocess.filterTranscript
import com.yazses.core.vocab.mergeInitialPrompt
import com.yazses.core.postprocess.cleanText
import com.yazses.core.postprocess.continuationPrefix
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.TestFactory
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Runs every `contract/vectors` JSON file against the Kotlin cores.
 *
 * This is the whole definition of "done" for a ported unit (ADR-MOB-008). The
 * point is that a contributor never has to guess what the desktop does, and never
 * waits for a reviewer to say whether an edge case was intentional: the JSON was
 * generated from the Python and it is the contract.
 *
 * Each vector file becomes one dynamic test per case, so a failure names the case
 * id and the file rather than reporting "1 test failed".
 */
class ContractVectorTest {

    private val json = Json { ignoreUnknownKeys = true }

    private val contractDir: File by lazy {
        val configured = System.getProperty("yazses.contract.dir")
            ?: error(
                "yazses.contract.dir is not set. The Gradle test task passes it; " +
                    "running this class directly from an IDE needs it too."
            )
        File(configured).also {
            assertTrue(it.isDirectory, "contract directory not found: $it")
        }
    }

    private fun cases(file: String): List<JsonObject> {
        val f = File(contractDir, "vectors/$file")
        assertTrue(f.isFile, "missing vector file: $f")
        return json.parseToJsonElement(f.readText())
            .jsonObject["cases"]!!.jsonArray.map { it.jsonObject }
    }

    private fun JsonObject.str(key: String): String = this[key]!!.jsonPrimitive.content

    private fun JsonObject.optionBool(key: String): Boolean =
        this["options"]?.jsonObject?.get(key)?.jsonPrimitive?.content?.toBoolean() ?: false

    /**
     * One dynamic test per case. [apply] receives the case so a unit with options
     * can read them; the id and description go into the failure message, because
     * "expected X got Y" without the description loses the reason the case exists.
     */
    private fun vectorTests(file: String, apply: (JsonObject) -> String): List<DynamicTest> =
        cases(file).map { case ->
            DynamicTest.dynamicTest("$file :: ${case.str("id")}") {
                assertEquals(
                    case.str("expected"),
                    apply(case),
                    "${case.str("id")}: ${case.str("description")}",
                )
            }
        }

    @TestFactory
    fun `clean_text matches the contract`(): List<DynamicTest> =
        vectorTests("clean_text.json") { cleanText(it.str("input")) }

    @TestFactory
    fun `continuation spacing matches the contract`(): List<DynamicTest> =
        vectorTests("spacing.json") {
            continuationPrefix(it.str("input"), it.optionBool("had_recent_injection"))
        }

    @TestFactory
    fun `voice punctuation matches the contract`(): List<DynamicTest> =
        vectorTests("voice_punctuation.json") { applyVoicePunctuation(it.str("input")) }

    @TestFactory
    fun `disfluency filter matches the contract`(): List<DynamicTest> =
        vectorTests("disfluency.json") { case ->
            filterTranscript(case.str("input"), disfluencyConfig(case)).text
        }

    @TestFactory
    fun `the command grammar matches the contract`(): List<DynamicTest> =
        cases("grammar.json").map { case ->
            DynamicTest.dynamicTest("grammar.json :: ${case.str("id")}") {
                val expected = case["expected"]!!.jsonObject
                val actual = classify(case.str("input"))
                val why = "${case.str("id")}: ${case.str("description")}"
                assertEquals(expected["intent"]!!.jsonPrimitive.content, actual.intent.wire, why)
                assertEquals(expected["action"]!!.jsonPrimitive.content, actual.action, why)
                assertEquals(expected["raw_text"]!!.jsonPrimitive.content, actual.rawText, why)
                val expectedArgs = expected["args"]!!.jsonObject
                    .mapValues { it.value.jsonPrimitive.content }
                assertEquals(expectedArgs, actual.args, why)
            }
        }

    @TestFactory
    fun `the initial prompt matches the contract`(): List<DynamicTest> =
        cases("vocabulary.json").map { case ->
            DynamicTest.dynamicTest("vocabulary.json :: ${case.str("id")}") {
                val parts = case["input"]!!.jsonArray.map { element ->
                    element.jsonPrimitive.let { if (it.isString) it.content else null }
                }
                assertEquals(
                    case.str("expected"),
                    mergeInitialPrompt(*parts.toTypedArray()),
                    "${case.str("id")}: ${case.str("description")}",
                )
            }
        }

    /** Build the config a case declares, falling back to the desktop defaults. */
    private fun disfluencyConfig(case: JsonObject): DisfluencyConfig {
        val options = case["options"]?.jsonObject ?: return DisfluencyConfig()
        val base = DisfluencyConfig()
        return base.copy(
            enabled = options["enabled"]?.jsonPrimitive?.content?.toBoolean() ?: base.enabled,
            fillerWords = options["filler_words"]?.jsonArray?.map { it.jsonPrimitive.content }
                ?: base.fillerWords,
            collapseRepetitions = options["collapse_repetitions"]?.jsonPrimitive?.content?.toBoolean()
                ?: base.collapseRepetitions,
            collapseProlongations = options["collapse_prolongations"]?.jsonPrimitive?.content?.toBoolean()
                ?: base.collapseProlongations,
            prolongationMinRun = options["prolongation_min_run"]?.jsonPrimitive?.content?.toInt()
                ?: base.prolongationMinRun,
        )
    }

    /**
     * The harness must fail loudly when a vector file it claims to cover is
     * missing — otherwise deleting one would silently reduce coverage to zero and
     * still report green.
     */
    @TestFactory
    fun `every covered vector file exists and has cases`(): List<DynamicTest> =
        listOf(
                "clean_text.json", "spacing.json", "voice_punctuation.json",
                "disfluency.json", "grammar.json", "vocabulary.json",
            ).map { file ->
            DynamicTest.dynamicTest("$file is present and non-empty") {
                assertTrue(cases(file).isNotEmpty(), "$file has no cases")
            }
        }
}
