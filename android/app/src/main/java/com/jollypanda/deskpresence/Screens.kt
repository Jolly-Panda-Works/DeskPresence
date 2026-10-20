package com.jollypanda.deskpresence

import android.graphics.Bitmap
import android.text.format.DateUtils
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.mapNotNull
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import javax.net.ssl.SSLHandshakeException

// ---------------------------------------------------------------- shared widgets
@Composable
fun Card(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(Palette.Panel)
            .border(1.dp, Palette.Border, RoundedCornerShape(18.dp))
            .padding(18.dp),
        content = content,
    )
}

@Composable
fun SectionLabel(text: String) =
    Text(text.uppercase(), color = Palette.Orange, fontSize = 12.sp, fontWeight = FontWeight.Bold)

@Composable
fun PrimaryButton(text: String, enabled: Boolean = true, modifier: Modifier = Modifier, onClick: () -> Unit) =
    Button(
        onClick = onClick, enabled = enabled, modifier = modifier.fillMaxWidth().height(52.dp),
        shape = RoundedCornerShape(14.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = Palette.Orange, contentColor = Palette.OnOrange,
            disabledContainerColor = Palette.PanelHi, disabledContentColor = Palette.Faint,
        ),
    ) { Text(text, fontWeight = FontWeight.Bold, fontSize = 16.sp) }

@Composable
fun GhostButton(text: String, modifier: Modifier = Modifier, onClick: () -> Unit) =
    OutlinedButton(
        onClick = onClick, modifier = modifier.fillMaxWidth().height(52.dp), shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, Palette.Border),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = Palette.Fg),
    ) { Text(text, fontSize = 16.sp) }

@Composable
fun field(value: String, onChange: (String) -> Unit, label: String, keyboard: KeyboardType = KeyboardType.Text,
          placeholder: String? = null) =
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true,
        placeholder = placeholder?.let { { Text(it, color = Palette.Faint) } },
        keyboardOptions = KeyboardOptions(keyboardType = keyboard),
        modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = Palette.Orange, unfocusedBorderColor = Palette.Border,
            focusedLabelColor = Palette.Orange, cursorColor = Palette.Orange,
            focusedContainerColor = Palette.Field, unfocusedContainerColor = Palette.Field,
        ),
    )

@Composable
fun Header(title: String, subtitle: String? = null, trailing: @Composable () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(11.dp)).background(Palette.Orange),
            contentAlignment = Alignment.Center) {
            Text("👁", fontSize = 20.sp)
        }
        Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
            Text(title, color = Palette.Fg, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            if (subtitle != null) Text(subtitle, color = Palette.Muted, fontSize = 13.sp)
        }
        trailing()
    }
}

fun errorText(e: Throwable, ctx: android.content.Context): String = when {
    e is ApiException && e.code == 403 -> ctx.getString(R.string.err_bad_code)
    e is ApiException && e.message == "fingerprint_mismatch" -> ctx.getString(R.string.err_certificate)
    e is ApiException && e.code == 503 -> ctx.getString(R.string.err_pc_offline)
    e is SSLHandshakeException || e.cause is java.security.cert.CertificateException ->
        ctx.getString(R.string.err_certificate)
    else -> ctx.getString(R.string.err_unreachable)
}

