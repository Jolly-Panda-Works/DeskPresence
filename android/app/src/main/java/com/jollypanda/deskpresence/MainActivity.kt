package com.jollypanda.deskpresence

import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            DeskTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = Palette.Bg) {
                    Box(Modifier.safeDrawingPadding()) { App() }
                }
            }
        }
    }
}

enum class Screen { Home, Camera }

@Composable
fun App() {
    val context = LocalContext.current
    val store = remember { Store(context) }
    var pairing by remember { mutableStateOf(store.load()) }
    var screen by remember { mutableStateOf(Screen.Home) }

    val current = pairing
    if (current == null) {
        PairScreen(
            defaultName = "${Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${Build.MODEL}",
            onPaired = { p -> store.save(p); pairing = p; screen = Screen.Home },
        )
        return
    }
    when (screen) {
        Screen.Home -> HomeScreen(
            pairing = current,
            onWatch = { screen = Screen.Camera },
            onMoved = { host, port ->
                store.updateAddress(host, port)
                pairing = current.copy(host = host, port = port)
            },
            onUnpair = { store.clear(); pairing = null },
        )
        Screen.Camera -> {
            BackHandler { screen = Screen.Home }
            CameraScreen(pairing = current, onClose = { screen = Screen.Home })
        }
    }
}
