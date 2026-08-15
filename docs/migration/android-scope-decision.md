# Android scope decision

## Classification

**5. INCOMPLETE AND SAFE TO EXCLUDE FROM THIS SPLIT**

The Android directory is preserved in the Marketing repository as historical
work-in-progress. It is excluded from the current Marketing and Operations
web/server staging scope. This decision does not delete the code or claim that the
client is complete.

## Evidence

- The authoritative monolith history introduces the directory in commits described
  as "feature-parity work in progress" (`639990b` and `83b56e3`).
- Android is a standalone HTTP/WebSocket client. It is not loaded by either FastAPI
  service and is not referenced by the server Dockerfiles, Compose definitions,
  deployment scripts, or web/server CI workflows.
- The current production-critical deployment is the server/web application. No
  evidence in the repository identifies an Android build or APK as a production
  runtime dependency.
- The client cannot be reproduced on this workstation: the wrapper JAR is absent by
  design, and JDK 17, Gradle, and an Android SDK are not installed/configured.
- The source tree is otherwise preserved from the authoritative monolith. Four
  Marketing navigation/role files differ to reflect the split ownership; those
  changes are source-level only and have not been validated by an Android build.

## Preservation correction

The repository-wide `data/` ignore pattern also matched the Kotlin package at
`android/app/src/main/java/com/teleautomation/android/data`. Explicit exceptions now
keep those 29 main-source files and four related test files tracked. Runtime `data/`
directories remain ignored.

## CI and release treatment

- Web/server CI must not fail solely because Android tooling is unavailable.
- A Marketing web/server staging release does not publish or modify an Android app.
- Android work requires a separate future scope: restore a reproducible wrapper,
  provision JDK 17 and Android SDK 35, build, run JVM/instrumented tests, and verify
  API/route compatibility against the split services.
- Until that work is completed, no Android parity, deployability, or production
  support claim is made.