// ---------------------------------------------------------------- pairing
@Composable
fun PairScreen(defaultName: String, keys: java.security.KeyPair, initialLink: DeskLink.Pc?, onPaired: (Pairing) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val found by remember { discoverPcs(context) }.collectAsState(initial = emptyList())
    var selected by remember { mutableStateOf<FoundPc?>(null) }
    var address by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var name by remember { mutableStateOf(defaultName) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun pair(link: DeskLink.Pc) {
        busy = true; error = null
        scope.launch {
            runCatching { pairWithPc(link, name.ifBlank { defaultName }, keys) }
                .onSuccess(onPaired)
                .onFailure { error = errorText(it, context) }
            busy = false
        }
    }

    // a QR code / link carries everything: connect right away
    LaunchedEffect(initialLink) { initialLink?.let(::pair) }
    val scanner = rememberQrScanner { text ->
        when (val link = parseLink(text)) {
            is DeskLink.Pc -> pair(link)
            else -> error = context.getString(R.string.err_not_pc_link)
        }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Header(stringResource(R.string.pair_title), stringResource(R.string.pair_subtitle))

        PrimaryButton("⌖  " + stringResource(R.string.scan_qr), enabled = !busy) { scanner.launch(scanOptions(context)) }
        Text(stringResource(R.string.scan_or_link), color = Palette.Faint, fontSize = 13.sp,
            modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)

        Card {
            SectionLabel(stringResource(R.string.pair_found))
            Spacer(Modifier.height(10.dp))
            if (found.isEmpty()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(18.dp), color = Palette.Orange, strokeWidth = 2.dp)
                    Spacer(Modifier.width(10.dp))
                    Text(stringResource(R.string.pair_searching), color = Palette.Muted)
                }
            }
            found.forEach { pc ->
                val active = selected == pc
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp))
                        .background(if (active) Palette.PanelHi else Palette.Field)
                        .border(1.dp, if (active) Palette.Orange else Palette.Border, RoundedCornerShape(12.dp))
                        .clickable { selected = pc; address = "" }
                        .padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("🖥", fontSize = 22.sp)
                    Column(Modifier.padding(horizontal = 12.dp)) {
                        Text(pc.name, color = Palette.Fg, fontWeight = FontWeight.Bold)
                        Text("${pc.host}:${pc.port}", color = Palette.Muted, fontSize = 12.sp)
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            field(address, { v ->
                // a pasted pairing link works too
                val link = parseLink(v)
                if (link is DeskLink.Pc) pair(link) else { address = v.trim(); if (v.isNotBlank()) selected = null }
            }, stringResource(R.string.pair_address), KeyboardType.Uri, stringResource(R.string.pair_address_hint))
        }

        Card {
            field(code, { v -> code = v.filter(Char::isDigit).take(6) }, stringResource(R.string.pair_code),
                KeyboardType.NumberPassword)
            Spacer(Modifier.height(10.dp))
            field(name, { name = it.take(40) }, stringResource(R.string.pair_name))
        }

        error?.let { Text(it, color = Palette.Red, fontSize = 14.sp) }

        val lan: String? = selected?.let { "${it.host}:${it.port}" }
            ?: address.takeIf { it.isNotBlank() }?.let { if (':' in it) it else "$it:${Api.DEFAULT_PORT}" }
        PrimaryButton(
            if (busy) stringResource(R.string.pair_working) else stringResource(R.string.pair_button),
            enabled = !busy && code.length == 6 && lan != null,
        ) {
            pair(DeskLink.Pc(code, keyFp = "", tlsFp = selected?.fingerprintPrefix.orEmpty(), lan = lan ?: return@PrimaryButton,
                hub = "", relay = ""))
        }
        if (lan == null) Text(stringResource(R.string.pair_choose), color = Palette.Faint, fontSize = 13.sp,
            modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
    }
}

