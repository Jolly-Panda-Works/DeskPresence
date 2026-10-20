package com.jollypanda.deskpresence

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.security.KeyPair

/** The paired PC: local address, token, pinned certificate and the end-to-end key for the relay. */
data class Pairing(
    val host: String,
    val port: Int,
    val token: String,
    val fingerprint: String,      // TLS certificate (local network)
    val deviceId: String,
    val pcName: String,
    val pcPub: String = "",       // PC's identity key (end-to-end)
    val hub: String = "",         // PC's id on the relay
    val relay: String = "",       // https://relay.example.com ("" = local network only)
)

/** Another phone this phone shares its status with. */
data class Contact(val id: String, val name: String, val pub: String)

/** What this phone tells its contacts. */
data class MyStatus(val preset: String = "available", val text: String = "")

class Store(context: Context) {
    private val prefs = context.getSharedPreferences("deskpresence", Context.MODE_PRIVATE)

    // ---------------------------------------------------------------- this phone's key pair
    fun identity(): KeyPair {
        val pub = prefs.getString("id_pub", null)
        val priv = prefs.getString("id_priv", null)
        if (pub != null && priv != null) return KeyPair(Crypto.loadPublic(pub), Crypto.loadPrivate(priv))
        val pair = Crypto.newKeyPair()
        prefs.edit().putString("id_pub", Crypto.publicB64(pair.public)).putString("id_priv", Crypto.privateB64(pair.private))
            .apply()
        return pair
    }

    // ---------------------------------------------------------------- the PC
    fun load(): Pairing? {
        val token = prefs.getString("token", null) ?: return null
        return Pairing(
            host = prefs.getString("host", "") ?: "",
            port = prefs.getInt("port", Api.DEFAULT_PORT),
            token = token,
            fingerprint = prefs.getString("fingerprint", "") ?: "",
            deviceId = prefs.getString("device_id", "") ?: "",
            pcName = prefs.getString("pc_name", "") ?: "",
            pcPub = prefs.getString("pc_pub", "") ?: "",
            hub = prefs.getString("hub", "") ?: "",
            relay = prefs.getString("relay", "") ?: "",
        )
    }

    fun save(p: Pairing) {
        prefs.edit()
            .putString("host", p.host).putInt("port", p.port).putString("token", p.token)
            .putString("fingerprint", p.fingerprint).putString("device_id", p.deviceId)
            .putString("pc_name", p.pcName).putString("pc_pub", p.pcPub).putString("hub", p.hub)
            .putString("relay", p.relay)
            .apply()
        if (p.relay.isNotBlank() && relayUrl().isBlank()) setRelayUrl(p.relay)
    }

    /** The PC moved to another address (found again on the network). */
    fun updateAddress(host: String, port: Int) {
        prefs.edit().putString("host", host).putInt("port", port).apply()
    }

    fun forgetPc() {
        prefs.edit().apply {
            listOf("host", "port", "token", "fingerprint", "device_id", "pc_name", "pc_pub", "hub", "relay")
                .forEach { remove(it) }
        }.apply()
    }

    // ---------------------------------------------------------------- relay account (phone <-> phone)
    fun relayUrl(): String = prefs.getString("relay_url", "") ?: ""
    fun setRelayUrl(url: String) = prefs.edit().putString("relay_url", url.trim().trimEnd('/')).apply()

    fun relayAccount(): Pair<String, String>? {
        val id = prefs.getString("relay_phone_id", null) ?: return null
        val secret = prefs.getString("relay_secret", null) ?: return null
        return id to secret
    }

    fun setRelayAccount(id: String, secret: String) =
        prefs.edit().putString("relay_phone_id", id).putString("relay_secret", secret).apply()

    fun contacts(): List<Contact> {
        val arr = JSONArray(prefs.getString("contacts", "[]"))
        return (0 until arr.length()).map {
            val o = arr.getJSONObject(it)
            Contact(o.getString("id"), o.optString("name"), o.getString("pub"))
        }
    }

    private fun saveContacts(list: List<Contact>) {
        val arr = JSONArray()
        list.forEach { arr.put(JSONObject().put("id", it.id).put("name", it.name).put("pub", it.pub)) }
        prefs.edit().putString("contacts", arr.toString()).apply()
    }

    fun addContact(c: Contact) = saveContacts(contacts().filter { it.id != c.id } + c)
    fun removeContact(id: String) = saveContacts(contacts().filter { it.id != id })
    fun renameContact(id: String, name: String) =
        saveContacts(contacts().map { if (it.id == id) it.copy(name = name) else it })

    fun myName(default: String): String = prefs.getString("my_name", null) ?: default
    fun setMyName(name: String) = prefs.edit().putString("my_name", name).apply()

    fun myStatus() = MyStatus(prefs.getString("status_preset", "available") ?: "available",
        prefs.getString("status_text", "") ?: "")

    fun setMyStatus(s: MyStatus) =
        prefs.edit().putString("status_preset", s.preset).putString("status_text", s.text).apply()
}
