package com.example.reelremote

import android.content.Context
import android.content.SharedPreferences
import java.security.SecureRandom

/**
 * Tiny SharedPreferences wrapper. Holds the pairing token, the port, the gesture
 * geometry and two behaviour switches. Nothing here ever leaves the device except
 * the token, which the user types into the laptop controller by hand.
 */
class Prefs(context: Context) {

    private val sp: SharedPreferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** Created on first read and kept until the user regenerates it. */
    val token: String
        get() {
            sp.getString(KEY_TOKEN, null)?.let { if (it.length == TOKEN_LENGTH) return it }
            return regenerateToken()
        }

    fun regenerateToken(): String {
        val fresh = generateToken()
        sp.edit().putString(KEY_TOKEN, fresh).apply()
        return fresh
    }

    var port: Int
        get() = sp.getInt(KEY_PORT, DEFAULT_PORT).let { if (it in 1024..65535) it else DEFAULT_PORT }
        set(value) = sp.edit().putInt(KEY_PORT, value.coerceIn(1024, 65535)).apply()

    /** Remembers whether the user had the server switched on, so it can come back by itself. */
    var serverEnabled: Boolean
        get() = sp.getBoolean(KEY_SERVER_ENABLED, false)
        set(value) = sp.edit().putBoolean(KEY_SERVER_ENABLED, value).apply()

    /** When true, gestures are refused unless [targetPackage] is the foreground app. */
    var requireTargetForeground: Boolean
        get() = sp.getBoolean(KEY_REQUIRE_FOREGROUND, true)
        set(value) = sp.edit().putBoolean(KEY_REQUIRE_FOREGROUND, value).apply()

    var targetPackage: String
        get() = sp.getString(KEY_TARGET_PACKAGE, DEFAULT_TARGET_PACKAGE) ?: DEFAULT_TARGET_PACKAGE
        set(value) = sp.edit().putString(KEY_TARGET_PACKAGE, value.trim()).apply()

    var gestureConfig: GestureConfig
        get() = GestureConfig(
            swipeXPct = sp.getInt(KEY_SWIPE_X, GestureConfig.DEFAULT_SWIPE_X),
            nextStartYPct = sp.getInt(KEY_START_Y, GestureConfig.DEFAULT_START_Y),
            nextEndYPct = sp.getInt(KEY_END_Y, GestureConfig.DEFAULT_END_Y),
            swipeDurationMs = sp.getInt(KEY_DURATION, GestureConfig.DEFAULT_DURATION),
            tapXPct = sp.getInt(KEY_TAP_X, GestureConfig.DEFAULT_TAP_X),
            tapYPct = sp.getInt(KEY_TAP_Y, GestureConfig.DEFAULT_TAP_Y)
        ).sanitized()
        set(value) {
            val c = value.sanitized()
            sp.edit()
                .putInt(KEY_SWIPE_X, c.swipeXPct)
                .putInt(KEY_START_Y, c.nextStartYPct)
                .putInt(KEY_END_Y, c.nextEndYPct)
                .putInt(KEY_DURATION, c.swipeDurationMs)
                .putInt(KEY_TAP_X, c.tapXPct)
                .putInt(KEY_TAP_Y, c.tapYPct)
                .apply()
        }

    companion object {
        private const val FILE = "reelremote_prefs"
        private const val KEY_TOKEN = "token"
        private const val KEY_PORT = "port"
        private const val KEY_SERVER_ENABLED = "server_enabled"
        private const val KEY_REQUIRE_FOREGROUND = "require_foreground"
        private const val KEY_TARGET_PACKAGE = "target_package"
        private const val KEY_SWIPE_X = "swipe_x"
        private const val KEY_START_Y = "start_y"
        private const val KEY_END_Y = "end_y"
        private const val KEY_DURATION = "duration"
        private const val KEY_TAP_X = "tap_x"
        private const val KEY_TAP_Y = "tap_y"

        const val DEFAULT_PORT = 8787
        const val DEFAULT_TARGET_PACKAGE = "com.instagram.android"

        private const val TOKEN_LENGTH = 16

        // No 0/O/1/I - the token gets read off a phone screen and typed on a laptop.
        private const val ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

        private fun generateToken(): String {
            val random = SecureRandom()
            val sb = StringBuilder(TOKEN_LENGTH)
            repeat(TOKEN_LENGTH) { sb.append(ALPHABET[random.nextInt(ALPHABET.length)]) }
            return sb.toString()
        }
    }
}
