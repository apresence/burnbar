package com.apresence.burnbar.api

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

data class UsageInfo(
    val tokensRemaining: Long,
    val tokensLimit: Long,
    val requestsRemaining: Long,
    val requestsLimit: Long,
    val resetTime: String = "",
) {
    val percentage: Double
        get() = if (tokensLimit <= 0) 100.0
                else (tokensRemaining.toDouble() / tokensLimit * 100.0).coerceIn(0.0, 100.0)

    /** Remaining capacity 0-100 (for threshold comparisons) */
    val tokenRemaining: Int get() = percentage.toInt()
    val requestRemaining: Int
        get() = if (requestsLimit <= 0) 100
                else ((requestsRemaining.toDouble() / requestsLimit * 100.0).coerceIn(0.0, 100.0)).toInt()

    /** Usage 0-100 (for bar fill -- fills up as you burn through capacity) */
    val tokenUsage: Int get() = 100 - tokenRemaining
    val requestUsage: Int get() = 100 - requestRemaining

    fun resetCountdown(): String {
        if (resetTime.isBlank()) return ""
        return try {
            val instant = Instant.parse(resetTime)
            val now = Instant.now()
            val secs = instant.epochSecond - now.epochSecond
            when {
                secs <= 0 -> "now"
                secs < 3600 -> "${secs / 60}m"
                secs < 86400 -> "${secs / 3600}h"
                else -> "${secs / 86400}d"
            }
        } catch (_: Exception) {
            resetTime
        }
    }

    fun resetDisplay(): String {
        if (resetTime.isBlank()) return ""
        return try {
            val instant = Instant.parse(resetTime)
            val local = instant.atZone(ZoneId.systemDefault())
            local.format(DateTimeFormatter.ofPattern("h:mm a"))
        } catch (_: Exception) {
            resetTime
        }
    }
}
