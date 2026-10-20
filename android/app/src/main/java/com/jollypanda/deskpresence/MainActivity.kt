package com.jollypanda.deskpresence

import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.flow.MutableStateFlow

class MainActivity : ComponentActivity() {
    /** A pairing / invite link the app was opened with (QR code in another app, messenger link...). */
    private val incomingLink = MutableStateFlow<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        incomingLink.value = intent?.dataString
        StatusWorker.schedule(this)
        setContent {
            DeskTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = Palette.Bg) {
                    Box(Modifier.safeDrawingPadding()) {
                        val link by incomingLink.collectAsState()
                        App(link, onLinkHandled = { incomingLink.value = null })
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        incomingLink.value = intent.dataString
    }
}

enum class Tab { Pc, People }
enum class Screen { Home, Camera }

@Composable
fun App(incoming: String?, onLinkHandled: () -> Unit) {
    val context = LocalContext.current
    val store = remember { Store(context) }
    val keys = remember { store.identity() }
    var pairing by remember { mutableStateOf(store.load()) }
    var screen by remember { mutableStateOf(Screen.Home) }
    var tab by remember { mutableStateOf(Tab.Pc) }
    var pcLink by remember { mutableStateOf<DeskLink.Pc?>(null) }
    var invite by remember { mutableStateOf<DeskLink.Invite?>(null) }
    val defaultName = remember { "${Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${Build.MODEL}" }

    LaunchedEffect(incoming) {
        when (val link = incoming?.let(::parseLink)) {
            is DeskLink.Pc -> { tab = Tab.Pc; pairing = null; pcLink = link }
            is DeskLink.Invite -> { tab = Tab.People; invite = link }
            null -> Unit
        }
        if (incoming != null) onLinkHandled()
    }

    if (screen == Screen.Camera && pairing != null) {
        BackHandler { screen = Screen.Home }
        CameraScreen(pairing = pairing!!, keys = keys, onClose = { screen = Screen.Home })
        return
    }

    Column(Modifier.fillMaxSize()) {
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (tab) {
                Tab.Pc -> {
                    val current = pairing
                    if (current == null) {
                        PairScreen(defaultName = defaultName, keys = keys, initialLink = pcLink, onPaired = { p ->
                            store.save(p); pairing = p; pcLink = null; screen = Screen.Home
                        })
                    } else {
                        HomeScreen(
                            pairing = current, keys = keys,
                            onWatch = { screen = Screen.Camera },
                            onMoved = { host, port ->
                                store.updateAddress(host, port)
                                pairing = current.copy(host = host, port = port)
                            },
                            onUnpair = { store.forgetPc(); pairing = null },
                        )
                    }
                }
                Tab.People -> PeopleScreen(store, invite, onInviteHandled = { invite = null })
            }
        }
        NavigationBar(containerColor = Palette.Toolbar) {
            val colors = NavigationBarItemDefaults.colors(
                selectedIconColor = Palette.OnOrange, selectedTextColor = Palette.Orange,
                indicatorColor = Palette.Orange, unselectedIconColor = Palette.Muted, unselectedTextColor = Palette.Muted,
            )
            NavigationBarItem(selected = tab == Tab.Pc, onClick = { tab = Tab.Pc }, colors = colors,
                icon = { Text("🖥", fontSize = 20.sp) }, label = { Text(stringResource(R.string.tab_pc)) })
            NavigationBarItem(selected = tab == Tab.People, onClick = { tab = Tab.People }, colors = colors,
                icon = { Text("👥", fontSize = 20.sp) }, label = { Text(stringResource(R.string.tab_people)) })
        }
    }
}
