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
        // The id becomes a storage file name (ADR-MOB-006), so it is restricted to a safe
        // lower-case slug: no separators, no leading dot, no upper case, bounded length.
        private val ID_PATTERN = Regex("^[a-z0-9][a-z0-9._-]*$")
        private const val MAX_ID_LENGTH = 64

        /**
         * Suffix of every temporary download file ([InstallPlan.begin]). An id may not end with it,
         * so no final model file can share a name with a file a download is still writing.
         */
        public const val TEMP_SUFFIX: String = ".part"
        private val IPV4_LITERAL = Regex("^\\d{1,3}(\\.\\d{1,3}){3}$")
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
         * - `id` matches `^[a-z0-9][a-z0-9._-]*$`, is at most 64 characters and has no `..`
         * - `id` does not end with [TEMP_SUFFIX]: `tiny` downloads to `tiny.<sha12>.part`, and a
         *   final model named `tiny.part` (or any `.part` name) must never collide with it
         * - `sha256` is 64 lower-case hex characters
         * - `sizeBytes` is positive
         * - `url` is `https://` with a DNS host, no userinfo, and not localhost, a loopback
         *   name or an IP literal (see [urlProblem])
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
                if (!ID_PATTERN.matches(e.id) || e.id.length > MAX_ID_LENGTH || ".." in e.id) {
                    problems += "model id '${e.id}' must match ^[a-z0-9][a-z0-9._-]*\$, be at most " +
                        "$MAX_ID_LENGTH characters, and not contain '..'"
                }
                if (e.id.endsWith(TEMP_SUFFIX)) {
                    problems += "model id '${e.id}' must not end with '$TEMP_SUFFIX': that suffix is reserved for temporary downloads"
                }
                if (e.displayName.isBlank()) problems += "$where: displayName is blank"
                if (e.engine.isBlank()) problems += "$where: engine is blank"
                if (e.licence.isBlank()) problems += "$where: licence is blank"
                if (!SHA256_HEX.matches(e.sha256)) {
                    problems += "$where: sha256 must be 64 lower-case hex characters"
                }
                if (e.sizeBytes <= 0L) problems += "$where: sizeBytes must be positive, was ${e.sizeBytes}"
                urlProblem(e.url)?.let { problems += "$where: url $it" }
            }
            return problems
        }

        /**
         * Why [url] is not acceptable as a model source, or null when it is. Only a name a
         * real upstream can be reached under passes: no credentials in the URL, no
         * localhost or loopback name, and no bare IP literal (ADR-MOB-006: the catalogue
         * names a real host, and a host that is this machine or a raw address is a mistake).
         */
        internal fun urlProblem(url: String): String? {
            val uri = try {
                URI(url)
            } catch (_: URISyntaxException) {
                return "must be an https:// URL, was '$url'"
            }
            if (!uri.scheme.equals("https", ignoreCase = true)) return "must be an https:// URL, was '$url'"
            if (uri.rawAuthority?.contains('@') == true) {
                return "must not contain credentials (user info), was '$url'"
            }
            val host = uri.host?.trimEnd('.')?.lowercase()
            if (host.isNullOrEmpty()) return "must be an https:// URL with a host, was '$url'"
            if (host == "localhost" || host.endsWith(".localhost")) {
                return "must name a real upstream host, not localhost, was '$url'"
            }
            if (host.startsWith("[") || IPV4_LITERAL.matches(host)) {
                return "must name a DNS host, not an IP literal (loopback included), was '$url'"
            }
            return null
        }
    }
}

@Serializable
private data class CatalogueFile(val schemaVersion: Int, val models: List<ModelEntry>)
