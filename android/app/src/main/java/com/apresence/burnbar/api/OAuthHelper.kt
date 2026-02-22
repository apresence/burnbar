package com.apresence.burnbar.api

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.TimeUnit

object OAuthHelper {

    private const val CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    private const val AUTH_URL = "https://claude.ai/oauth/authorize"
    private const val TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
    private const val REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
    private const val SCOPES = "user:inference user:profile"
    private const val EXPIRY_BUFFER_SECONDS = 300

    private val JSON_TYPE = "application/json".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    data class PkceChallenge(val verifier: String, val challenge: String)

    fun generatePkce(): PkceChallenge {
        val bytes = ByteArray(48)
        SecureRandom().nextBytes(bytes)
        val verifier = android.util.Base64.encodeToString(
            bytes, android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING,
        )
        val digest = MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray(Charsets.US_ASCII))
        val challenge = android.util.Base64.encodeToString(
            digest, android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING,
        )
        return PkceChallenge(verifier, challenge)
    }

    fun generateState(): String {
        val bytes = ByteArray(16)
        SecureRandom().nextBytes(bytes)
        return android.util.Base64.encodeToString(
            bytes, android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING,
        )
    }

    fun getAuthorizationUrl(codeChallenge: String, state: String): String {
        val params = mapOf(
            "code" to "true",
            "response_type" to "code",
            "client_id" to CLIENT_ID,
            "redirect_uri" to REDIRECT_URI,
            "scope" to SCOPES,
            "code_challenge" to codeChallenge,
            "code_challenge_method" to "S256",
            "state" to state,
        )
        val query = params.entries.joinToString("&") { (k, v) ->
            "${java.net.URLEncoder.encode(k, "UTF-8")}=${java.net.URLEncoder.encode(v, "UTF-8")}"
        }
        return "$AUTH_URL?$query"
    }

    data class TokenResult(val accessToken: String, val refreshToken: String, val expiresAt: Long)

    fun exchangeCode(code: String, codeVerifier: String): TokenResult {
        val json = JSONObject().apply {
            put("grant_type", "authorization_code")
            put("client_id", CLIENT_ID)
            put("code", code)
            put("redirect_uri", REDIRECT_URI)
            put("code_verifier", codeVerifier)
        }

        val request = Request.Builder()
            .url(TOKEN_URL)
            .post(json.toString().toRequestBody(JSON_TYPE))
            .build()

        val resp = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            throw ApiError("Network error during token exchange")
        }

        if (resp.code != 200) {
            val body = resp.body?.string()?.take(200) ?: ""
            resp.close()
            throw ApiError("Token exchange failed (${resp.code}): $body")
        }

        val data = JSONObject(resp.body!!.string())
        resp.close()
        val accessToken = data.getString("access_token")
        val refreshToken = data.optString("refresh_token", "")
        val expiresIn = data.optLong("expires_in", 3600)
        val expiresAt = System.currentTimeMillis() / 1000 + expiresIn

        return TokenResult(accessToken, refreshToken, expiresAt)
    }

    fun refreshAccessToken(refreshToken: String): TokenResult {
        val json = JSONObject().apply {
            put("grant_type", "refresh_token")
            put("client_id", CLIENT_ID)
            put("refresh_token", refreshToken)
        }

        val request = Request.Builder()
            .url(TOKEN_URL)
            .post(json.toString().toRequestBody(JSON_TYPE))
            .build()

        val resp = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            throw ApiError("Network error during token refresh")
        }

        if (resp.code != 200) {
            val body = resp.body?.string()?.take(200) ?: ""
            resp.close()
            throw ApiError("Token refresh failed (${resp.code}): $body")
        }

        val data = JSONObject(resp.body!!.string())
        resp.close()
        val newAccessToken = data.getString("access_token")
        val newRefreshToken = data.optString("refresh_token", refreshToken)
        val expiresIn = data.optLong("expires_in", 3600)
        val newExpiresAt = System.currentTimeMillis() / 1000 + expiresIn

        return TokenResult(newAccessToken, newRefreshToken, newExpiresAt)
    }

    fun isTokenExpired(expiresAt: Long): Boolean {
        if (expiresAt <= 0) return true
        return System.currentTimeMillis() / 1000 >= (expiresAt - EXPIRY_BUFFER_SECONDS)
    }
}
