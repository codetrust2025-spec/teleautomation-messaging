# TeleAutomation Android

> Split status: **INCOMPLETE AND SAFE TO EXCLUDE FROM THIS SPLIT**. This historical,
> work-in-progress client is preserved in the Marketing repository, but it is not part
> of the production-critical web/server runtime and is intentionally not a web/server
> CI or staging deployment gate. See `docs/migration/android-scope-decision.md`.

Native Android client (Kotlin + Jetpack Compose, MVVM + repositories, Hilt) targeting
functional parity with the TeleAutomation web app. It is a pure client of the existing
FastAPI Backend (HTTP REST + `/ws` WebSocket); it introduces no duplicate or mock
production endpoints (R23).

## Module layout

```
android/
├── settings.gradle.kts          # single :app module, version-catalog-managed
├── build.gradle.kts             # root: plugin aliases (apply false)
├── gradle.properties            # AndroidX, parallel/caching, non-transitive R
├── gradle/
│   ├── libs.versions.toml        # version catalog (single source of versions)
│   └── wrapper/
│       └── gradle-wrapper.properties   # Gradle 8.11.1
├── gradlew / gradlew.bat        # wrapper launch scripts
└── app/
    ├── build.gradle.kts          # app module: Compose, Hilt(KSP), Retrofit/OkHttp, ...
    ├── proguard-rules.pro
    └── src/
        ├── main/
        │   ├── AndroidManifest.xml
        │   ├── java/com/teleautomation/android/
        │   │   ├── MainActivity.kt          # single activity
        │   │   ├── ui/                       # Compose screens, theme, shell
        │   │   ├── presentation/             # ViewModels (StateFlow/SharedFlow)
        │   │   ├── data/
        │   │   │   ├── api/                   # Retrofit services + DTOs
        │   │   │   ├── repo/                  # repositories -> NetworkResult<T>
        │   │   │   └── local/                 # EncryptedSharedPreferences + DataStore
        │   │   └── core/                      # pure logic: validators/formatters/backoff
        │   └── res/                          # theme, strings, launcher icon
        ├── test/                             # JVM unit + property tests (kotest)
        └── androidTest/                      # Compose UI + Hilt instrumented tests
```

## Tech stack (versions pinned in `gradle/libs.versions.toml`)

| Concern        | Library / tool                                   | Version        |
| -------------- | ------------------------------------------------ | -------------- |
| Build          | Android Gradle Plugin                            | 8.7.3          |
| Language       | Kotlin (+ Compose compiler plugin)               | 2.0.21         |
| Annotation     | KSP                                              | 2.0.21-1.0.28  |
| UI             | Jetpack Compose (BOM)                            | 2024.12.01     |
| DI             | Hilt                                             | 2.52           |
| HTTP           | Retrofit / OkHttp                                | 2.11.0 / 4.12.0|
| JSON           | kotlinx-serialization (lenient)                  | 1.7.3          |
| Images         | Coil                                             | 2.7.0          |
| Navigation     | Navigation-Compose                               | 2.8.5          |
| Storage        | DataStore + androidx.security:security-crypto    | 1.1.1 / 1.1.0-alpha06 |
| Async          | Coroutines / Flow                                | 1.9.0          |
| Property tests | kotest-property                                  | 5.9.1          |
| Network tests  | OkHttp MockWebServer                             | 4.12.0         |

SDK levels: `compileSdk` 35, `targetSdk` 35, `minSdk` 24. `applicationId` =
`com.teleautomation.android`.

## Bootstrap (one-time, requires a JDK 17 + Android SDK)

The binary `gradle/wrapper/gradle-wrapper.jar` is intentionally not committed by the
scaffolding step (it is a binary artifact). Generate it once from a machine that has
Gradle installed:

```bash
cd android
gradle wrapper --gradle-version 8.11.1
```

After that, the project is buildable with the wrapper:

```bash
./gradlew :app:assembleDebug      # build
./gradlew :app:testDebugUnitTest  # unit + property tests
```

You also need a `local.properties` pointing at your Android SDK (created automatically
by Android Studio, or manually):

```
sdk.dir=/path/to/Android/Sdk
```
