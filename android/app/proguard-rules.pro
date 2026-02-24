-keepattributes *Annotation*
-dontwarn okhttp3.**
-keep class okhttp3.** { *; }

# Google Tink (via androidx.security:security-crypto)
-dontwarn com.google.errorprone.annotations.CanIgnoreReturnValue
-dontwarn com.google.errorprone.annotations.CheckReturnValue
-dontwarn com.google.errorprone.annotations.Immutable
-dontwarn com.google.errorprone.annotations.RestrictedApi
