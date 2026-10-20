package com.jollypanda.deskpresence

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.AudioManager
import android.net.Uri
import android.os.BatteryManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.DataInputStream
import java.security.KeyPair
import java.util.concurrent.TimeUnit

private val JSON = "application/json; charset=utf-8".toMediaType()

/** Plain HTTPS client for the relay (it has a normal Let's Encrypt certificate). */
private val relayHttp: OkHttpClient by lazy {
    OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build()
}

private fun Request.Builder.json(body: JSONObject) = post(body.toString().toRequestBody(JSON))

private suspend fun relayRequest(req: Request): JSONObject = withContext(Dispatchers.IO) {
    relayHttp.newCall(req).execute().use { resp ->
        val json = runCatching { JSONObject(resp.body?.string().orEmpty()) }.getOrDefault(JSONObject())
        if (!resp.isSuccessful) throw ApiException(resp.code, json.optString("error", "http_${resp.code}"))
        json
    }
}

// ---------------------------------------------------------------- links and QR codes
sealed class DeskLink {
    /** Pair with a PC: code, PC key fingerprint, TLS fingerprint, local address, relay hub / url. */
    data class Pc(val code: String, val keyFp: String, val tlsFp: String, val lan: String, val hub: String,
                  val relay: String) : DeskLink()

    /** Connect to another phone. */
    data class Invite(val code: String, val keyFp: String, val relay: String) : DeskLink()
}

/**
 * Understands https://relay/p/#c=..&k=.. (PC), https://relay/i/#c=..&k=.. (phone) and the
 * deskpresence://pair?... / deskpresence://invite?... links the landing page opens.
 */
fun parseLink(text: String): DeskLink? {
    val uri = runCatching { Uri.parse(text.trim()) }.getOrNull() ?: return null
    val params: Map<String, String>
    val kind: String
    val relay: String
    when (uri.scheme) {
        "deskpresence" -> {
            kind = uri.host ?: return null
            params = uri.queryParameterNames.associateWith { uri.getQueryParameter(it).orEmpty() }
            relay = params["r"]?.takeIf { it.isNotBlank() }?.let { if (it.startsWith("http")) it else "https://$it" } ?: ""
        }
        "https", "http" -> {
            kind = when {
                uri.path?.startsWith("/p") == true -> "pair"
                uri.path?.startsWith("/i") == true -> "invite"
                else -> return null
            }
            params = Uri.parse("x://x?" + (uri.encodedFragment ?: "")).let { f ->
                f.queryParameterNames.associateWith { f.getQueryParameter(it).orEmpty() }
            }
            relay = "${uri.scheme}://${uri.encodedAuthority}"
        }
        else -> return null
    }
    val code = params["c"].orEmpty()
    if (code.length != 6) return null
    return when (kind) {
        "pair" -> DeskLink.Pc(code, params["k"].orEmpty(), params["f"].orEmpty(), params["l"].orEmpty(),
            params["h"].orEmpty(), if (params["h"].isNullOrBlank()) "" else relay)
        "invite" -> DeskLink.Invite(code, params["k"].orEmpty(), relay)
        else -> null
    }
}

// ---------------------------------------------------------------- pairing with a PC
/**
 * Pairs over the local network when the PC is reachable there, otherwise through the relay.
 * The public key the PC answers with must match the fingerprint from the QR code / link.
 */