// ---------------------------------------------------------------- home
@Composable
fun HomeScreen(pairing: Pairing, keys: java.security.KeyPair, onWatch: () -> Unit, onMoved: (String, Int) -> Unit,
               onUnpair: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val api = remember(pairing) { DeskClient(pairing, keys) }
    var status by remember { mutableStateOf<DeskStatus?>(null) }
    var lastOk by remember { mutableStateOf(0L) }
    var offline by remember { mutableStateOf(false) }
    var unpaired by remember { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    var dialog by remember { mutableStateOf<String?>(null) } // "message" | "rename" | "unpair"
    var toast by remember { mutableStateOf<String?>(null) }

    // poll the PC every 5 seconds; if it cannot be reached, look for it on the network (new IP)
    LaunchedEffect(api) {
        var failures = 0
        while (true) {
            runCatching { api.status() }
                .onSuccess { status = it; lastOk = System.currentTimeMillis(); offline = false; failures = 0 }
                .onFailure { e ->
                    if (e is ApiException && e.code == 401) { unpaired = true; return@LaunchedEffect }
                    offline = true
                    failures++
                    if (failures % 3 == 0) {
                        val moved = withTimeoutOrNull(6000) {
                            discoverPcs(context).mapNotNull { list ->
                                list.firstOrNull {
                                    it.fingerprintPrefix.isNotEmpty() && pairing.fingerprint.startsWith(it.fingerprintPrefix)
                                }
                            }.first()
                        }
                        moved?.let { if (it.host != pairing.host || it.port != pairing.port) onMoved(it.host, it.port) }
                    }
                }
            delay(5000)
        }
    }
    LaunchedEffect(toast) { if (toast != null) { delay(2500); toast = null } }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Header(pairing.pcName.ifBlank { "DeskPresence" }, status?.deviceName) {
            Box {
                TextButton(onClick = { menu = true }) { Text("⋮", color = Palette.Fg, fontSize = 22.sp) }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(text = { Text(stringResource(R.string.menu_rename)) },
                        onClick = { menu = false; dialog = "rename" })
                    DropdownMenuItem(text = { Text(stringResource(R.string.menu_unpair)) },
                        onClick = { menu = false; dialog = "unpair" })
                }
            }
        }

        if (unpaired) {
            Card {
                Text(stringResource(R.string.unpaired), color = Palette.Fg)
                Spacer(Modifier.height(12.dp))
                PrimaryButton(stringResource(R.string.pair_again), onClick = onUnpair)
            }
            return@Column
        }

        StatusCard(status)

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            StatTile("💧", status?.waterToday?.toString() ?: "–", stringResource(R.string.water_today), Modifier.weight(1f))
            StatTile("⏱", status?.let { formatWork(it.workSecondsToday) } ?: "–", stringResource(R.string.work_today),
                Modifier.weight(1f))
        }

        val s = status
        val canWatch = s != null && s.cameraAllowed && s.cameraAvailable && !offline
        PrimaryButton("👁  " + stringResource(R.string.watch), enabled = canWatch, onClick = onWatch)
        if (s != null && !s.cameraAllowed) Text(stringResource(R.string.watch_off), color = Palette.Faint, fontSize = 13.sp)
        else if (s != null && !s.cameraAvailable) Text(stringResource(R.string.watch_busy), color = Palette.Faint, fontSize = 13.sp)
        GhostButton("✉  " + stringResource(R.string.message)) { dialog = "message" }

        if (offline) Text(stringResource(R.string.offline, pairing.pcName), color = Palette.Amber, fontSize = 13.sp)
        else if (lastOk > 0) Text(
            stringResource(R.string.updated, DateUtils.getRelativeTimeSpanString(lastOk).toString()) + "  ·  " +
                stringResource(if (api.viaRelay) R.string.via_relay else R.string.via_local),
            color = Palette.Faint, fontSize = 12.sp, modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
        toast?.let { Text(it, color = Palette.Green, modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center) }
    }

    when (dialog) {
        "message" -> TextDialog(stringResource(R.string.message), stringResource(R.string.message_hint), "",
            stringResource(R.string.send), maxLength = 500, onDismiss = { dialog = null }) { text ->
            scope.launch {
                runCatching { api.sendMessage(text) }
                    .onSuccess { toast = context.getString(R.string.sent) }
                    .onFailure { toast = errorText(it, context) }
            }
        }
        "rename" -> TextDialog(stringResource(R.string.menu_rename), null, status?.deviceName ?: "",
            stringResource(R.string.send), maxLength = 40, onDismiss = { dialog = null }) { text ->
            scope.launch { runCatching { api.rename(text) }.onSuccess { toast = context.getString(R.string.rename_saved) } }
        }
        "unpair" -> AlertDialog(
            onDismissRequest = { dialog = null },
            text = { Text(stringResource(R.string.unpair_confirm, pairing.pcName)) },
            confirmButton = { TextButton(onClick = { dialog = null; onUnpair() }) {
                Text(stringResource(R.string.menu_unpair), color = Palette.Red) } },
            dismissButton = { TextButton(onClick = { dialog = null }) { Text(stringResource(R.string.cancel)) } },
            containerColor = Palette.Panel,
        )
    }
}

