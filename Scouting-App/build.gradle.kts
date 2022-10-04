import com.android.build.gradle.BaseExtension
import org.apache.commons.io.output.TeeOutputStream
import org.jetbrains.kotlin.gradle.dsl.KotlinJvmOptions
import org.jetbrains.kotlin.gradle.dsl.KotlinProjectExtension
import org.jetbrains.kotlin.gradle.internal.AndroidExtensionsExtension
import org.jetbrains.kotlin.gradle.internal.CacheImplementation

buildscript {
    repositories.deps()

    dependencies {
        classpath(Config.Plugins.android)
        classpath(Config.Plugins.kotlin)
        classpath(Config.Plugins.google)
        classpath(Config.Plugins.firebase)
        classpath(Config.Plugins.fabric)
    }
}

plugins {
    `lifecycle-base`
    id("com.supercilex.robotscouter.build")
    Config.Plugins.run { versionChecker }
}

buildScan {
    termsOfServiceUrl = "https://gradle.com/terms-of-service"
    termsOfServiceAgree = "yes"

    publishAlways()
    for (tag in buildTags) tag(tag)
}

allprojects {
    repositories.deps()

    configureGeneral()
    configureAndroid()
}

tasks.wrapper {
    distributionType = Wrapper.DistributionType.ALL
}

fun Project.configureGeneral() {
    afterEvaluate {
        convention.findByType<KotlinProjectExtension>()?.apply {
            sourceSets.configureEach {
                languageSettings.progressiveMode = true
                languageSettings.enableLanguageFeature("NewInference")
                languageSettings.useExperimentalAnnotation(
                        "kotlinx.coroutines.ExperimentalCoroutinesApi")
            }
        }
    }
}

fun Project.configureAndroid() {
    configurations.register("compileClasspath") // TODO see https://youtrack.jetbrains.com/issue/KT-27170

    val tree = (group as String).split(".")
    when {
        tree.contains("library") && name != "common" -> apply(plugin = "com.android.library")
        name == "android-base" -> apply(plugin = "com.android.application")
        tree.contains("feature") -> apply(plugin = "com.android.dynamic-feature")
        else -> return
    }
    apply(plugin = "kotlin-android")
    apply(plugin = "kotlin-android-extensions")

    // Resource packaging breaks otherwise for some reason
    tasks.matching { it.name.contains("Test") }.configureEach { enabled = false }

    if (!isReleaseBuild) {
        tasks.matching { it.name.contains("lintVitalRelease") }.configureEach { enabled = false }
    }

    configure<BaseExtension> {
        compileSdkVersion(Config.SdkVersions.compile)

        defaultConfig {
            minSdkVersion(Config.SdkVersions.min)
            targetSdkVersion(Config.SdkVersions.target)

            versionCode = 1
            vectorDrawables.useSupportLibrary = true
        }

        lintOptions {
            isCheckDependencies = true
            isCheckAllWarnings = true
            isWarningsAsErrors = true
            isAbortOnError = false

            baseline(file("$rootDir/app/android-base/lint-baseline.xml"))
            disable(
                    "InvalidPackage", // Needed because of Okio
                    "GradleDependency", "NewerVersionAvailable", // For build reproducibility
                    "WrongThreadInterprocedural", // Slow
                    "SyntheticAccessor" // Don't care, proguard should deal with it
            )

            val reportsDir = "$buildDir/reports"
            htmlOutput = file("$reportsDir/lint-results.html")
            xmlOutput = file("$reportsDir/lint-results.xml")
        }

        compileOptions {
            sourceCompatibility = JavaVersion.VERSION_1_8
            targetCompatibility = JavaVersion.VERSION_1_8
        }

        (this as ExtensionAware).configure<KotlinJvmOptions> {
            jvmTarget = "1.8"
        }
    }

    configure<AndroidExtensionsExtension> {
        isExperimental = true
        defaultCacheImplementation = CacheImplementation.SPARSE_ARRAY
    }
}
