# Default ProGuard/R8 rules for the release build.

# Keep kotlinx.serialization generated serializers.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**

# Keep @Serializable classes and their synthetic companion + serializer.
-keepclassmembers class **$$serializer { *; }
-keepclasseswithmembers class * {
    @kotlinx.serialization.Serializable <methods>;
}
-keep,includedescriptorclasses class com.teleautomation.android.**$$serializer { *; }
-keepclassmembers class com.teleautomation.android.** {
    *** Companion;
}

# Retrofit / OkHttp.
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn retrofit2.**
-keepattributes Signature, Exceptions
