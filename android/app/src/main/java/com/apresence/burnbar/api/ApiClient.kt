package com.apresence.burnbar.api

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit

class ApiError(message: String) : Exception(message)

class ApiClient(
    private val apiKey: String = "",
    private val endpointMode: String = "both",
    private val authMode: String = "api_key",
    private val accessToken: String = "",
) {

    companion object {
        private const val API_BASE = "https://api.anthropic.com/v1"
        private val JSON_TYPE = "application/json".toMediaType()
    }

    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .build()

    fun checkUsageApiKey(): UsageInfo {
        if (apiKey.isBlank()) throw ApiError("API key not configured")

        var lastError: ApiError? = null

        if (endpointMode in listOf("both", "count_tokens")) {
            try {
                val resp = callCountTokens()
                if (hasRatelimitHeaders(resp)) {
                    return parseHeaders(resp).also { resp.close() }
                }
                resp.close()
            } catch (e: ApiError) {
                lastError = e
                if (endpointMode == "count_tokens") throw e
            }
        }

        if (endpointMode in listOf("both", "messages")) {
            try {
                val resp = callMessagesMinimal("claude-haiku-4-5-20251001")
                if (hasRatelimitHeaders(resp)) {
                    return parseHeaders(resp).also { resp.close() }
                }
                resp.close()
            } catch (e: ApiError) {
                throw e
            }
        }

        throw lastError ?: ApiError("API did not return rate-limit headers")
    }

    fun checkUsageOAuth(): UnifiedUsageInfo {
        if (accessToken.isBlank()) throw ApiError("OAuth token not configured")

        val resp = callMessagesMinimal("claude-sonnet-4-6")

        if (hasUnifiedHeaders(resp)) {
            return parseUnifiedHeaders(resp).also { resp.close() }
        }

        if (hasRatelimitHeaders(resp)) {
            val std = parseHeaders(resp)
            resp.close()
            val utilization = 1.0 - (std.percentage / 100.0)
            return UnifiedUsageInfo(
                utilization5h = utilization,
                utilization7d = 0.0,
                utilization7dSonnet = 0.0,
                reset5h = 0,
                reset7d = 0,
                reset7dSonnet = 0,
            )
        }

        resp.close()
        throw ApiError("API did not return usage headers (OAuth)")
    }

    private fun buildHeaders(): Map<String, String> {
        return if (authMode == "oauth") {
            mapOf(
                "Authorization" to "Bearer $accessToken",
                "anthropic-version" to "2023-06-01",
                "anthropic-beta" to "oauth-2025-04-20",
                "content-type" to "application/json",
            )
        } else {
            mapOf(
                "x-api-key" to apiKey,
                "anthropic-version" to "2023-06-01",
                "content-type" to "application/json",
            )
        }
    }

    private fun callCountTokens(): Response {
        val body = """{"model":"claude-haiku-4-5-20251001","max_tokens":1,"messages":[{"role":"user","content":"x"}]}"""
            .toRequestBody(JSON_TYPE)

        val builder = Request.Builder()
            .url("$API_BASE/messages/count_tokens")
            .post(body)
        buildHeaders().forEach { (k, v) -> builder.header(k, v) }

        return executeRequest(builder.build())
    }

    private fun callMessagesMinimal(model: String): Response {
        val body = """{"model":"$model","max_tokens":1,"messages":[{"role":"user","content":"."}]}"""
            .toRequestBody(JSON_TYPE)

        val builder = Request.Builder()
            .url("$API_BASE/messages")
            .post(body)
        buildHeaders().forEach { (k, v) -> builder.header(k, v) }

        return executeRequest(builder.build())
    }

    private fun executeRequest(request: Request): Response {
        val resp: Response
        try {
            resp = http.newCall(request).execute()
        } catch (_: SocketTimeoutException) {
            throw ApiError("Request timed out")
        } catch (_: IOException) {
            throw ApiError("Network error -- check your connection")
        }

        checkStatus(resp)
        return resp
    }

    private fun checkStatus(resp: Response) {
        val isOAuth = authMode == "oauth"
        when (resp.code) {
            200, 429 -> return
            401 -> throw ApiError(if (isOAuth) "OAuth token invalid or expired" else "Invalid API key")
            403 -> throw ApiError(if (isOAuth) "OAuth token lacks permission" else "API key lacks permission")
            400 -> {
                val msg = try {
                    val json = resp.body?.string() ?: ""
                    if ("credit balance" in json.lowercase() || "billing" in json.lowercase()) {
                        throw ApiError("No API credits -- check Plans & Billing")
                    }
                    json.take(200)
                } catch (e: ApiError) {
                    throw e
                } catch (_: Exception) {
                    ""
                }
                throw ApiError(if (msg.isNotBlank()) "Bad request: $msg" else "Bad request")
            }
            in 500..599 -> throw ApiError("Anthropic server error (${resp.code})")
            else -> throw ApiError("Unexpected status ${resp.code}")
        }
    }

    private fun hasRatelimitHeaders(resp: Response): Boolean =
        resp.header("anthropic-ratelimit-tokens-limit") != null

    private fun hasUnifiedHeaders(resp: Response): Boolean =
        resp.header("anthropic-ratelimit-unified-5h-utilization") != null

    private fun parseHeaders(resp: Response): UsageInfo {
        val exhausted = resp.code == 429
        val tokensLimit = resp.header("anthropic-ratelimit-tokens-limit")?.toLongOrNull() ?: 0L
        val tokensRemaining = if (exhausted) 0L
            else resp.header("anthropic-ratelimit-tokens-remaining")?.toLongOrNull() ?: 0L
        val requestsLimit = resp.header("anthropic-ratelimit-requests-limit")?.toLongOrNull() ?: 0L
        val requestsRemaining = if (exhausted) 0L
            else resp.header("anthropic-ratelimit-requests-remaining")?.toLongOrNull() ?: 0L
        val resetTime = resp.header("anthropic-ratelimit-tokens-reset") ?: ""

        if (tokensLimit == 0L) throw ApiError("Rate-limit headers present but token limit is 0")

        return UsageInfo(
            tokensRemaining = tokensRemaining,
            tokensLimit = tokensLimit,
            requestsRemaining = requestsRemaining,
            requestsLimit = requestsLimit,
            resetTime = resetTime,
        )
    }

    private fun parseUnifiedHeaders(resp: Response): UnifiedUsageInfo {
        val exhausted = resp.code == 429
        var util5h = resp.header("anthropic-ratelimit-unified-5h-utilization")?.toDoubleOrNull() ?: 0.0
        val util7d = resp.header("anthropic-ratelimit-unified-7d-utilization")?.toDoubleOrNull() ?: 0.0
        val util7dSonnet = resp.header("anthropic-ratelimit-unified-7d_sonnet-utilization")?.toDoubleOrNull() ?: 0.0
        val reset5h = resp.header("anthropic-ratelimit-unified-5h-reset")?.toLongOrNull() ?: 0L
        val reset7d = resp.header("anthropic-ratelimit-unified-7d-reset")?.toLongOrNull() ?: 0L
        val reset7dSonnet = resp.header("anthropic-ratelimit-unified-7d_sonnet-reset")?.toLongOrNull() ?: 0L

        if (exhausted) util5h = maxOf(util5h, 1.0)

        return UnifiedUsageInfo(
            utilization5h = util5h,
            utilization7d = util7d,
            utilization7dSonnet = util7dSonnet,
            reset5h = reset5h,
            reset7d = reset7d,
            reset7dSonnet = reset7dSonnet,
        )
    }
}
