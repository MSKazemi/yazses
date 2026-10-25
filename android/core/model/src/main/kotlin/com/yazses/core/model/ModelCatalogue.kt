package com.yazses.core.model

import java.net.URI
import java.net.URISyntaxException
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/**
 * One downloadable speech model, as listed in the in-repo catalogue
 * (`android/app/src/main/assets/models.json`, ADR-MOB-006 §7).
 */
@Serializable
public data class ModelEntry(
    val id: String,
    val displayName: String,
    val engine: String,
    /** Size of the model file in bytes. Must be positive. */
    val sizeBytes: Long,
    /** Lower-case hex SHA-256 of the model file, 64 characters. */
    val sha256: String,
    val licence: String,
    /** Upstream source. Must be an `https://` URL. */
    @SerialName("url") val url: String,
)

/** Thrown by [ModelCatalogue.parse] with every problem found, not just the first. */
public class CatalogueException(public val problems: List<String>) :
    IllegalArgumentException(problems.joinToString("; "))

/**
 * The validated model catalogue.
 *
 * File shape, decoded by [parse]:
 * ```
 * {
 *   "schemaVersion": 1,
 *   "models": [
 *     { "id": "...", "displayName": "...", "engine": "...", "sizeBytes": 1234,
 *       "sha256": "<64 lower-case hex>", "licence": "...", "url": "https://..." }
 *   ]
 * }
 * ```
 * Unknown top-level keys are ignored, so a file may carry a `_schema` note. Every
 * other key is required. An empty `models` array is valid.
 */
public class ModelCatalogue private constructor(public val models: List<ModelEntry>) {

    private val index: Map<String, ModelEntry> = models.associateBy { it.id }

    /** The entry with this [id], or null when the catalogue does not list it. */
    public fun byId(id: String): ModelEntry? = index[id]

    public companion object {
        /** The only file layout this parser understands. */
        public const val SCHEMA_VERSION: Int = 1

        private val SHA256_HEX = Regex("^[0-9a-f]{64}$")
        private val json = Json { ignoreUnknownKeys = true }

        /**
         * Decodes and validates a catalogue file.
         *
         * @throws CatalogueException when the text is not a valid catalogue. The
         *   exception lists every problem, so a bad PR shows all of them at once.
         */
        public fun parse(text: String): ModelCatalogue {
            val file = try {
                json.decodeFromString(CatalogueFile.serializer(), text)
            } catch (e: SerializationException) {
                throw CatalogueException(listOf("malformed catalogue: ${e.message}"))
            }
            val problems = mutableListOf<String>()
            if (file.schemaVersion != SCHEMA_VERSION) {
                problems += "schemaVersion ${file.schemaVersion} is not supported (expected $SCHEMA_VERSION)"
            }
            problems += validate(file.models)
            if (problems.isNotEmpty()) throw CatalogueException(problems)
            return ModelCatalogue(file.models)
        }

        /**
         * Every rule a catalogue must satisfy, as human-readable problems. Empty means valid.
         *
         * - ids are unique, and so are digests (two entries with one digest make
         *   a sideloaded file's identity ambiguous)
         * - `sha256` is 64 lower-case hex characters
         * - `sizeBytes` is positive
         * - `url` is `https://` with a host
         * - `displayName`, `engine` and `licence` are not blank
         */
        public fun validate(entries: List<ModelEntry>): List<String> {
            val problems = mutableListOf<String>()
            entries.groupBy { it.id }.filterValues { it.size > 1 }.keys.forEach {
                problems += "duplicate id '$it'"
            }
            entries.groupBy { it.sha256 }.filterValues { it.size > 1 }.values.forEach { same ->
                problems += "models ${same.joinToString { "'${it.id}'" }} share one sha256; identity would be ambiguous"
            }
            entries.forEach { e ->
                val where = "model '${e.id}'"
                if (e.id.isBlank()) problems += "a model has a blank id"
                if (e.displayName.isBlank()) problems += "$where: displayName is blank"
                if (e.engine.isBlank()) problems += "$where: engine is blank"
                if (e.licence.isBlank()) problems += "$where: licence is blank"
                if (!SHA256_HEX.matches(e.sha256)) {
                    problems += "$where: sha256 must be 64 lower-case hex characters"
                }
                if (e.sizeBytes <= 0L) problems += "$where: sizeBytes must be positive, was ${e.sizeBytes}"
                if (!isHttps(e.url)) problems += "$where: url must be an https:// URL, was '${e.url}'"
            }
            return problems
        }

        internal fun isHttps(url: String): Boolean = try {
            val uri = URI(url)
            uri.scheme.equals("https", ignoreCase = true) && !uri.host.isNullOrBlank()
        } catch (_: URISyntaxException) {
            false
        }
    }
}

@Serializable
private data class CatalogueFile(val schemaVersion: Int, val models: List<ModelEntry>)
