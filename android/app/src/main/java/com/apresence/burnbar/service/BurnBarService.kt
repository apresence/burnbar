package com.apresence.burnbar.service

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import com.apresence.burnbar.api.ApiClient
import com.apresence.burnbar.api.ApiError
import com.apresence.burnbar.api.OAuthHelper
import com.apresence.burnbar.data.Preferences
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class BurnBarService : Service() {

    private lateinit var notificationHelper: NotificationHelper
    private lateinit var prefs: Preferences
    private var pollJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO)

    companion object {
        private const val ACTION_START = "com.apresence.burnbar.START"
        private const val ACTION_STOP = "com.apresence.burnbar.STOP"

        fun start(context: Context) {
            val intent = Intent(context, BurnBarService::class.java).apply {
                action = ACTION_START
            }
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            val intent = Intent(context, BurnBarService::class.java).apply {
                action = ACTION_STOP
            }
            context.startService(intent)
        }
    }

    override fun onCreate() {
        super.onCreate()
        prefs = Preferences(this)
        notificationHelper = NotificationHelper(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopPolling()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                startForeground(NotificationHelper.NOTIFICATION_ID, notificationHelper.buildInitial())
                startPolling()
            }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopPolling()
        super.onDestroy()
    }

    private fun startPolling() {
        pollJob?.cancel()
        pollJob = scope.launch {
            delay(1000)
            while (isActive) {
                poll()
                val interval = prefs.pollIntervalSeconds.coerceAtLeast(10)
                delay(interval * 1000L)
            }
        }
    }

    private fun stopPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    private fun poll() {
        if (!prefs.hasCredentials) {
            notificationHelper.update(notificationHelper.buildError("No credentials configured"))
            return
        }

        try {
            if (prefs.authMode == "oauth") {
                pollOAuth()
            } else {
                pollApiKey()
            }
        } catch (e: ApiError) {
            notificationHelper.update(notificationHelper.buildError(e.message ?: "Unknown error"))
        } catch (e: Exception) {
            notificationHelper.update(notificationHelper.buildError("Error: ${e.message?.take(60)}"))
        }
    }

    private fun pollApiKey() {
        val client = ApiClient(apiKey = prefs.apiKey, endpointMode = prefs.endpointMode, authMode = "api_key")
        val usage = client.checkUsageApiKey()
        notificationHelper.update(notificationHelper.buildForApiKey(usage))
    }

    private fun pollOAuth() {
        // Try with current token first
        try {
            val client = ApiClient(authMode = "oauth", accessToken = prefs.oauthAccessToken)
            val usage = client.checkUsageOAuth()
            notificationHelper.update(notificationHelper.buildForOAuth(usage))
            return
        } catch (e: ApiError) {
            // If 401, try refreshing token and retry
            if (e.message?.contains("invalid or expired") != true) throw e
        }

        // Token rejected -- try refresh
        if (prefs.oauthRefreshToken.isBlank()) {
            throw ApiError("OAuth token expired and no refresh token available")
        }

        val result = OAuthHelper.refreshAccessToken(prefs.oauthRefreshToken)
        prefs.oauthAccessToken = result.accessToken
        prefs.oauthRefreshToken = result.refreshToken
        prefs.oauthExpiresAt = result.expiresAt

        // Retry with new token
        val client = ApiClient(authMode = "oauth", accessToken = prefs.oauthAccessToken)
        val usage = client.checkUsageOAuth()
        notificationHelper.update(notificationHelper.buildForOAuth(usage))
    }
}
