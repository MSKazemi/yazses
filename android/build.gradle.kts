// Root build: shared configuration, and the architecture rules the build enforces
// so that review does not have to.

plugins {
    alias(libs.plugins.kotlin.jvm) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
}

// ---------------------------------------------------------------------------
// Layering, enforced by the build (ADR-MOB-002 §3, ADR-MOB-007 B).
//
// `:core:*` being kotlin("jvm") already makes `import android.content.Context`
// impossible — the Android SDK is simply not on the classpath, so it fails at
// compile time with no extra machinery. That is the reason for the module type,
// not a side effect of it.
//
// The direction rule needs a check, because Gradle is perfectly happy to let a
// core module depend on a feature module. A comment in a review guide would be
// enforced by whoever happens to read it; this is enforced by `./gradlew check`.
// ---------------------------------------------------------------------------

/** Project paths a module in [fromPrefix] may never depend on. */
val forbiddenEdges = mapOf(
    ":core" to listOf(":feature", ":platform", ":app", ":bench", ":native", ":model"),
    ":platform" to listOf(":feature", ":app", ":bench"),
)

val checkLayering by tasks.registering {
    group = "verification"
    description = "Fails when a module depends on a layer it must not know about."

    // Configuration-cache friendly: resolve the graph at configuration time into
    // plain data, so the task action touches no Project.
    val violations = mutableListOf<String>()
    subprojects.forEach { sub ->
        val prefix = forbiddenEdges.keys.firstOrNull { sub.path.startsWith("$it:") } ?: return@forEach
        val banned = forbiddenEdges.getValue(prefix)
        sub.configurations.forEach { conf ->
            conf.dependencies.withType(ProjectDependency::class.java).forEach { dep ->
                @Suppress("DEPRECATION")
                val target = dep.dependencyProject.path
                if (banned.any { target.startsWith("$it:") || target == it }) {
                    violations += "${sub.path} (${conf.name}) -> $target"
                }
            }
        }
    }

    doLast {
        if (violations.isNotEmpty()) {
            throw GradleException(
                buildString {
                    appendLine("Forbidden module dependencies:")
                    violations.forEach { appendLine("  $it") }
                    appendLine()
                    appendLine("`:core:*` is the portable half — it may not know about Android,")
                    appendLine("about features, or about the app. See docs/mobile/architecture.md §3")
                    appendLine("and ADR-MOB-002 §3. If you need something from a feature, the")
                    appendLine("dependency is pointing the wrong way: define an interface in core")
                    appendLine("and inject the implementation.")
                }
            )
        }
    }
}

// ADR-MOB-007 privacy gates: merged-manifest golden diff, dependency allow-list,
// network containment, and no content in logs.
apply(from = "gradle/privacy.gradle.kts")

// `check` is what CI runs, so neither rule can be skipped by running `test`.
subprojects {
    tasks.matching { it.name == "check" }.configureEach {
        dependsOn(checkLayering)
        dependsOn(rootProject.tasks.named("checkPrivacy"))
    }
}