@Composable
private fun StatusCard(status: DeskStatus?) {
    val (label, color) = when (status?.state) {
        "working" -> stringResource(R.string.state_working) to Palette.Green
        "away" -> stringResource(R.string.state_away) to Palette.Amber
        "break" -> stringResource(R.string.state_break) to Palette.Blue
        else -> stringResource(R.string.state_unknown) to Palette.Muted
    }
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(22.dp).clip(CircleShape).background(color))
            Spacer(Modifier.width(14.dp))
            Column {
                Text(label, color = Palette.Fg, fontSize = 30.sp, fontWeight = FontWeight.Bold)
                if (status != null && status.since > 0) {
                    val seconds = (System.currentTimeMillis() / 1000 - status.since).coerceAtLeast(0)
                    Text(stringResource(R.string.for_duration, formatDuration(seconds)), color = Palette.Muted)
                }
            }
        }
    }
}

@Composable
private fun StatTile(icon: String, value: String, label: String, modifier: Modifier) {
    Card(modifier) {
        Text(icon, fontSize = 22.sp)
        Spacer(Modifier.height(6.dp))
        Text(value, color = Palette.Fg, fontSize = 26.sp, fontWeight = FontWeight.Bold)
        Text(label, color = Palette.Muted, fontSize = 13.sp)
    }
}

@Composable
private fun formatDuration(seconds: Long): String {
    val minutes = (seconds / 60).toInt()
    return if (minutes < 60) stringResource(R.string.minutes, minutes)
    else stringResource(R.string.hours_minutes, minutes / 60, minutes % 60)
}

@Composable
private fun formatWork(seconds: Long): String = formatDuration(seconds)

@Composable
private fun TextDialog(title: String, hint: String?, initial: String, confirm: String, maxLength: Int,
                       onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var text by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                if (hint != null) Text(hint, color = Palette.Muted, fontSize = 13.sp)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(value = text, onValueChange = { text = it.take(maxLength) },
                    modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            }
        },
        confirmButton = {
            TextButton(enabled = text.isNotBlank(), onClick = { onConfirm(text.trim()); onDismiss() }) {
                Text(confirm, color = Palette.Orange, fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
        containerColor = Palette.Panel,
    )
}

// ---------------------------------------------------------------- camera
@Composable
fun CameraScreen(pairing: Pairing, keys: java.security.KeyPair, onClose: () -> Unit) {
    val context = LocalContext.current
    var frame by remember { mutableStateOf<Bitmap?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(pairing) {
        val api = DeskClient(pairing, keys)
        runCatching { api.watchCamera { frame = it } }
            .onFailure { e ->
                if (e !is kotlinx.coroutines.CancellationException) {
                    error = when {
                        e is ApiException && e.code == 403 -> context.getString(R.string.watch_off)
                        e is ApiException && e.code == 409 -> context.getString(R.string.watch_busy)
                        else -> errorText(e, context)
                    }
                }
            }
    }
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        val f = frame
        if (f != null) {
            Image(f.asImageBitmap(), contentDescription = null, contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize())
        } else {
            Column(Modifier.align(Alignment.Center).padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                if (error == null) CircularProgressIndicator(color = Palette.Orange)
                Spacer(Modifier.height(12.dp))
                Text(error ?: stringResource(R.string.connecting), color = if (error != null) Palette.Red else Palette.Fg,
                    textAlign = TextAlign.Center)
            }
        }
        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            if (f != null) {
                Text(stringResource(R.string.live), color = Color.White, fontWeight = FontWeight.Bold, fontSize = 12.sp,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Palette.Red)
                        .padding(horizontal = 8.dp, vertical = 3.dp))
            }
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onClose) { Text(stringResource(R.string.close), color = Color.White) }
        }
        Text(stringResource(R.string.camera_notice, pairing.pcName), color = Palette.Muted, fontSize = 12.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(16.dp))
    }
}
