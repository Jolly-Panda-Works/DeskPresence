package com.jollypanda.deskpresence

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicBoolean

/** A PC running DeskPresence, found on the Wi-Fi network. */
data class FoundPc(val name: String, val host: String, val port: Int, val fingerprintPrefix: String)

/** Finds PCs that advertise _deskpresence._tcp over mDNS. Emits the full list whenever it changes. */
fun discoverPcs(context: Context): Flow<List<FoundPc>> = callbackFlow {
    val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    val lock = wifi.createMulticastLock("deskpresence").apply { setReferenceCounted(false); acquire() }
    val found = linkedMapOf<String, FoundPc>()
    // older Android versions can resolve only one service at a time
    val queue = ConcurrentLinkedQueue<NsdServiceInfo>()
    val resolving = AtomicBoolean(false)

    fun resolveNext() {
        if (!resolving.compareAndSet(false, true)) return
        val info = queue.poll() ?: run { resolving.set(false); return }
        @Suppress("DEPRECATION")
        nsd.resolveService(info, object : NsdManager.ResolveListener {
            override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                resolving.set(false); resolveNext()
            }

            override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                val host = if (Build.VERSION.SDK_INT >= 34) {
                    serviceInfo.hostAddresses.firstOrNull { it.address.size == 4 }?.hostAddress
                } else {
                    @Suppress("DEPRECATION") serviceInfo.host?.hostAddress
                }
                if (host != null) {
                    val attrs = serviceInfo.attributes
                    val name = attrs["name"]?.toString(Charsets.UTF_8) ?: serviceInfo.serviceName
                    val fp = attrs["fp"]?.toString(Charsets.UTF_8) ?: ""
                    found[serviceInfo.serviceName] = FoundPc(name, host, serviceInfo.port, fp)
                    trySend(found.values.toList())
                }
                resolving.set(false); resolveNext()
            }
        })
    }

    val listener = object : NsdManager.DiscoveryListener {
        override fun onDiscoveryStarted(serviceType: String) = Unit
        override fun onDiscoveryStopped(serviceType: String) = Unit
        override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
        override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
        override fun onServiceFound(info: NsdServiceInfo) {
            queue.add(info); resolveNext()
        }

        override fun onServiceLost(info: NsdServiceInfo) {
            if (found.remove(info.serviceName) != null) trySend(found.values.toList())
        }
    }
    trySend(emptyList())
    nsd.discoverServices("_deskpresence._tcp", NsdManager.PROTOCOL_DNS_SD, listener)
    awaitClose {
        runCatching { nsd.stopServiceDiscovery(listener) }
        lock.release()
    }
}
