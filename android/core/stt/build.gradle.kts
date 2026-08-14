// SttEngine interface, DecodeOptions, Transcript, engine factory
//
// kotlin("jvm"), NOT com.android.library: the Android SDK is not on this
// classpath, so `import android.*` cannot compile here. That is what keeps the
// suite emulator-free and the KMP door open (ADR-MOB-002 §3).
plugins {
    alias(libs.plugins.kotlin.jvm)
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    testImplementation(libs.kotlin.test)
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.platform.launcher)
}

tasks.test {
    useJUnitPlatform()
}
