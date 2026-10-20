package com.jollypanda.deskpresence

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSource
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** What the PC reports. */
data class DeskStatus(
    val state: String,          // working | away | break | unknown
    val since: Long,            // unix seconds of the last change
    val waterToday: Int,
    val workSecondsToday: Long,
    val cameraAllowed: Boolean,
    val cameraAvailable: Boolean,
    val pcName: String,
    val deviceName: String,
)

class ApiException(val code: Int, message: String) : Exception(message)

/**
 * HTTPS client for the DeskPresence server on the PC.
 *
 * The PC uses a self-signed certificate. Instead of a certificate authority, the app pins the
 * certificate's SHA-256 fingerprint it saw when pairing; any other certificate is refused.
 */
class Api(private val host: String, private val port: Int, private val pin: String?, private val token: String?) {
    companion object {
        const val DEFAULT_PORT = 47830
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

        fun parseStatus(r: JSONObject) = DeskStatus(
            state = r.optString("state", "unknown"),
            since = r.optLong("since"),
            waterToday = r.optInt("water_today"),
            workSecondsToday = r.optLong("work_seconds_today"),
            cameraAllowed = r.optBoolean("camera_allowed"),
            cameraAvailable = r.optBoolean("camera_available", true),
            pcName = r.optString("name"),
            deviceName = r.optString("device_name"),
        )
    }

    /** Fingerprint of the certificate seen on the last connection. */
    @Volatile var seenFingerprint: String? = null
        private set

    private val trust = object : X509TrustManager {
        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit
        override fun checkServerTrusted(chain: Array<out X509Certificate>, authType: String?) {
            val fp = sha256(chain[0].encoded)
            seenFingerprint = fp
            if (pin != null && !fp.equals(pin, ignoreCase = true)) {
                throw CertificateException("This is not the paired PC (certificate changed)")
            }
        }
        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    private fun client(readTimeoutSeconds: Long = 10): OkHttpClient {
        val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), SecureRandom()) }
        return OkHttpClient.Builder()
            .sslSocketFactory(ssl.socketFactory, trust)
            .hostnameVerifier { _, _ -> true } // the pinned fingerprint identifies the PC, not its name
            .connectTimeout(6, TimeUnit.SECONDS)
            .readTimeout(readTimeoutSeconds, TimeUnit.SECONDS)
            .build()
    }

    private val base get() = "https://$host:$port"

    private fun request(path: String) = Request.Builder().url(base + path).apply {
        if (token != null) header("Authorization", "Bearer $token")
    }

    private suspend fun call(path: String, body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        val req = request(path).apply {
            if (body != null) post(body.toString().toRequestBody(JSON))
        }.build()
        client().newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            val json = runCatching { JSONObject(text) }.getOrDefault(JSONObject())
            if (!resp.isSuccessful) throw ApiException(resp.code, json.optString("error", "http_${resp.code}"))
            json
        }
    }

    suspend fun info(): JSONObject = call("/api/info")

    /** Pairing over the local network; [seenFingerprint] is the certificate of this very connection. */
    suspend fun pairRaw(code: String, name: String, pub: String): JSONObject {
        val r = call("/api/pair", JSONObject().put("code", code).put("name", name).put("pub", pub))
        val fp = seenFingerprint ?: throw ApiException(0, "no_certificate")
        if (!fp.equals(r.optString("fingerprint"), ignoreCase = true)) throw ApiException(0, "fingerprint_mismatch")
        return r
    }

    suspend fun status(): DeskStatus = parseStatus(call("/api/status"))

    suspend fun sendMessage(text: String) {
        call("/api/message", JSONObject().put("text", text))
    }

    suspend fun rename(name: String) {
        call("/api/rename", JSONObject().put("name", name))
    }

    /** Reads the MJPEG stream and hands every frame to [onFrame] until cancelled. */
    suspend fun watchCamera(onFrame: (Bitmap) -> Unit) = withContext(Dispatchers.IO) {
        val call = client(readTimeoutSeconds = 20).newCall(request("/api/camera").build())
        val ctx = currentCoroutineContext()
        ctx[kotlinx.coroutines.Job]?.invokeOnCompletion { call.cancel() }
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                val json = runCatching { JSONObject(resp.body?.string().orEmpty()) }.getOrDefault(JSONObject())
                throw ApiException(resp.code, json.optString("error", "http_${resp.code}"))
            }
            val source = resp.body!!.source()
            while (ctx.isActive) {
                val jpeg = readPart(source) ?: break
                BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)?.let(onFrame)
            }
        }
    }

    /** One part of multipart/x-mixed-replace: headers, blank line, Content-Length bytes. */
    private fun readPart(source: BufferedSource): ByteArray? {
        var length = -1
        while (true) {
            val line = source.readUtf8Line() ?: return null
            if (line.startsWith("Content-Length:", ignoreCase = true)) {
                length = line.substringAfter(':').trim().toIntOrNull() ?: -1
            } else if (line.isEmpty() && length >= 0) {
                break
            }
        }
        val bytes = source.readByteArray(length.toLong())
        source.readUtf8Line() // the CRLF after the image
        return bytes
    }
}
