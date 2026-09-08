package me.jasgun.reelremote

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.app.KeyguardManager
import android.content.Intent
import android.graphics.Path
import android.graphics.Point
import android.hardware.display.DisplayManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.util.DisplayMetrics
import android.util.Log
import android.view.Display
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import me.jasgun.reelremote.net.CommandHandler
import me.jasgun.reelremote.net.CommandOutcome
import me.jasgun.reelremote.net.CommandServer
import org.json.JSONObject
import java.io.IOException
import java.net.BindException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Owns both the gesture dispatching and the local command server.
 *
 * Hosting the server here (rather than in a foreground service) is deliberate: an enabled
 * accessibility service is already a long-lived, system-bound process, so the listener keeps
 * running while Instagram is in the foreground without a persistent notification or a
 * foreground-service type. If the service is disabled, the server is useless anyway, so the
 * two lifecycles are correctly coupled.
 *
 * This service never reads screen content (canRetrieveWindowContent="false"). The only thing
 * it observes is the package name of whatever window just came to the front.
 */
class ReelAccessibilityService : AccessibilityService(), CommandHandler {

    private val mainHandler = Handler(Looper.getMainLooper())
    private lateinit var prefs: Prefs

    @Volatile
    private var foregroundPackage: String? = null

    private var server: CommandServer? = null

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        RemoteState.setAccessibilityConnected(true)
        RemoteState.log("Accessibility service connected")
        // Bring the listener back automatically if the user had it switched on.
        if (prefs.serverEnabled && server?.isRunning != true) {
            startServer()
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        if (event.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return
        val pkg = event.packageName?.toString() ?: return
        if (pkg.isNotEmpty() && pkg != foregroundPackage) {
            foregroundPackage = pkg
        }
    }

    override fun onInterrupt() {
        // Nothing to interrupt: this service produces no continuous feedback.
    }

    override fun onUnbind(intent: Intent?): Boolean {
        shutdownServer("accessibility service disabled")
        RemoteState.setAccessibilityConnected(false)
        RemoteState.log("Accessibility service disconnected")
        instance = null
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        shutdownServer(null)
        RemoteState.setAccessibilityConnected(false)
        instance = null
        super.onDestroy()
    }

    // --- server control (called from MainActivity) ------------------------------------

    /** Returns null on success, or a human-readable error message. */
    fun startServer(): String? {
        server?.let { if (it.isRunning) return null }
        val port = prefs.port
        val candidate = CommandServer(
            port = port,
            tokenProvider = { prefs.token },
            handler = this,
            listener = serverListener
        )
        return try {
            candidate.start()
            server = candidate
            prefs.serverEnabled = true
            RemoteState.setServerRunning(true, port)
            RemoteState.log("Server listening on port $port")
            null
        } catch (e: BindException) {
            val msg = "Port $port is already in use. Pick a different port."
            RemoteState.setError(msg)
            RemoteState.log(msg)
            msg
        } catch (e: IOException) {
            val msg = "Could not start server: ${e.message ?: "I/O error"}"
            RemoteState.setError(msg)
            RemoteState.log(msg)
            msg
        } catch (e: IllegalStateException) {
            null // already running
        }
    }

    fun stopServer() {
        prefs.serverEnabled = false
        shutdownServer("stopped by user")
    }

    private fun shutdownServer(reason: String?) {
        val current = server ?: return
        current.stop()
        server = null
        RemoteState.setServerRunning(false, prefs.port)
        RemoteState.log("Server stopped${if (reason != null) " ($reason)" else ""}")
    }

    private val serverListener = object : CommandServer.Listener {
        override fun onLog(line: String) = RemoteState.log(line)

        override fun onClientSeen(ip: String) = RemoteState.noteClient(ip)

        override fun onServerStopped(reason: String?) {
            server = null
            RemoteState.setServerRunning(false, prefs.port)
            RemoteState.setError(reason)
            RemoteState.log("Server stopped unexpectedly${if (reason != null) ": $reason" else ""}")
        }
    }

    // --- CommandHandler ----------------------------------------------------------------

    override fun deviceStatus(): JSONObject {
        val fg = foregroundPackage
        val target = prefs.targetPackage
        return JSONObject()
            .put("accessibility", true)
            .put("screen_on", isScreenInteractive())
            .put("locked", isKeyguardLocked())
            .put("foreground_package", fg ?: JSONObject.NULL)
            .put("target_package", target)
            .put("target_foreground", fg != null && fg == target)
            .put("require_target_foreground", prefs.requireTargetForeground)
            .put("port", prefs.port)
    }

    override fun handleCommand(command: String): CommandOutcome {
        if (!isScreenInteractive()) {
            return CommandOutcome(false, 409, "SCREEN_OFF", "The phone screen is off")
        }
        if (isKeyguardLocked()) {
            return CommandOutcome(false, 409, "SCREEN_LOCKED", "The phone is locked")
        }

        if (prefs.requireTargetForeground) {
            val target = prefs.targetPackage
            val fg = foregroundPackage
            if (fg == null) {
                return CommandOutcome(
                    false, 409, "FOREGROUND_UNKNOWN",
                    "Foreground app not detected yet - switch apps once on the phone"
                )
            }
            if (fg != target) {
                return CommandOutcome(
                    false, 409, "TARGET_NOT_FOREGROUND",
                    "Foreground app is $fg, expected $target"
                )
            }
        }

        val size = screenSize() ?: return CommandOutcome(
            false, 500, "NO_SCREEN_METRICS", "Could not read screen dimensions"
        )
        val cfg = prefs.gestureConfig

        val dispatched = when (command) {
            CMD_NEXT -> swipe(size, cfg, cfg.nextStartYPct, cfg.nextEndYPct)
            CMD_PREVIOUS -> swipe(size, cfg, cfg.nextEndYPct, cfg.nextStartYPct)
            CMD_PLAY_PAUSE -> tap(size, cfg)
            else -> return CommandOutcome(false, 400, "UNKNOWN_COMMAND", "Unsupported: $command")
        }

        return if (dispatched) {
            RemoteState.noteCommand(command)
            RemoteState.log("$command performed")
            CommandOutcome(true, 200)
        } else {
            RemoteState.log("$command failed to dispatch")
            CommandOutcome(
                false, 409, "GESTURE_FAILED",
                "The system rejected or cancelled the gesture"
            )
        }
    }

    // --- gestures -----------------------------------------------------------------------

    private fun swipe(size: Point, cfg: GestureConfig, fromYPct: Int, toYPct: Int): Boolean {
        val x = size.x * cfg.swipeXPct / 100f
        val yFrom = size.y * fromYPct / 100f
        val yTo = size.y * toYPct / 100f

        val path = Path().apply {
            moveTo(x, yFrom)
            lineTo(x, yTo)
        }
        val durationMs = cfg.swipeDurationMs.toLong()
        val stroke = GestureDescription.StrokeDescription(path, 0L, durationMs)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        return dispatchAndAwait(gesture, durationMs)
    }

    private fun tap(size: Point, cfg: GestureConfig): Boolean {
        val x = size.x * cfg.tapXPct / 100f
        val y = size.y * cfg.tapYPct / 100f
        val path = Path().apply {
            moveTo(x, y)
            // A zero-length path is invalid on some builds; a sub-pixel move keeps it a tap.
            lineTo(x + 1f, y)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0L, TAP_DURATION_MS)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        return dispatchAndAwait(gesture, TAP_DURATION_MS)
    }

    /**
     * dispatchGesture() is asynchronous. The server runs on a worker thread, so we post the
     * dispatch to the main looper and block the worker until the system reports the result.
     */
    private fun dispatchAndAwait(gesture: GestureDescription, durationMs: Long): Boolean {
        val latch = CountDownLatch(1)
        val accepted = AtomicBoolean(false)
        val completed = AtomicBoolean(false)

        val callback = object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                completed.set(true)
                latch.countDown()
            }

            override fun onCancelled(gestureDescription: GestureDescription?) {
                completed.set(false)
                latch.countDown()
            }
        }

