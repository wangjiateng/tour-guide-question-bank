plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.daoyou.tiku"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.daoyou.tiku"
        minSdk = 24
        targetSdk = 36
        versionCode = 4
        versionName = "1.3"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // 用 debug 签名出 release 包：无调试开销、可直接安装分发
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

// 仅保留 release 变体：禁用 debug（仓库约定只打 release 包，见 AGENTS.md §2/§6）。
// 效果：assembleDebug / installDebug / testDebugUnitTest 等 debug 任务不再生成，
// 想打 debug 包只能临时注释掉本块（AGP 在配置阶段就会忽略 debug 变体）。
androidComponents {
    beforeVariants(selector().all()) { variant ->
        if (variant.buildType == "debug") variant.enable = false
    }
}

// 题库 JSON 是唯一事实源（仓库根 data/，AI 直接维护）：构建时复制进 assets，不产生副本漂移
val copyQuizData = tasks.register<Copy>("copyQuizData") {
    from(file("${rootProject.projectDir}/../data"))
    into("src/main/assets/data")
}
tasks.named("preBuild") { dependsOn(copyQuizData) }

dependencies {
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    val composeBom = platform("androidx.compose:compose-bom:2025.09.00")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
}
