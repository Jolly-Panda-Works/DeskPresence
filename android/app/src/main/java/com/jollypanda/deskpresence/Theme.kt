package com.jollypanda.deskpresence

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Same palette as the DeskPresence desktop app (and Image Format Converter / SnapshotAll)
object Palette {
    val Bg = Color(0xFF110D0A)
    val Toolbar = Color(0xFF16110D)
    val Panel = Color(0xFF1F1813)
    val PanelHi = Color(0xFF2B221B)
    val Field = Color(0xFF2A211A)
    val Border = Color(0xFF3A2E24)
    val Fg = Color(0xFFF5EEE8)
    val Muted = Color(0xFFA99B8E)
    val Faint = Color(0xFF6E6259)
    val Orange = Color(0xFFF97316)
    val OrangeHi = Color(0xFFFB923C)
    val OnOrange = Color(0xFF1A0E05)
    val Green = Color(0xFF4ADE80)
    val Amber = Color(0xFFFBBF24)
    val Blue = Color(0xFF60A5FA)
    val Red = Color(0xFFF87171)
}

@Composable
fun DeskTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Palette.Orange,
            onPrimary = Palette.OnOrange,
            secondary = Palette.OrangeHi,
            background = Palette.Bg,
            onBackground = Palette.Fg,
            surface = Palette.Panel,
            onSurface = Palette.Fg,
            surfaceVariant = Palette.Field,
            onSurfaceVariant = Palette.Muted,
            outline = Palette.Border,
            error = Palette.Red,
        ),
        content = content,
    )
}
