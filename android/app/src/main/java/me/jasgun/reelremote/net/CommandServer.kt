package me.jasgun.reelremote.net

import android.util.Log
import me.jasgun.reelremote.NetUtils
import org.json.JSONException
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.ArrayDeque
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicBoolean

/** Result of actually trying to perform a gesture. */
data class CommandOutcome(
    val ok: Boolean,
    val httpStatus: Int,
    val error: String? = null,
    val message: String? = null
)

/** Implemented by the accessibility service. */
interface CommandHandler {
    fun handleCommand(command: String): CommandOutcome

    /** Device-side facts for GET /ping (no screen content, ever). */
    fun deviceStatus(): JSONObject
}

/**
 * Minimal HTTP/1.1 server, hand-written so the app carries no networking library.
 *
 * Endpoints (both require the pairing token):
 *   GET  /ping      -> {"ok":true, "accessibility":..., "screen_on":..., ...}
 *   POST /command   -> body {"token":"...","command":"NEXT|PREVIOUS|PLAY_PAUSE"}
 *
 * The token may be sent either in the JSON body or in an `X-Auth-Token` header.
 */
class CommandServer(
    private val port: Int,
    private val tokenProvider: () -> String,
    private val handler: CommandHandler,
    private val listener: Listener
) {

    interface Listener {
        fun onLog(line: String)
        fun onClientSeen(ip: String)
        fun onServerStopped(reason: String?)
    }

    private val running = AtomicBoolean(false)
    private var serverSocket: ServerSocket? = null
    private var pool: ExecutorService? = null
    private var acceptThread: Thread? = null

    // --- rate limiting / abuse control -------------------------------------------------
    // java.util.ArrayDeque (not kotlin.collections.ArrayDeque) for peek/poll semantics.
    private val recentCommands: ArrayDeque<Long> = ArrayDeque()
    private val failedAuthByIp = HashMap<String, MutableList<Long>>()
    private val lock = Any()

    val isRunning: Boolean get() = running.get()

    /** Throws IOException (e.g. BindException when the port is taken). */
    @Throws(IOException::class)
    fun start() {
        if (!running.compareAndSet(false, true)) {
            throw IllegalStateException("Server already running")
        }
        val socket = ServerSocket()
        try {
            socket.reuseAddress = true
            socket.bind(InetSocketAddress(port), BACKLOG)
        } catch (e: IOException) {
            running.set(false)
            runCatching { socket.close() }
            throw e
        }
        serverSocket = socket
        pool = Executors.newFixedThreadPool(WORKER_THREADS)
        acceptThread = Thread({ acceptLoop(socket) }, "reelremote-accept").apply {
            isDaemon = true
            start()
        }
    }

    fun stop() {
        if (!running.compareAndSet(true, false)) return
        runCatching { serverSocket?.close() }
        serverSocket = null
        pool?.shutdownNow()
        pool = null
        acceptThread = null
        synchronized(lock) {
            recentCommands.clear()
            failedAuthByIp.clear()
        }
    }

    // -----------------------------------------------------------------------------------

    private fun acceptLoop(socket: ServerSocket) {
        while (running.get()) {
            val client = try {
                socket.accept()
            } catch (e: IOException) {
                if (running.get()) {
                    // Unexpected: the socket died while we still wanted it.
                    running.set(false)
                    listener.onServerStopped(e.message ?: "accept failed")
                }
                return
            }
            try {
                pool?.execute { handleClient(client) } ?: runCatching { client.close() }
            } catch (e: RejectedExecutionException) {
                runCatching { client.close() }
            }
        }
    }

    private fun handleClient(socket: Socket) {
        var ip = "?"
        try {
            socket.soTimeout = SOCKET_TIMEOUT_MS
            socket.tcpNoDelay = true

            val remote = (socket.remoteSocketAddress as? InetSocketAddress)?.address
            ip = remote?.hostAddress ?: "?"
            val out = socket.getOutputStream()

            // 1. Never serve anyone outside the local network, whatever the token says.
            if (remote == null || !NetUtils.isPrivateAddress(remote)) {
                respond(out, 403, errorJson("FORBIDDEN_NETWORK", "Only local-network clients are accepted"))
                listener.onLog("Rejected non-local client $ip")
                return
            }

            // 2. Throttle IPs that keep guessing the token.
            if (isAuthBanned(ip)) {
                respond(out, 429, errorJson("AUTH_THROTTLED", "Too many failed token attempts"))
                return
            }

            val input = BufferedInputStream(socket.getInputStream())
            val requestLine = readLine(input)
            if (requestLine.isNullOrBlank()) return

            val parts = requestLine.split(' ')
            if (parts.size < 2) {
                respond(out, 400, errorJson("BAD_REQUEST", "Malformed request line"))
                return
            }
            val method = parts[0].uppercase()
            val path = parts[1].substringBefore('?')

            val headers = readHeaders(input)
            if (headers == null) {
                respond(out, 431, errorJson("BAD_REQUEST", "Too many headers"))
                return
            }

            val contentLength = headers["content-length"]?.toIntOrNull() ?: 0
            if (contentLength > MAX_BODY_BYTES) {
                respond(out, 413, errorJson("PAYLOAD_TOO_LARGE", "Body limit is $MAX_BODY_BYTES bytes"))
                return
            }
            val body = if (contentLength > 0) readBody(input, contentLength) else ""

            route(out, method, path, headers, body, ip)
        } catch (e: Exception) {
            Log.w(TAG, "Client $ip failed: ${e.message}")
        } finally {
            runCatching { socket.close() }
        }
    }

    private fun route(
        out: OutputStream,
        method: String,
        path: String,
        headers: Map<String, String>,
        body: String,
        ip: String
    ) {
        val json: JSONObject? = if (body.isNotEmpty()) {
            try {
                JSONObject(body)
            } catch (e: JSONException) {
                respond(out, 400, errorJson("BAD_JSON", "Body is not valid JSON"))
                return
            }
        } else null

        val presented = headers["x-auth-token"] ?: json?.optString("token").orEmpty()
        if (!constantTimeEquals(presented, tokenProvider())) {
            noteAuthFailure(ip)
            respond(out, 401, errorJson("UNAUTHORIZED", "Bad or missing pairing token"))
            listener.onLog("Rejected bad token from $ip")
            return
        }
        clearAuthFailures(ip)
        listener.onClientSeen(ip)

        when {
            path == "/ping" && (method == "GET" || method == "POST") -> {
                val payload = handler.deviceStatus()
                payload.put("ok", true)
                payload.put("app", APP_ID)
                payload.put("protocol", PROTOCOL_VERSION)
                respond(out, 200, payload)
            }

            path == "/command" && method == "POST" -> {
                if (json == null) {
                    respond(out, 400, errorJson("BAD_REQUEST", "POST /command requires a JSON body"))
                    return
                }
                val command = json.optString("command").trim().uppercase()
                if (command !in ALLOWED_COMMANDS) {
                    respond(
                        out, 400,
                        errorJson("UNKNOWN_COMMAND", "Allowed: ${ALLOWED_COMMANDS.joinToString(", ")}")
                    )
                    return
                }
                val wait = rateLimitDelayMs()
                if (wait > 0) {
                    respond(
                        out, 429,
                        errorJson("RATE_LIMITED", "Slow down").put("retry_after_ms", wait)
                    )
                    return
                }
                val outcome = handler.handleCommand(command)
                val payload = JSONObject()
                    .put("ok", outcome.ok)
                    .put("command", command)
                if (!outcome.ok) {
                    payload.put("error", outcome.error ?: "FAILED")
                    payload.put("message", outcome.message ?: "")
                }
                respond(out, outcome.httpStatus, payload)
            }

            path == "/command" -> respond(out, 405, errorJson("METHOD_NOT_ALLOWED", "Use POST"))

            else -> respond(out, 404, errorJson("NOT_FOUND", "Unknown endpoint"))
        }
    }

    // --- rate limiting ------------------------------------------------------------------

    /** Returns 0 when the command may run, otherwise how long the client should wait. */
    private fun rateLimitDelayMs(): Long = synchronized(lock) {
        val now = System.currentTimeMillis()
        // Drop everything that has aged out of the rolling window.
        while (true) {
            val oldest: Long = recentCommands.peekFirst() ?: break
            if (now - oldest <= WINDOW_MS) break
            recentCommands.pollFirst()
        }
        val last: Long? = recentCommands.peekLast()
        if (last != null && now - last < MIN_INTERVAL_MS) {
            return MIN_INTERVAL_MS - (now - last)
        }
        if (recentCommands.size >= MAX_PER_WINDOW) {
            val oldest: Long? = recentCommands.peekFirst()
            if (oldest != null) return WINDOW_MS - (now - oldest)
        }
        recentCommands.addLast(now)
        0L
    }

    private fun noteAuthFailure(ip: String) {
        synchronized(lock) {
            val now = System.currentTimeMillis()
            val list = failedAuthByIp.getOrPut(ip) { mutableListOf() }
            list.removeAll { now - it > AUTH_BAN_WINDOW_MS }
            list.add(now)
        }
    }

    private fun clearAuthFailures(ip: String) {
        synchronized(lock) { failedAuthByIp.remove(ip) }
    }

    private fun isAuthBanned(ip: String): Boolean = synchronized(lock) {
        val now = System.currentTimeMillis()
        val list = failedAuthByIp[ip] ?: return false
        list.removeAll { now - it > AUTH_BAN_WINDOW_MS }
        list.size >= MAX_AUTH_FAILURES
    }

    // --- raw HTTP plumbing --------------------------------------------------------------

    /** Reads one CRLF-terminated line, capped so a hostile client cannot exhaust memory. */
    @Throws(IOException::class)
    private fun readLine(input: InputStream): String? {
        val buffer = ByteArrayOutputStream(128)
        while (true) {
            val b = input.read()
            if (b == -1) return if (buffer.size() == 0) null else buffer.toString("UTF-8")
            if (b == '\n'.code) break
            if (b != '\r'.code) buffer.write(b)
            if (buffer.size() > MAX_LINE_BYTES) throw IOException("Header line too long")
        }
        return buffer.toString("UTF-8")
    }

    /** Lower-cased header names. Returns null if the client sends absurdly many. */
    @Throws(IOException::class)
    private fun readHeaders(input: InputStream): Map<String, String>? {
        val headers = HashMap<String, String>()
        var count = 0
        while (true) {
            val line = readLine(input) ?: break
            if (line.isEmpty()) break
            if (++count > MAX_HEADERS) return null
            val idx = line.indexOf(':')
            if (idx <= 0) continue
            headers[line.substring(0, idx).trim().lowercase()] = line.substring(idx + 1).trim()
        }
        return headers
    }

    @Throws(IOException::class)
    private fun readBody(input: InputStream, length: Int): String {
        val bytes = ByteArray(length)
        var read = 0
        while (read < length) {
            val n = input.read(bytes, read, length - read)
            if (n == -1) break
            read += n
        }
        return String(bytes, 0, read, StandardCharsets.UTF_8)
    }

    private fun respond(out: OutputStream, status: Int, body: JSONObject) {
        val payload = body.toString().toByteArray(StandardCharsets.UTF_8)
        val head = buildString {
            append("HTTP/1.1 ").append(status).append(' ').append(reasonPhrase(status)).append("\r\n")
            append("Content-Type: application/json; charset=utf-8\r\n")
            append("Content-Length: ").append(payload.size).append("\r\n")
            append("Cache-Control: no-store\r\n")
            append("Connection: close\r\n")
            append("\r\n")
        }
        out.write(head.toByteArray(StandardCharsets.US_ASCII))
        out.write(payload)
        out.flush()
    }

    private fun errorJson(code: String, message: String): JSONObject =
        JSONObject().put("ok", false).put("error", code).put("message", message)

    private fun reasonPhrase(status: Int): String = when (status) {
        200 -> "OK"
        400 -> "Bad Request"
        401 -> "Unauthorized"
        403 -> "Forbidden"
        404 -> "Not Found"
        405 -> "Method Not Allowed"
        409 -> "Conflict"
        413 -> "Payload Too Large"
        429 -> "Too Many Requests"
        431 -> "Request Header Fields Too Large"
        503 -> "Service Unavailable"
        else -> "Error"
    }

    /** Length-leaking but value-safe comparison; good enough for a 16-char LAN token. */
    private fun constantTimeEquals(a: String, b: String): Boolean {
        if (a.length != b.length) return false
        var diff = 0
        for (i in a.indices) diff = diff or (a[i].code xor b[i].code)
        return diff == 0
    }

    companion object {
        private const val TAG = "ReelRemoteServer"

        const val APP_ID = "reelremote"
        const val PROTOCOL_VERSION = 1

        val ALLOWED_COMMANDS = setOf("NEXT", "PREVIOUS", "PLAY_PAUSE")

        private const val BACKLOG = 16
        private const val WORKER_THREADS = 4
        private const val SOCKET_TIMEOUT_MS = 5_000
        private const val MAX_BODY_BYTES = 4_096
        private const val MAX_LINE_BYTES = 4_096
        private const val MAX_HEADERS = 40

        private const val MIN_INTERVAL_MS = 150L
        private const val WINDOW_MS = 5_000L
        private const val MAX_PER_WINDOW = 25

        private const val MAX_AUTH_FAILURES = 10
        private const val AUTH_BAN_WINDOW_MS = 60_000L
    }
}
