// JNI bridge to whisper.cpp
plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

android {
    // `native` is a Java keyword, so it cannot be a package segment. The Gradle
    // path stays `:native:whispercpp` as the architecture specifies; only the
    // namespace differs.
    namespace = "com.yazses.jni.whispercpp"
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
