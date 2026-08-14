// sherpa-onnx engine, VAD, diarization (optional flavour)
plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

android {
    // `native` is a Java keyword, so it cannot be a package segment. The Gradle
    // path stays `:native:sherpaonnx` as the architecture specifies; only the
    // namespace differs.
    namespace = "com.yazses.jni.sherpaonnx"
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
