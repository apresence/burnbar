package com.apresence.burnbar.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Build
import android.view.View
import android.widget.RemoteViews
import androidx.core.app.NotificationCompat
import androidx.core.graphics.drawable.IconCompat
import com.apresence.burnbar.MainActivity
import com.apresence.burnbar.R
import com.apresence.burnbar.api.UnifiedUsageInfo
import com.apresence.burnbar.api.UsageInfo
import com.apresence.burnbar.data.Preferences

class NotificationHelper(private val context: Context) {

    companion object {
        const val CHANNEL_ID = "burnbar_usage"
        const val NOTIFICATION_ID = 1

        private const val COLOR_GREEN = 0xFF4CAF50.toInt()
        private const val COLOR_YELLOW = 0xFFFFC107.toInt()
        private const val COLOR_RED = 0xFFF44336.toInt()

        private const val ICON_HEIGHT_DP = 24
        private const val ICON_WIDTH_DP = 36
    }

    private val manager: NotificationManager =
        context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    private val prefs = Preferences(context)
    private val density = context.resources.displayMetrics.density

    init {
        val channel = NotificationChannel(
            CHANNEL_ID,
            context.getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = context.getString(R.string.notification_channel_description)
            setShowBadge(false)
            setSound(null, null)
            enableVibration(false)
        }
        manager.createNotificationChannel(channel)
    }

    fun buildInitial(): Notification = buildNotification("Starting...", iconLevels = null)

    fun buildForApiKey(usage: UsageInfo): Notification {
        val views = RemoteViews(context.packageName, R.layout.notification_bars)

        views.setTextViewText(R.id.label1, "Tok")
        views.setProgressBar(R.id.bar1, 100, usage.tokenUsage, false)
        tintBar(views, R.id.bar1, usage.tokenRemaining)
        views.setTextViewText(R.id.reset1, usage.resetCountdown())

        views.setTextViewText(R.id.label2, "Req")
        views.setProgressBar(R.id.bar2, 100, usage.requestUsage, false)
        tintBar(views, R.id.bar2, usage.requestRemaining)
        views.setTextViewText(R.id.reset2, "${usage.requestRemaining}%")

        views.setViewVisibility(R.id.row3, View.GONE)

        val contentText = "Tokens: ${usage.tokenUsage}% | Requests: ${usage.requestUsage}%"
        return buildNotification(contentText, views, listOf(usage.tokenUsage, usage.requestUsage))
    }

    fun buildForOAuth(usage: UnifiedUsageInfo): Notification {
        val views = RemoteViews(context.packageName, R.layout.notification_bars)

        views.setTextViewText(R.id.label1, "Sess")
        views.setProgressBar(R.id.bar1, 100, usage.sessionUsage, false)
        tintBar(views, R.id.bar1, usage.sessionRemaining)
        views.setTextViewText(R.id.reset1, usage.session5hCountdown)

        views.setTextViewText(R.id.label2, "Week")
        views.setProgressBar(R.id.bar2, 100, usage.weeklyUsage, false)
        tintBar(views, R.id.bar2, usage.weeklyRemaining)
        views.setTextViewText(R.id.reset2, usage.weekly7dCountdown)

        views.setViewVisibility(R.id.row3, View.VISIBLE)
        views.setTextViewText(R.id.label3, "Sonn")
        views.setProgressBar(R.id.bar3, 100, usage.sonnetUsage, false)
        tintBar(views, R.id.bar3, usage.sonnetRemaining)
        views.setTextViewText(R.id.reset3, usage.sonnet7dCountdown)

        val contentText = "Sess: ${usage.sessionUsage}% | Week: ${usage.weeklyUsage}% | Sonn: ${usage.sonnetUsage}%"
        return buildNotification(contentText, views, listOf(usage.sessionUsage, usage.weeklyUsage, usage.sonnetUsage))
    }

    fun buildError(error: String): Notification = buildNotification(error, iconLevels = null)

    fun update(notification: Notification) {
        manager.notify(NOTIFICATION_ID, notification)
    }

    /** Color based on remaining capacity (green = safe, red = low) */
    private fun tintBar(views: RemoteViews, viewId: Int, remaining: Int) {
        val color = when {
            remaining <= prefs.redThresholdPct -> COLOR_RED
            remaining <= prefs.yellowThresholdPct -> COLOR_YELLOW
            else -> COLOR_GREEN
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            views.setColorStateList(viewId, "setProgressTintList", ColorStateList.valueOf(color))
        }
    }

    /**
     * Draw status bar icon with horizontal gauge bars (usage %).
     * White fill on semi-transparent track, wider than tall for readability.
     */
    private fun drawBarIcon(levels: List<Int>): IconCompat {
        val widthPx = (ICON_WIDTH_DP * density).toInt()
        val heightPx = (ICON_HEIGHT_DP * density).toInt()
        val bitmap = Bitmap.createBitmap(widthPx, heightPx, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)

        val barCount = levels.size
        val padV = heightPx * 0.12f
        val padH = widthPx * 0.04f
        val gap = heightPx * 0.08f
        val totalGaps = gap * (barCount - 1)
        val barHeight = (heightPx - padV * 2 - totalGaps) / barCount
        val barWidth = widthPx - padH * 2
        val radius = barHeight / 3f

        val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.argb(80, 255, 255, 255)
        }
        val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
        }

        for (i in levels.indices) {
            val top = padV + i * (barHeight + gap)
            val bottom = top + barHeight
            val fillW = barWidth * (levels[i].coerceIn(0, 100) / 100f)

            canvas.drawRoundRect(padH, top, padH + barWidth, bottom, radius, radius, trackPaint)
            if (fillW > 0) {
                canvas.drawRoundRect(padH, top, padH + fillW, bottom, radius, radius, fillPaint)
            }
        }

        return IconCompat.createWithBitmap(bitmap)
    }

    private fun buildNotification(
        contentText: String,
        customView: RemoteViews? = null,
        iconLevels: List<Int>? = null,
    ): Notification {
        val tapIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            context, 0, tapIntent, PendingIntent.FLAG_IMMUTABLE,
        )

        val builder = NotificationCompat.Builder(context, CHANNEL_ID)
            .setContentTitle("BurnBar")
            .setContentText(contentText)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setSilent(true)
            .setOnlyAlertOnce(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setCategory(NotificationCompat.CATEGORY_STATUS)

        if (iconLevels != null) {
            builder.setSmallIcon(drawBarIcon(iconLevels))
        } else {
            builder.setSmallIcon(android.R.drawable.ic_menu_info_details)
        }

        if (customView != null) {
            builder.setCustomContentView(customView)
            builder.setCustomBigContentView(customView)
            builder.setStyle(NotificationCompat.DecoratedCustomViewStyle())
        }

        return builder.build()
    }
}
