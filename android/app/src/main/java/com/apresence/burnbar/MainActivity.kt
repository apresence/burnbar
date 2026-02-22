package com.apresence.burnbar

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import com.apresence.burnbar.api.ApiError
import com.apresence.burnbar.api.OAuthHelper
import com.apresence.burnbar.data.Preferences
import com.apresence.burnbar.service.BurnBarService
import com.apresence.burnbar.ui.SettingsScreen
import com.apresence.burnbar.ui.theme.BurnBarTheme

class MainActivity : ComponentActivity() {

    private lateinit var prefs: Preferences
    private var serviceRunning by mutableStateOf(false)
    private var oauthStatus by mutableStateOf("")
    private var pendingPkce: OAuthHelper.PkceChallenge? = null

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) startMonitoring()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Preferences(this)
        updateOAuthStatus()

        setContent {
            BurnBarTheme {
                SettingsScreen(
                    prefs = prefs,
                    isServiceRunning = serviceRunning,
                    onStartService = ::requestStartMonitoring,
                    onStopService = ::stopMonitoring,
                    onBrowserLogin = ::startBrowserLogin,
                    onPasteToken = ::showPasteTokenDialog,
                    oauthStatus = oauthStatus,
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        updateOAuthStatus()
    }

    private fun updateOAuthStatus() {
        oauthStatus = when {
            !prefs.hasOAuthToken -> "No token -- login or paste token"
            prefs.oauthExpiresAt == 0L -> "Token loaded"
            OAuthHelper.isTokenExpired(prefs.oauthExpiresAt) -> "Token loaded (expired -- will auto-refresh)"
            else -> "Token loaded"
        }
    }

    private fun startBrowserLogin() {
        val pkce = OAuthHelper.generatePkce()
        pendingPkce = pkce
        val state = OAuthHelper.generateState()
        val url = OAuthHelper.getAuthorizationUrl(pkce.challenge, state)

        val browserIntent = android.content.Intent(android.content.Intent.ACTION_VIEW, Uri.parse(url))
        startActivity(browserIntent)

        Toast.makeText(this, "Complete login in browser, then paste the code", Toast.LENGTH_LONG).show()

        showCodeInputDialog()
    }

    private fun showPasteTokenDialog() {
        val dp = resources.displayMetrics.density
        val pad = (24 * dp).toInt()

        val layout = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(pad, pad, pad, 0)
        }

        val accessLabel = android.widget.TextView(this).apply { text = "Access Token" }
        val accessInput = android.widget.EditText(this).apply {
            hint = "Paste access token"
            setSingleLine()
        }
        val refreshLabel = android.widget.TextView(this).apply {
            text = "Refresh Token"
            setPadding(0, (12 * dp).toInt(), 0, 0)
        }
        val refreshInput = android.widget.EditText(this).apply {
            hint = "Paste refresh token"
            setSingleLine()
        }

        layout.addView(accessLabel)
        layout.addView(accessInput)
        layout.addView(refreshLabel)
        layout.addView(refreshInput)

        val scroll = android.widget.ScrollView(this).apply { addView(layout) }

        android.app.AlertDialog.Builder(this)
            .setTitle("Paste Tokens")
            .setView(scroll)
            .setPositiveButton("OK") { _, _ ->
                val access = accessInput.text.toString().trim()
                if (access.isNotBlank()) {
                    prefs.oauthAccessToken = access
                    prefs.oauthRefreshToken = refreshInput.text.toString().trim()
                    prefs.oauthExpiresAt = 0
                    updateOAuthStatus()
                    Toast.makeText(this, "Token saved!", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showCodeInputDialog() {
        val editText = android.widget.EditText(this).apply {
            hint = "Paste authorization code"
            setSingleLine()
        }

        android.app.AlertDialog.Builder(this)
            .setTitle("Authorization Code")
            .setMessage("After logging in, copy the authorization code from the browser and paste it here.")
            .setView(editText)
            .setPositiveButton("OK") { _, _ ->
                val code = editText.text.toString().trim()
                if (code.isNotBlank()) {
                    exchangeCode(code)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun exchangeCode(code: String) {
        val pkce = pendingPkce ?: return
        Thread {
            try {
                val result = OAuthHelper.exchangeCode(code, pkce.verifier)
                prefs.oauthAccessToken = result.accessToken
                prefs.oauthRefreshToken = result.refreshToken
                prefs.oauthExpiresAt = result.expiresAt
                runOnUiThread {
                    updateOAuthStatus()
                    Toast.makeText(this, "Login successful!", Toast.LENGTH_SHORT).show()
                }
            } catch (e: ApiError) {
                runOnUiThread {
                    Toast.makeText(this, "Login failed: ${e.message}", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this, "Login failed: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
        pendingPkce = null
    }

    private fun requestStartMonitoring() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val perm = Manifest.permission.POST_NOTIFICATIONS
            if (ContextCompat.checkSelfPermission(this, perm) != PackageManager.PERMISSION_GRANTED) {
                notificationPermissionLauncher.launch(perm)
                return
            }
        }
        startMonitoring()
    }

    private fun startMonitoring() {
        BurnBarService.start(this)
        serviceRunning = true
    }

    private fun stopMonitoring() {
        BurnBarService.stop(this)
        serviceRunning = false
    }
}
