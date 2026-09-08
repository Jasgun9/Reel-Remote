package me.jasgun.reelremote

import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.text.TextUtils
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface

object NetUtils {

    /**
     * Best-effort local IPv4 address on the Wi-Fi / LAN interface.
     * Returns null when the phone is not on a local network.
     */
    fun localIpv4(): String? {
        return try {
            val candidates = mutableListOf<Pair<String, String>>() // interface name to address
            for (nif in NetworkInterface.getNetworkInterfaces()) {
                if (!nif.isUp || nif.isLoopback) continue
                for (addr in nif.inetAddresses) {
                    if (addr !is Inet4Address) continue
                    if (addr.isLoopbackAddress) continue
                    val host = addr.hostAddress ?: continue
                    candidates.add(nif.name to host)
                }
            }
            // Prefer wlan* (normal Wi-Fi), then any other private address.
            candidates.firstOrNull { it.first.startsWith("wlan") }?.second
                ?: candidates.firstOrNull { isPrivateIpv4(it.second) }?.second
                ?: candidates.firstOrNull()?.second
        } catch (t: Throwable) {
            null
        }
    }

    /** RFC1918 + link-local + loopback. Used to reject off-LAN clients. */
    fun isPrivateAddress(address: InetAddress): Boolean =
        address.isLoopbackAddress ||
            address.isSiteLocalAddress ||
            address.isLinkLocalAddress ||
            address.isAnyLocalAddress

    private fun isPrivateIpv4(host: String): Boolean = try {
        isPrivateAddress(InetAddress.getByName(host))
    } catch (t: Throwable) {
        false
    }

    /** True when the user has switched our accessibility service on in system settings. */
    fun isAccessibilityServiceEnabled(context: Context): Boolean {
        val expected = ComponentName(context, ReelAccessibilityService::class.java)
        val enabled = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false

        val splitter = TextUtils.SimpleStringSplitter(':')
        splitter.setString(enabled)
        for (entry in splitter) {
            val component = ComponentName.unflattenFromString(entry) ?: continue
            if (component == expected) return true
        }
        return false
    }
}
