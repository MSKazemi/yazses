// Runs contract/vectors/*.json against the Kotlin cores.
//
// This module is why a contributor porting a unit never has to guess what the
// Python does, and never waits for a reviewer to say whether an edge case was
// intentional: the JSON is the definition of correct (ADR-MOB-008).
plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(project(":core:postprocess"))
    implementation(project(":core:commands"))
    implementation(project(":core:vocab"))
    implementation(project(":core:vad"))
    testImplementation(libs.kotlin.test)
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.kotlinx.serialization.json)
    testRuntimeOnly(libs.junit.platform.launcher)
}

val contractDir = rootProject.layout.projectDirectory.dir("../contract")

tasks.test {
    useJUnitPlatform()
    // The vectors live in the repository root, not in android/. Passed as a
    // property rather than resolved from the working directory, which differs
    // between `./gradlew test` and an IDE run.
    systemProperty("yazses.contract.dir", contractDir.asFile.absolutePath)

    // ...and declared as an input, which is what makes the property honest.
    //
    // Gradle keys up-to-date checks and the build cache on a task's declared
    // inputs. A system property naming a directory is not one of them, so with
    // the corpus undeclared this task believed nothing had changed when the
    // contract itself changed -- and `gradle/actions/setup-gradle` restores the
    // build cache between runs, so `./gradlew test` reported the *previous*
    // run's pass. Reproduced: a 232-case corpus returned FROM-CACHE with
    // `tests="228"`, and only `--rerun-tasks` ran the new cases.
    //
    // That defeated exactly the guard the workflow was written for: android-test
    // triggers on `contract/**` because amending the contract can break the port,
    // and a contract-only change is the one case where every other input is
    // identical -- so it was the case guaranteed to hit the cache.
    inputs.dir(contractDir)
        .withPropertyName("contractVectors")
        .withPathSensitivity(PathSensitivity.RELATIVE)
}