suspend fun pairWithPc(link: DeskLink.Pc, name: String, keys: KeyPair): Pairing {
    val pub = Crypto.publicB64(keys.public)
    var reply: JSONObject? = null
    var tlsSeen = ""
    var host = ""
    var port = Api.DEFAULT_PORT
    if (link.lan.isNotBlank()) {
        host = link.lan.substringBefore(':')
        port = link.lan.substringAfter(':', "").toIntOrNull() ?: Api.DEFAULT_PORT
        runCatching {
            withTimeout(5000) {
                val api = Api(host, port, pin = null, token = null)
                val r = api.pairRaw(link.code, name, pub)
                tlsSeen = api.seenFingerprint.orEmpty()
                r
            }
        }.onSuccess { reply = it }.onFailure { e -> if (e is ApiException && e.code == 403) throw e }
        if (reply != null && link.tlsFp.isNotBlank() && !tlsSeen.startsWith(link.tlsFp)) {
            throw ApiException(0, "fingerprint_mismatch")
        }
    }
    if (reply == null) {
        if (link.relay.isBlank() || link.hub.isBlank()) throw ApiException(0, "unreachable")
        val body = JSONObject().put("pair", JSONObject().put("code", link.code).put("name", name).put("pub", pub))
        reply = relayRequest(Request.Builder().url("${link.relay}/v1/hub/${link.hub}/call").json(body).build())
        tlsSeen = reply!!.optString("fingerprint")
        val lan = reply!!.optJSONArray("lan")?.optString(0).orEmpty()
        if (lan.isNotBlank()) {
            host = lan.substringBefore(':'); port = lan.substringAfter(':', "").toIntOrNull() ?: port
        }
    }
    val r = reply!!
    val pcPub = r.optString("pc_pub")
    if (link.keyFp.isNotBlank() && (pcPub.isBlank() || Crypto.fingerprint(pcPub) != link.keyFp)) {
        throw ApiException(0, "fingerprint_mismatch")
    }
    return Pairing(
        host = host, port = port, token = r.getString("token"), fingerprint = tlsSeen.ifBlank { r.optString("fingerprint") },
        deviceId = r.getString("device_id"), pcName = r.optString("name"), pcPub = pcPub,
        hub = r.optString("hub").ifBlank { link.hub }, relay = r.optString("relay").ifBlank { link.relay },
    )
}

// ---------------------------------------------------------------- talking to the paired PC
/**
 * Uses the local network when the PC answers there (fast, direct), otherwise the relay with
 * end-to-end encryption. Remembers a failed local attempt for a minute.
 */
class DeskClient(private val p: Pairing, keys: KeyPair) {
    private val direct = Api(p.host, p.port, p.fingerprint, p.token)
    private val key: ByteArray? =
        if (p.pcPub.isNotBlank()) Crypto.derive(keys.private, p.pcPub, p.deviceId, Crypto.PC_INFO) else null
    private val relayReady = p.relay.isNotBlank() && p.hub.isNotBlank() && key != null

    @Volatile var viaRelay = false
        private set

    companion object {
        @Volatile private var directFailedAt = 0L
    }

    private suspend fun <T> route(local: suspend () -> T, remote: suspend () -> T): T {
        val tryLocal = p.host.isNotBlank() && (!relayReady || System.currentTimeMillis() - directFailedAt > 60_000)
        if (tryLocal) {
            try {
                val v = if (relayReady) withTimeout(4000) { local() } else local()
                viaRelay = false
                return v
            } catch (e: ApiException) {
                throw e
            } catch (e: Exception) {
                if (!relayReady || e is kotlinx.coroutines.CancellationException && e !is kotlinx.coroutines.TimeoutCancellationException) throw e
                directFailedAt = System.currentTimeMillis()
            }
        }
        val v = remote()
        viaRelay = true
        return v
    }

    private fun envelope(method: String, path: String, body: JSONObject = JSONObject()): JSONObject {
        val req = JSONObject().put("m", method).put("p", path).put("b", body)
            .put("t", System.currentTimeMillis() / 1000.0)
        return Crypto.seal(key!!, req, p.deviceId).put("d", p.deviceId)
    }

    private suspend fun relayCall(method: String, path: String, body: JSONObject = JSONObject()): JSONObject {
        val r = relayRequest(Request.Builder().url("${p.relay}/v1/hub/${p.hub}/call")
            .json(envelope(method, path, body)).build())
        val inner = Crypto.open(key!!, r, p.deviceId)
        val status = inner.optInt("s", 500)
        val b = inner.optJSONObject("b") ?: JSONObject()
        if (status != 200) throw ApiException(status, b.optString("error", "http_$status"))
        return b
    }

