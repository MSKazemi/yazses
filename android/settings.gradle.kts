// The module map from docs/mobile/architecture.md §3, one entry per row.
//
// Empty modules are the point of this file: the structure and its rules have to
// exist before ten people start in parallel, or they collide and re-decide the
// same questions in review.

pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

// Downloads the JDK the modules ask for instead of demanding the contributor
// already have that exact version installed. "Green from a clean clone" has to
// be true on whatever JDK someone happens to have.
plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "0.8.0"
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "yazses-android"

// ---- :core:* — pure Kotlin/JVM. No android.* on the classpath, by construction.
include(":core:config")
include(":core:audio")
include(":core:vad")
include(":core:stt")
include(":core:postprocess")
include(":core:commands")
include(":core:vocab")
include(":core:session")
include(":core:features")
// Runs contract/vectors/*.json against the cores. JVM test module.
include(":core:contract-test")

// ---- Android modules. Declared now so the dependency rules have something to
// enforce; each is a namespace and a placeholder until its own issue lands.
include(":platform:audio")
include(":model")
include(":native:whispercpp")
include(":native:sherpaonnx")
include(":feature:ime")
include(":feature:recognition")
include(":feature:meeting")
include(":feature:transcribe")
include(":feature:settings")
include(":feature:bubble")
include(":bench")
include(":app")
