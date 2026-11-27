// AudioRecord capture, device selection, audio-focus handling
plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.yazses.platform.audio"
    compileSdk = libs.versions.compileSdk.get().toInt()

    defaultConfig {
        minSdk = libs.versions.minSdk.get().toInt()
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    // The capture loop and its types are pure JVM and tested there. `api` because
    // CaptureStopReason is part of MicrophoneCapture's public signature.
    api(project(":core:audio"))
}
