package com.jollypanda.deskpresence

import android.util.Base64
import org.json.JSONObject
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.PublicKey
import java.security.SecureRandom
import java.security.spec.ECGenParameterSpec
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * End-to-end encryption, the same steps as deskpresence/e2e.py on the PC:
 * P-256 ECDH -> HKDF-SHA256 -> AES-256-GCM (random 12-byte nonce, the sender's id as associated data).
 * Public keys travel as base64url(DER SubjectPublicKeyInfo).
 */
object Crypto {
    val PC_INFO = "deskpresence pc-phone v1".toByteArray()
    val PHONE_INFO = "deskpresence phone-phone v1".toByteArray()
    private val random = SecureRandom()

    fun b64e(data: ByteArray): String =
        Base64.encodeToString(data, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)

    fun b64d(text: String): ByteArray = Base64.decode(text, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)

    fun newKeyPair(): KeyPair =
        KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1"), random) }.generateKeyPair()

    fun publicB64(key: PublicKey) = b64e(key.encoded)
    fun privateB64(key: PrivateKey) = b64e(key.encoded)

    fun loadPublic(b64: String): PublicKey = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(b64d(b64)))
    fun loadPrivate(b64: String): PrivateKey = KeyFactory.getInstance("EC").generatePrivate(PKCS8EncodedKeySpec(b64d(b64)))

    /** First 16 hex digits of SHA-256 over the DER public key (shown in QR codes and links). */
    fun fingerprint(pubB64: String): String =
        MessageDigest.getInstance("SHA-256").digest(b64d(pubB64)).joinToString("") { "%02x".format(it) }.take(16)

    fun derive(mine: PrivateKey, theirPubB64: String, salt: String, info: ByteArray): ByteArray {
        val agreement = KeyAgreement.getInstance("ECDH")
        agreement.init(mine)
        agreement.doPhase(loadPublic(theirPubB64), true)
        return hkdf(agreement.generateSecret(), salt.toByteArray(), info, 32)
    }

    private fun hkdf(ikm: ByteArray, salt: ByteArray, info: ByteArray, length: Int): ByteArray {
        fun hmac(key: ByteArray, data: ByteArray) =
            Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(key, "HmacSHA256")) }.doFinal(data)
        val prk = hmac(if (salt.isEmpty()) ByteArray(32) else salt, ikm)
        val out = java.io.ByteArrayOutputStream()
        var block = ByteArray(0)
        var counter = 1
        while (out.size() < length) {
            block = hmac(prk, block + info + byteArrayOf(counter.toByte()))
            out.write(block)
            counter++
        }
        return out.toByteArray().copyOf(length)
    }

    private fun cipher(mode: Int, key: ByteArray, nonce: ByteArray, aad: String) =
        Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(mode, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
            updateAAD(aad.toByteArray())
        }

    /** {"n": nonce, "c": ciphertext} of a JSON object. */
    fun seal(key: ByteArray, obj: JSONObject, aad: String): JSONObject {
        val nonce = ByteArray(12).also(random::nextBytes)
        val c = cipher(Cipher.ENCRYPT_MODE, key, nonce, aad).doFinal(obj.toString().toByteArray())
        return JSONObject().put("n", b64e(nonce)).put("c", b64e(c))
    }

    fun open(key: ByteArray, envelope: JSONObject, aad: String): JSONObject {
        val plain = cipher(Cipher.DECRYPT_MODE, key, b64d(envelope.getString("n")), aad)
            .doFinal(b64d(envelope.getString("c")))
        return JSONObject(String(plain))
    }

    /** Binary frame: 12-byte nonce + ciphertext. */
    fun openBytes(key: ByteArray, frame: ByteArray, aad: String): ByteArray =
        cipher(Cipher.DECRYPT_MODE, key, frame.copyOfRange(0, 12), aad).doFinal(frame, 12, frame.size - 12)
}
