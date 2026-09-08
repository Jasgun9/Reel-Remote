package com.example.reelremote

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.example.reelremote.databinding.ActivityMainBinding
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * The whole UI: turn the accessibility service on, start/stop the listener, read off the
 * IP / port / token, and tune the gesture geometry. No other screens.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: Prefs

    private val clockFormat = SimpleDateFormat("HH:mm:ss", Locale.US)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = Prefs(this)

        loadFieldsFromPrefs()
        wireButtons()
        observeState()
    }

    override fun onResume() {
        super.onResume()
        // The IP can change between sessions, and the user may have just toggled the
        // service in system settings, so re-render on every return to the screen.
        render()
    }

    // --- setup ---------------------------------------------------------------------------

    private fun loadFieldsFromPrefs() {
        val cfg = prefs.gestureConfig
        binding.etPort.setText(prefs.port.toString())
        binding.etSwipeX.setText(cfg.swipeXPct.toString())
        binding.etStartY.setText(cfg.nextStartYPct.toString())
        binding.etEndY.setText(cfg.nextEndYPct.toString())
        binding.etDuration.setText(cfg.swipeDurationMs.toString())
        binding.etTapX.setText(cfg.tapXPct.toString())
        binding.etTapY.setText(cfg.tapYPct.toString())
        binding.cbRequireForeground.isChecked = prefs.requireTargetForeground
        binding.tvToken.text = prefs.token
    }

    private fun wireButtons() {
        binding.btnEnableAccessibility.setOnClickListener {
            try {
                startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            } catch (e: ActivityNotFoundException) {
                toast("Could not open accessibility settings on this device")
            }
        }

        binding.btnToggleServer.setOnClickListener { toggleServer() }

        binding.btnCopyToken.setOnClickListener {
            copyToClipboard("Reel Remote token", prefs.token)
            toast(getString(R.string.copied))
        }

        binding.btnRegenerateToken.setOnClickListener {
            val fresh = prefs.regenerateToken()
            binding.tvToken.text = fresh
            RemoteState.log("Pairing token regenerated - update the laptop controller")
            toast("New token generated")
        }

        binding.cbRequireForeground.setOnCheckedChangeListener { _, checked ->
            prefs.requireTargetForeground = checked
        }

        binding.btnSaveGestures.setOnClickListener { saveGestures() }

        binding.btnResetGestures.setOnClickListener {
            prefs.gestureConfig = GestureConfig()
            loadFieldsFromPrefs()
            toast(getString(R.string.saved))
        }

        binding.btnClearLog.setOnClickListener { RemoteState.clearLog() }
    }

    private fun observeState() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch { RemoteState.status.collect { render() } }
                launch {
                    RemoteState.log.collect { lines ->
                        binding.tvLog.text =
                            if (lines.isEmpty()) "(nothing yet)" else lines.joinToString("\n")
                    }
                }
            }
        }
    }

    // --- actions -------------------------------------------------------------------------

    private fun toggleServer() {
        val service = ReelAccessibilityService.instance
        if (service == null) {
            toast(getString(R.string.needs_accessibility_first))
            return
        }

        if (RemoteState.status.value.serverRunning) {
            service.stopServer()
            return
        }

        // Apply the port field before binding the socket.
        val port = binding.etPort.text.toString().toIntOrNull()
        if (port == null || port !in 1024..65535) {
            toast("Port must be a number between 1024 and 65535")
            return
        }
        prefs.port = port
        binding.etPort.setText(prefs.port.toString())

        val error = service.startServer()
        if (error != null) toast(error)
    }

    private fun saveGestures() {
        val cfg = GestureConfig(
            swipeXPct = readInt(binding.etSwipeX, GestureConfig.DEFAULT_SWIPE_X),
            nextStartYPct = readInt(binding.etStartY, GestureConfig.DEFAULT_START_Y),
            nextEndYPct = readInt(binding.etEndY, GestureConfig.DEFAULT_END_Y),
            swipeDurationMs = readInt(binding.etDuration, GestureConfig.DEFAULT_DURATION),
            tapXPct = readInt(binding.etTapX, GestureConfig.DEFAULT_TAP_X),
            tapYPct = readInt(binding.etTapY, GestureConfig.DEFAULT_TAP_Y)
        ).sanitized()

        if (cfg.nextStartYPct == cfg.nextEndYPct) {
            toast("Start Y and End Y must differ")
            return
        }

        prefs.gestureConfig = cfg
        loadFieldsFromPrefs()
        toast(getString(R.string.saved))
    }

    private fun readInt(field: EditText, fallback: Int): Int =
        field.text.toString().trim().toIntOrNull() ?: fallback

    private fun copyToClipboard(label: String, value: String) {
        val clipboard = getSystemService(ClipboardManager::class.java) ?: return
        clipboard.setPrimaryClip(ClipData.newPlainText(label, value))
    }

    private fun toast(message: String) =
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()

    // --- rendering -----------------------------------------------------------------------

    private fun render() {
        val status = RemoteState.status.value
        val accessibilityOn =
            status.accessibilityConnected || NetUtils.isAccessibilityServiceEnabled(this)

        binding.tvAccessibilityStatus.apply {
            text = getString(
                if (accessibilityOn) R.string.status_accessibility_on
                else R.string.status_accessibility_off
            )
            setTextColor(
                ContextCompat.getColor(
                    this@MainActivity,
                    if (accessibilityOn) R.color.status_ok else R.color.status_bad
                )
            )
        }
        binding.btnEnableAccessibility.isEnabled = true

        binding.tvServerStatus.apply {
            text = getString(
                if (status.serverRunning) R.string.status_server_on
                else R.string.status_server_off
            )
            setTextColor(
                ContextCompat.getColor(
                    this@MainActivity,
                    if (status.serverRunning) R.color.status_ok else R.color.status_bad
                )
            )
        }

        binding.btnToggleServer.setText(
            if (status.serverRunning) R.string.btn_stop_server else R.string.btn_start_server
        )

        val ip = NetUtils.localIpv4()
        binding.tvEndpoint.text = when {
            ip == null -> getString(R.string.no_wifi)
            status.serverRunning -> "IP   $ip\nPort ${status.port}\nURL  http://$ip:${status.port}/command"
            else -> "IP   $ip\nPort ${prefs.port}  (server stopped)"
        }

        binding.tvClient.text = buildString {
            if (status.lastClientIp != null) {
                append("Last request: ${status.lastClientIp} at ")
                append(clockFormat.format(Date(status.lastClientAtMs)))
            } else {
                append("No laptop has connected yet")
            }
            if (status.lastCommand != null) {
                append("\nCommands served: ${status.commandsServed} (last: ${status.lastCommand})")
            }
            status.lastError?.let { append("\nError: $it") }
        }
    }
}
