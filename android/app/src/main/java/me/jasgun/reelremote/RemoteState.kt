package me.jasgun.reelremote

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Shared, process-wide state between the accessibility service (which owns the server)
 * and MainActivity (which only displays it). Both live in the same process, so a plain
 * object with StateFlows is enough - no IPC, no broadcasts.
 */
object RemoteState {

    data class Status(
        val accessibilityConnected: Boolean = false,
        val serverRunning: Boolean = false,
        val port: Int = Prefs.DEFAULT_PORT,
        val lastError: String? = null,
        val lastClientIp: String? = null,
        val lastClientAtMs: Long = 0L,
        val lastCommand: String? = null,
        val commandsServed: Int = 0
    )

    private val _status = MutableStateFlow(Status())
    val status: StateFlow<Status> = _status

    private val _log = MutableStateFlow<List<String>>(emptyList())
    val log: StateFlow<List<String>> = _log

    private const val MAX_LOG_LINES = 60
    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.US)

    fun setAccessibilityConnected(connected: Boolean) =
        _status.update { it.copy(accessibilityConnected = connected) }

    fun setServerRunning(running: Boolean, port: Int) =
        _status.update { it.copy(serverRunning = running, port = port, lastError = null) }

    fun setError(message: String?) = _status.update { it.copy(lastError = message) }

    fun noteClient(ip: String) =
        _status.update { it.copy(lastClientIp = ip, lastClientAtMs = System.currentTimeMillis()) }

    fun noteCommand(command: String) = _status.update {
        it.copy(lastCommand = command, commandsServed = it.commandsServed + 1)
    }

    fun log(line: String) = _log.update { current ->
        val stamped = "${timeFormat.format(Date())}  $line"
        (current + stamped).takeLast(MAX_LOG_LINES)
    }

    fun clearLog() {
        _log.value = emptyList()
    }
}
