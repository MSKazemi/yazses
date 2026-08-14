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

tasks.test {
    useJUnitPlatform()
    // The vectors live in the repository root, not in android/. Passed as a
    // property rather than resolved from the working directory, which differs
    // between `./gradlew test` and an IDE run.
    systemProperty("yazses.contract.dir", rootProject.layout.projectDirectory.dir("../contract").asFile.absolutePath)
}
