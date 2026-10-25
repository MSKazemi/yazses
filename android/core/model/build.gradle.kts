// Pure model catalogue parsing/validation and SHA-256 verification (ADR-MOB-006).
//
// kotlin("jvm"), NOT com.android.library: this is the SDK-free half of :model.
// :model is the only module with INTERNET and cannot even configure without the
// Android SDK, so the logic that decides whether a model file is trusted lives
// here instead, where it is unit-testable on any JDK. This module has no network
// code and no project dependencies.
plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(libs.kotlinx.serialization.json)
    testImplementation(libs.kotlin.test)
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.platform.launcher)
}

tasks.test {
    useJUnitPlatform()
    // The shipped catalogue is read by path, so Gradle cannot see it as an input. Without this a
    // contributor who edits models.json and runs the tests gets a stale "UP-TO-DATE" pass.
    inputs.file("../../app/src/main/assets/models.json").withPropertyName("shippedModelCatalogue")
}