        mainHandler.post {
            val ok = try {
                dispatchGesture(gesture, callback, null)
            } catch (t: Throwable) {
                Log.w(TAG, "dispatchGesture threw: ${t.message}")
                false
            }
            accepted.set(ok)
            if (!ok) latch.countDown()
        }

        val finished = latch.await(durationMs + GESTURE_SLACK_MS, TimeUnit.MILLISECONDS)
        return finished && accepted.get() && completed.get()
    }

    // --- device facts --------------------------------------------------------------------

    /** Full physical screen size, handling the API 30 window-metrics change. */
    private fun screenSize(): Point? {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                val displayManager = getSystemService(DisplayManager::class.java)
                val display = displayManager?.getDisplay(Display.DEFAULT_DISPLAY)
                if (display != null) {
                    val windowContext = createDisplayContext(display)
                        .createWindowContext(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, null)
                    val wm = windowContext.getSystemService(WindowManager::class.java)
                    val bounds = wm?.currentWindowMetrics?.bounds
                    if (bounds != null && bounds.width() > 0 && bounds.height() > 0) {
                        return Point(bounds.width(), bounds.height())
                    }
                }
            } catch (t: Throwable) {
                Log.w(TAG, "currentWindowMetrics unavailable, falling back: ${t.message}")
            }
        }
        // Fallback for API 26-29, and for any device where the window context path fails.
        return try {
            val displayManager = getSystemService(DisplayManager::class.java) ?: return null
            val display = displayManager.getDisplay(Display.DEFAULT_DISPLAY) ?: return null
            val metrics = DisplayMetrics()
            @Suppress("DEPRECATION")
            display.getRealMetrics(metrics)
            if (metrics.widthPixels > 0 && metrics.heightPixels > 0) {
                Point(metrics.widthPixels, metrics.heightPixels)
            } else null
        } catch (t: Throwable) {
            null
        }
    }

    private fun isScreenInteractive(): Boolean =
        getSystemService(PowerManager::class.java)?.isInteractive ?: true

    private fun isKeyguardLocked(): Boolean =
        getSystemService(KeyguardManager::class.java)?.isKeyguardLocked ?: false

    companion object {
        private const val TAG = "ReelRemoteA11y"

        const val CMD_NEXT = "NEXT"
        const val CMD_PREVIOUS = "PREVIOUS"
        const val CMD_PLAY_PAUSE = "PLAY_PAUSE"

        private const val TAP_DURATION_MS = 60L
        private const val GESTURE_SLACK_MS = 1_500L

        /** Set while the service is connected; MainActivity uses it to start/stop the server. */
        @Volatile
        var instance: ReelAccessibilityService? = null
            private set
    }
}
