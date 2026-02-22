package com.apresence.burnbar.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class Preferences(context: Context) {

    private val masterKey: MasterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        "burnbar_prefs",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var authMode: String
        get() = prefs.getString(KEY_AUTH_MODE, DEFAULT_AUTH_MODE) ?: DEFAULT_AUTH_MODE
        set(value) = prefs.edit().putString(KEY_AUTH_MODE, value).apply()

    var apiKey: String
        get() = prefs.getString(KEY_API_KEY, "") ?: ""
        set(value) = prefs.edit().putString(KEY_API_KEY, value).apply()

    var oauthAccessToken: String
        get() = prefs.getString(KEY_OAUTH_ACCESS_TOKEN, "") ?: ""
        set(value) = prefs.edit().putString(KEY_OAUTH_ACCESS_TOKEN, value).apply()

    var oauthRefreshToken: String
        get() = prefs.getString(KEY_OAUTH_REFRESH_TOKEN, "") ?: ""
        set(value) = prefs.edit().putString(KEY_OAUTH_REFRESH_TOKEN, value).apply()

    var oauthExpiresAt: Long
        get() = prefs.getLong(KEY_OAUTH_EXPIRES_AT, 0)
        set(value) = prefs.edit().putLong(KEY_OAUTH_EXPIRES_AT, value).apply()

    var pollIntervalSeconds: Int
        get() = prefs.getInt(KEY_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        set(value) = prefs.edit().putInt(KEY_POLL_INTERVAL, value.coerceAtLeast(10)).apply()

    var yellowThresholdPct: Int
        get() = prefs.getInt(KEY_YELLOW_THRESHOLD, DEFAULT_YELLOW_THRESHOLD)
        set(value) = prefs.edit().putInt(KEY_YELLOW_THRESHOLD, value).apply()

    var redThresholdPct: Int
        get() = prefs.getInt(KEY_RED_THRESHOLD, DEFAULT_RED_THRESHOLD)
        set(value) = prefs.edit().putInt(KEY_RED_THRESHOLD, value).apply()

    var criticalThresholdPct: Int
        get() = prefs.getInt(KEY_CRITICAL_THRESHOLD, DEFAULT_CRITICAL_THRESHOLD)
        set(value) = prefs.edit().putInt(KEY_CRITICAL_THRESHOLD, value).apply()

    var endpointMode: String
        get() = prefs.getString(KEY_ENDPOINT_MODE, DEFAULT_ENDPOINT_MODE) ?: DEFAULT_ENDPOINT_MODE
        set(value) = prefs.edit().putString(KEY_ENDPOINT_MODE, value).apply()

    /** Which bar to show in the status bar icon: "session", "weekly", "sonnet", or "worst" */
    var statusBarIcon: String
        get() = prefs.getString(KEY_STATUS_BAR_ICON, DEFAULT_STATUS_BAR_ICON) ?: DEFAULT_STATUS_BAR_ICON
        set(value) = prefs.edit().putString(KEY_STATUS_BAR_ICON, value).apply()

    val hasCredentials: Boolean
        get() = if (authMode == "oauth") oauthAccessToken.isNotBlank() else apiKey.isNotBlank()

    val hasOAuthToken: Boolean
        get() = oauthAccessToken.isNotBlank()

    companion object {
        private const val KEY_AUTH_MODE = "auth_mode"
        private const val KEY_API_KEY = "api_key"
        private const val KEY_OAUTH_ACCESS_TOKEN = "oauth_access_token"
        private const val KEY_OAUTH_REFRESH_TOKEN = "oauth_refresh_token"
        private const val KEY_OAUTH_EXPIRES_AT = "oauth_expires_at"
        private const val KEY_POLL_INTERVAL = "poll_interval_seconds"
        private const val KEY_YELLOW_THRESHOLD = "yellow_threshold_pct"
        private const val KEY_RED_THRESHOLD = "red_threshold_pct"
        private const val KEY_CRITICAL_THRESHOLD = "critical_threshold_pct"
        private const val KEY_ENDPOINT_MODE = "endpoint_mode"
        private const val KEY_STATUS_BAR_ICON = "status_bar_icon"

        const val DEFAULT_AUTH_MODE = "oauth"
        const val DEFAULT_POLL_INTERVAL = 60
        const val DEFAULT_YELLOW_THRESHOLD = 25
        const val DEFAULT_RED_THRESHOLD = 5
        const val DEFAULT_CRITICAL_THRESHOLD = 3
        const val DEFAULT_ENDPOINT_MODE = "both"
        const val DEFAULT_STATUS_BAR_ICON = "session"
    }
}
