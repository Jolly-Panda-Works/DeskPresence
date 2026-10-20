package com.jollypanda.deskpresence

import android.content.Context

/** The paired PC (address, token and the pinned certificate fingerprint). */
data class Pairing(
    val host: String,
    val port: Int,
    val token: String,
    val fingerprint: String,
    val deviceId: String,
    val pcName: String,
)

class Store(context: Context) {
    private val prefs = context.getSharedPreferences("deskpresence", Context.MODE_PRIVATE)

    fun load(): Pairing? {
        val token = prefs.getString("token", null) ?: return null
        return Pairing(
            host = prefs.getString("host", "") ?: "",
            port = prefs.getInt("port", Api.DEFAULT_PORT),
            token = token,
            fingerprint = prefs.getString("fingerprint", "") ?: "",
            deviceId = prefs.getString("device_id", "") ?: "",
            pcName = prefs.getString("pc_name", "") ?: "",
        )
    }

    fun save(p: Pairing) {
        prefs.edit()
            .putString("host", p.host).putInt("port", p.port).putString("token", p.token)
            .putString("fingerprint", p.fingerprint).putString("device_id", p.deviceId)
            .putString("pc_name", p.pcName)
            .apply()
    }

    /** The PC moved to another address (found again on the network). */
    fun updateAddress(host: String, port: Int) {
        prefs.edit().putString("host", host).putInt("port", port).apply()
    }

    fun clear() = prefs.edit().clear().apply()
}