    suspend fun status(): DeskStatus = route({ direct.status() }, { Api.parseStatus(relayCall("GET", "/api/status")) })

    suspend fun sendMessage(text: String) =
        route({ direct.sendMessage(text) }, { relayCall("POST", "/api/message", JSONObject().put("text", text)); Unit })

    suspend fun rename(name: String) =
        route({ direct.rename(name) }, { relayCall("POST", "/api/rename", JSONObject().put("name", name)); Unit })

    suspend fun watchCamera(onFrame: (Bitmap) -> Unit) {
        // the local network first (if it answers quickly), then the relay
        if (p.host.isNotBlank() && (!relayReady || System.currentTimeMillis() - directFailedAt > 60_000)) {
            try {
                if (relayReady) withTimeout(4000) { direct.info() }
                viaRelay = false
                direct.watchCamera(onFrame)
                return
            } catch (e: ApiException) {
                throw e
            } catch (e: Exception) {
                if (!relayReady || e is kotlinx.coroutines.CancellationException && e !is kotlinx.coroutines.TimeoutCancellationException) throw e
                directFailedAt = System.currentTimeMillis()
            }
        }
        viaRelay = true
        relayCamera(onFrame)
    }

    private suspend fun relayCamera(onFrame: (Bitmap) -> Unit) = withContext(Dispatchers.IO) {
        val client = relayHttp.newBuilder().readTimeout(30, TimeUnit.SECONDS).build()
        val call = client.newCall(Request.Builder().url("${p.relay}/v1/hub/${p.hub}/stream")
            .json(envelope("GET", "/api/camera")).build())
        val ctx = currentCoroutineContext()
        ctx[kotlinx.coroutines.Job]?.invokeOnCompletion { call.cancel() }
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                val json = runCatching { JSONObject(resp.body?.string().orEmpty()) }.getOrDefault(JSONObject())
                throw ApiException(resp.code, json.optString("error", "http_${resp.code}"))
            }
            val input = DataInputStream(resp.body!!.byteStream())
            while (ctx.isActive) {
                val length = runCatching { input.readInt() }.getOrNull() ?: break
                val frame = ByteArray(length).also { input.readFully(it) }
                val plain = Crypto.openBytes(key!!, frame, p.deviceId)
                if (plain.isNotEmpty() && plain[0] == '{'.code.toByte()) {
                    val err = JSONObject(String(plain)).optString("error")
                    throw ApiException(if (err == "camera_busy") 409 else 403, err)
                }
                BitmapFactory.decodeByteArray(plain, 0, plain.size)?.let(onFrame)
            }
        }
    }
}

// ---------------------------------------------------------------- phone <-> phone
data class PeerStatus(
    val contact: Contact,
    val preset: String,
    val text: String,
    val battery: Int,
    val charging: Boolean,
    val inCall: Boolean,
    val updatedAt: Long,   // unix seconds, when the other phone last sent its status
)

data class DeviceState(val battery: Int, val charging: Boolean, val inCall: Boolean)

fun readDeviceState(context: Context): DeviceState {
    val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
    val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
    val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
    val plugged = (battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0) != 0
    // MODE_IN_CALL = phone call, MODE_IN_COMMUNICATION = WhatsApp / Telegram / ... call; no permission needed
    val mode = (context.getSystemService(Context.AUDIO_SERVICE) as AudioManager).mode
    return DeviceState(
        battery = if (level >= 0 && scale > 0) level * 100 / scale else -1,
        charging = plugged,
        inCall = mode == AudioManager.MODE_IN_CALL || mode == AudioManager.MODE_IN_COMMUNICATION,
    )
}

class PeopleClient(private val store: Store, private val keys: KeyPair) {
    val relay: String get() = store.relayUrl()
    private val myPub = Crypto.publicB64(keys.public)
    val myFingerprint: String get() = Crypto.fingerprint(myPub)

