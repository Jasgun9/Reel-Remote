package com.example.reelremote

/**
 * Gesture geometry expressed as percentages of the current screen size, so the same
 * numbers work on any resolution / aspect ratio.
 *
 * NEXT      : swipe from (swipeXPct, nextStartYPct) up to (swipeXPct, nextEndYPct)
 * PREVIOUS  : the exact opposite swipe
 * PLAY_PAUSE: a tap at (tapXPct, tapYPct)
 */
data class GestureConfig(
    val swipeXPct: Int = DEFAULT_SWIPE_X,
    val nextStartYPct: Int = DEFAULT_START_Y,
    val nextEndYPct: Int = DEFAULT_END_Y,
    val swipeDurationMs: Int = DEFAULT_DURATION,
    val tapXPct: Int = DEFAULT_TAP_X,
    val tapYPct: Int = DEFAULT_TAP_Y
) {
    /** Clamp everything into a range that cannot produce an invalid GestureDescription. */
    fun sanitized(): GestureConfig = GestureConfig(
        swipeXPct = swipeXPct.coerceIn(2, 98),
        nextStartYPct = nextStartYPct.coerceIn(2, 98),
        nextEndYPct = nextEndYPct.coerceIn(2, 98),
        swipeDurationMs = swipeDurationMs.coerceIn(50, 1000),
        tapXPct = tapXPct.coerceIn(2, 98),
        tapYPct = tapYPct.coerceIn(2, 98)
    )

    companion object {
        const val DEFAULT_SWIPE_X = 50
        const val DEFAULT_START_Y = 75
        const val DEFAULT_END_Y = 25
        const val DEFAULT_DURATION = 220
        const val DEFAULT_TAP_X = 50
        const val DEFAULT_TAP_Y = 50
    }
}
