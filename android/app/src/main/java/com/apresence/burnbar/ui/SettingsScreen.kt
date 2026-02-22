package com.apresence.burnbar.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.apresence.burnbar.data.Preferences

@Composable
fun SettingsScreen(
    prefs: Preferences,
    isServiceRunning: Boolean,
    onStartService: () -> Unit,
    onStopService: () -> Unit,
    onBrowserLogin: () -> Unit,
    onPasteToken: () -> Unit,
    oauthStatus: String,
) {
    var authMode by remember { mutableStateOf(prefs.authMode) }
    var apiKey by remember { mutableStateOf(prefs.apiKey) }
    var pollInterval by remember { mutableStateOf(prefs.pollIntervalSeconds.toString()) }
    var yellowThreshold by remember { mutableStateOf(prefs.yellowThresholdPct.toString()) }
    var redThreshold by remember { mutableStateOf(prefs.redThresholdPct.toString()) }
    var criticalThreshold by remember { mutableStateOf(prefs.criticalThresholdPct.toString()) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            text = "BurnBar",
            style = MaterialTheme.typography.headlineMedium,
        )

        Spacer(modifier = Modifier.height(4.dp))

        // Auth mode
        Text(
            text = "Authentication",
            style = MaterialTheme.typography.titleSmall,
        )

        Row(verticalAlignment = Alignment.CenterVertically) {
            RadioButton(
                selected = authMode == "oauth",
                onClick = {
                    authMode = "oauth"
                    prefs.authMode = "oauth"
                },
            )
            Text("Claude.ai (OAuth)", modifier = Modifier.padding(end = 16.dp))
            RadioButton(
                selected = authMode == "api_key",
                onClick = {
                    authMode = "api_key"
                    prefs.authMode = "api_key"
                },
            )
            Text("API Key")
        }

        // OAuth section
        if (authMode == "oauth") {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onBrowserLogin) {
                    Text("Login with Browser")
                }
                OutlinedButton(onClick = onPasteToken) {
                    Text("Paste Token")
                }
            }
            Text(
                text = oauthStatus,
                style = MaterialTheme.typography.bodySmall,
                color = if (prefs.hasOAuthToken) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }

        // API Key section
        if (authMode == "api_key") {
            OutlinedTextField(
                value = apiKey,
                onValueChange = {
                    apiKey = it
                    prefs.apiKey = it
                },
                label = { Text("API Key") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }

        HorizontalDivider()

        // Poll interval
        OutlinedTextField(
            value = pollInterval,
            onValueChange = {
                pollInterval = it
                it.toIntOrNull()?.let { v -> prefs.pollIntervalSeconds = v }
            },
            label = { Text("Poll interval (seconds)") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        // Thresholds
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value = yellowThreshold,
                onValueChange = {
                    yellowThreshold = it
                    it.toIntOrNull()?.let { v -> prefs.yellowThresholdPct = v }
                },
                label = { Text("Yellow %") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = redThreshold,
                onValueChange = {
                    redThreshold = it
                    it.toIntOrNull()?.let { v -> prefs.redThresholdPct = v }
                },
                label = { Text("Red %") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = criticalThreshold,
                onValueChange = {
                    criticalThreshold = it
                    it.toIntOrNull()?.let { v -> prefs.criticalThresholdPct = v }
                },
                label = { Text("Critical %") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
        }

        Spacer(modifier = Modifier.height(8.dp))

        Button(
            onClick = {
                if (isServiceRunning) onStopService() else onStartService()
            },
            modifier = Modifier.align(Alignment.CenterHorizontally),
            colors = if (isServiceRunning) {
                ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
            } else {
                ButtonDefaults.buttonColors()
            },
        ) {
            Text(if (isServiceRunning) "Stop Monitoring" else "Start Monitoring")
        }

        if (!prefs.hasCredentials) {
            Text(
                text = if (authMode == "oauth") "Login with your browser to start monitoring."
                       else "Enter your Anthropic API key to start monitoring.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
