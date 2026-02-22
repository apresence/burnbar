package com.apresence.burnbar.api

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

data class UnifiedUsageInfo(
    val utilization5h: Double,
    val utilization7d: Double,
    val utilization7dSonnet: Double,
    val reset5h: Long,
    val reset7d: Long,
    val reset7dSonnet: Long,
) {
    val percentage: Double
        get() {
            val used = maxOf(utilization5h, utilization7d, utilization7dSonnet)
            return ((1.0 - used) * 100.0).coerceIn(0.0, 100.0)
        }

    /** Remaining capacity 0-100 (for threshold comparisons) */
    val sessionRemaining: Int get() = ((1.0 - utilization5h) * 100.0).coerceIn(0.0, 100.0).toInt()
    val weeklyRemaining: Int get() = ((1.0 - utilization7d) * 100.0).coerceIn(0.0, 100.0).toInt()
    val sonnetRemaining: Int get() = ((1.0 - utilization7dSonnet) * 100.0).coerceIn(0.0, 100.0).toInt()

    /** Usage 0-100 (for bar fill -- fills up as you burn through capacity) */
    val sessionUsage: Int get() = (utilization5h * 100.0).coerceIn(0.0, 100.0).toInt()
    val weeklyUsage: Int get() = (utilization7d * 100.0).coerceIn(0.0, 100.0).toInt()
    val sonnetUsage: Int get() = (utilization7dSonnet * 100.0).coerceIn(0.0, 100.0).toInt()

    fun resetCountdown(epochSeconds: Long): String {
        if (epochSeconds <= 0) return ""
        val now = Instant.now().epochSecond
        val secs = epochSeconds - now
        return when {
            secs <= 0 -> "now"
            secs < 3600 -> "${secs / 60}m"
            secs < 86400 -> "${secs / 3600}h"
            else -> "${secs / 86400}d"
        }
    }

    val session5hCountdown: String get() = resetCountdown(reset5h)
    val weekly7dCountdown: String get() = resetCountdown(reset7d)
    val sonnet7dCountdown: String get() = resetCountdown(reset7dSonnet)
}