    private suspend fun account(): Pair<String, String> {
        store.relayAccount()?.let { return it }
        if (relay.isBlank()) throw ApiException(0, "no_relay")
        val r = relayRequest(Request.Builder().url("$relay/v1/phones").json(JSONObject()).build())
        store.setRelayAccount(r.getString("phone_id"), r.getString("secret"))
        return r.getString("phone_id") to r.getString("secret")
    }

    private suspend fun req(path: String, method: String = "GET", body: JSONObject? = null): JSONObject {
        val (id, secret) = account()
        val b = Request.Builder().url("$relay$path").header("Authorization", "Phone $id:$secret")
        when (method) {
            "GET" -> b.get()
            "DELETE" -> b.delete()
            "PUT" -> b.put((body ?: JSONObject()).toString().toRequestBody(JSON))
            else -> b.json(body ?: JSONObject())
        }
        return relayRequest(b.build())
    }

    private suspend fun pairKey(contact: Contact): ByteArray {
        val myId = account().first
        val salt = listOf(myId, contact.id).sorted().joinToString("")
        return Crypto.derive(keys.private, contact.pub, salt, Crypto.PHONE_INFO)
    }

    /** Creates an invite: returns (code, link to share / show as QR). */
    suspend fun createInvite(myName: String): Pair<String, String> {
        val code = req("/v1/invites", "POST", JSONObject().put("pub", myPub).put("name", myName)).getString("code")
        return code to "$relay/i/#c=$code&k=$myFingerprint"
    }

    /** Polls an own invite; returns the new contact once somebody accepted it. */
    suspend fun inviteResult(code: String): Contact? {
        val r = req("/v1/invites/$code/result")
        if (r.optBoolean("waiting")) return null
        return Contact(r.getString("phone_id"), r.optString("name"), r.getString("pub")).also(store::addContact)
    }

    /** Accepts somebody else's invite (code typed, QR scanned or link opened). */
    suspend fun acceptInvite(code: String, keyFp: String, myName: String): Contact {
        val r = req("/v1/invites/$code")
        val pub = r.getString("pub")
        if (keyFp.isNotBlank() && Crypto.fingerprint(pub) != keyFp) throw ApiException(0, "fingerprint_mismatch")
        req("/v1/invites/$code/accept", "POST", JSONObject().put("pub", myPub).put("name", myName))
        return Contact(r.getString("phone_id"), r.optString("name"), pub).also(store::addContact)
    }

    suspend fun pushStatus(context: Context) {
        val contacts = store.contacts()
        if (contacts.isEmpty() || relay.isBlank()) return
        val myId = account().first
        val s = store.myStatus()
        val d = readDeviceState(context)
        val obj = JSONObject().put("preset", s.preset).put("text", s.text).put("battery", d.battery)
            .put("charging", d.charging).put("in_call", d.inCall).put("name", store.myName(""))
            .put("t", System.currentTimeMillis() / 1000)
        val to = JSONObject()
        contacts.forEach { c -> to.put(c.id, Crypto.seal(pairKey(c), obj, myId).toString()) }
        req("/v1/status", "PUT", JSONObject().put("to", to))
    }

    suspend fun fetchStatuses(): List<PeerStatus> {
        val contacts = store.contacts()
        if (contacts.isEmpty() || relay.isBlank()) return emptyList()
        val from = req("/v1/status").optJSONObject("from") ?: JSONObject()
        return contacts.mapNotNull { c ->
            val entry = from.optJSONObject(c.id) ?: return@mapNotNull PeerStatus(c, "", "", -1, false, false, 0)
            runCatching {
                val o = Crypto.open(pairKey(c), JSONObject(entry.getString("sealed")), c.id)
                PeerStatus(c, o.optString("preset"), o.optString("text"), o.optInt("battery", -1),
                    o.optBoolean("charging"), o.optBoolean("in_call"), o.optLong("t", entry.optLong("at")))
            }.getOrNull()
        }
    }

    suspend fun remove(contact: Contact) {
        runCatching { req("/v1/contacts/${contact.id}", "DELETE") }
        store.removeContact(contact.id)
    }
}
