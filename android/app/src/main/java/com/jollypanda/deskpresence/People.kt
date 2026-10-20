package com.jollypanda.deskpresence

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.text.format.DateUtils
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.zxing.BarcodeFormat
import com.journeyapps.barcodescanner.BarcodeEncoder
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

val PRESETS = listOf("available", "busy", "driving", "meeting", "sleeping")

@Composable
fun presetLabel(preset: String): String = when (preset) {
    "available" -> stringResource(R.string.st_available)
    "busy" -> stringResource(R.string.st_busy)
    "driving" -> stringResource(R.string.st_driving)
    "meeting" -> stringResource(R.string.st_meeting)
    "sleeping" -> stringResource(R.string.st_sleeping)
    else -> ""
}

fun presetEmoji(preset: String) = when (preset) {
    "available" -> "🟢"; "busy" -> "⛔"; "driving" -> "🚗"; "meeting" -> "👥"; "sleeping" -> "🌙"; else -> "💬"
}

fun qrBitmap(text: String): Bitmap = BarcodeEncoder().encodeBitmap(text, BarcodeFormat.QR_CODE, 640, 640)

@Composable
fun rememberQrScanner(onResult: (String) -> Unit) =
    rememberLauncherForActivityResult(ScanContract()) { result -> result.contents?.let(onResult) }

fun scanOptions(context: Context) = ScanOptions()
    .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
    .setPrompt(context.getString(R.string.scan_prompt))
    .setBeepEnabled(false)
    .setOrientationLocked(false)

private fun share(context: Context, text: String) {
    val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
    context.startActivity(Intent.createChooser(send, null))
}

private fun peopleError(e: Throwable, context: Context): String = when {
    e is ApiException && e.code == 404 -> context.getString(R.string.err_bad_code)
    e is ApiException && e.message == "fingerprint_mismatch" -> context.getString(R.string.err_certificate)
    e is ApiException && e.message == "no_relay" -> context.getString(R.string.need_relay)
    else -> context.getString(R.string.err_relay)
}

@OptIn(ExperimentalLayoutApi::class, ExperimentalFoundationApi::class)
@Composable
fun PeopleScreen(store: Store, pendingInvite: DeskLink.Invite?, onInviteHandled: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val client = remember { PeopleClient(store, store.identity()) }
    val defaultName = remember { android.os.Build.MODEL }
    var relay by remember { mutableStateOf(store.relayUrl()) }
    var myName by remember { mutableStateOf(store.myName(defaultName)) }
    var status by remember { mutableStateOf(store.myStatus()) }
    var peers by remember { mutableStateOf<List<PeerStatus>>(emptyList()) }
    var contactsVersion by remember { mutableStateOf(0) }
    var dialog by remember { mutableStateOf<String?>(null) }  // "invite" | "join"
    var joinCode by remember { mutableStateOf("") }
    var joinFp by remember { mutableStateOf("") }
    var toast by remember { mutableStateOf<String?>(null) }
    var removeTarget by remember { mutableStateOf<Contact?>(null) }

    LaunchedEffect(pendingInvite) {
        pendingInvite?.let {
            if (it.relay.isNotBlank()) { store.setRelayUrl(it.relay); relay = store.relayUrl() }
            joinCode = it.code; joinFp = it.keyFp; dialog = "join"
            onInviteHandled()
        }
    }
    // share my status and read the others' every 20 seconds while this screen is open
    LaunchedEffect(relay, contactsVersion) {
        while (relay.isNotBlank()) {
            runCatching { client.pushStatus(context) }
            runCatching { client.fetchStatuses() }.onSuccess { peers = it }
            delay(20_000)
        }
    }
    LaunchedEffect(toast) { if (toast != null) { delay(2500); toast = null } }

    fun saveStatus(s: MyStatus) {
        status = s
        store.setMyStatus(s)
        scope.launch { runCatching { client.pushStatus(context) } }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Header(stringResource(R.string.people_title), stringResource(R.string.people_subtitle))

        if (relay.isBlank()) {
            var url by remember { mutableStateOf("https://") }
            Card {
                SectionLabel(stringResource(R.string.relay_title))
                Spacer(Modifier.height(6.dp))
                Text(stringResource(R.string.relay_hint), color = Palette.Muted, fontSize = 13.sp)
                Spacer(Modifier.height(10.dp))
                field(url, { url = it.trim() }, stringResource(R.string.relay_address), KeyboardType.Uri)
                Spacer(Modifier.height(10.dp))
                PrimaryButton(stringResource(R.string.save), enabled = url.length > 10) {
                    store.setRelayUrl(url); relay = store.relayUrl()
                }
            }
            return@Column
        }

        // ---- my status
        Card {
            SectionLabel(stringResource(R.string.my_status))
            Spacer(Modifier.height(10.dp))
            field(myName, { myName = it.take(40); store.setMyName(myName) }, stringResource(R.string.my_name))
            Spacer(Modifier.height(10.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                PRESETS.forEach { p ->
                    val active = status.preset == p
                    Text("${presetEmoji(p)} ${presetLabel(p)}",
                        color = if (active) Palette.OnOrange else Palette.Fg, fontSize = 14.sp,
                        modifier = Modifier.clip(RoundedCornerShape(20.dp))
                            .background(if (active) Palette.Orange else Palette.Field)
                            .border(1.dp, if (active) Palette.Orange else Palette.Border, RoundedCornerShape(20.dp))
                            .clickable { saveStatus(status.copy(preset = p)) }
                            .padding(horizontal = 12.dp, vertical = 7.dp))
                }
            }
            Spacer(Modifier.height(10.dp))
            var text by remember { mutableStateOf(status.text) }
            field(text, { text = it.take(80) }, stringResource(R.string.status_text))
            Spacer(Modifier.height(8.dp))
            GhostButton(stringResource(R.string.save)) { saveStatus(status.copy(text = text.trim())) }
            Text(stringResource(R.string.status_auto), color = Palette.Faint, fontSize = 12.sp,
                modifier = Modifier.padding(top = 8.dp))
        }

        // ---- add a phone
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            PrimaryButton(stringResource(R.string.invite), modifier = Modifier.weight(1f)) { dialog = "invite" }
            GhostButton(stringResource(R.string.join), modifier = Modifier.weight(1f)) { joinCode = ""; joinFp = ""; dialog = "join" }
        }

        // ---- contacts
        val contacts = remember(contactsVersion, peers) { store.contacts() }
        if (contacts.isEmpty()) {
            Text(stringResource(R.string.no_contacts), color = Palette.Muted, fontSize = 14.sp,
                modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
        }
        contacts.forEach { c ->
            val peer = peers.firstOrNull { it.contact.id == c.id }
            PeerCard(c, peer, onRemove = { removeTarget = c })
        }
        toast?.let { Text(it, color = Palette.Green, modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center) }
    }

    when (dialog) {
        "invite" -> InviteDialog(client, myName, onDone = { added ->
            dialog = null
            if (added != null) { contactsVersion++; toast = context.getString(R.string.connected_to, added.name) }
        })
        "join" -> JoinDialog(client, myName, joinCode, joinFp, onDone = { added ->
            dialog = null
            if (added != null) { contactsVersion++; toast = context.getString(R.string.connected_to, added.name) }
        })
    }
    removeTarget?.let { c ->
        AlertDialog(
            onDismissRequest = { removeTarget = null },
            text = { Text(stringResource(R.string.remove_confirm, c.name)) },
            confirmButton = { TextButton(onClick = {
                removeTarget = null
                scope.launch { client.remove(c); contactsVersion++ }
            }) { Text(stringResource(R.string.remove), color = Palette.Red) } },
            dismissButton = { TextButton(onClick = { removeTarget = null }) { Text(stringResource(R.string.cancel)) } },
            containerColor = Palette.Panel,
        )
    }
}

@Composable
private fun PeerCard(contact: Contact, peer: PeerStatus?, onRemove: () -> Unit) {
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(presetEmoji(peer?.preset.orEmpty()), fontSize = 26.sp)
            Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                Text(contact.name.ifBlank { "?" }, color = Palette.Fg, fontWeight = FontWeight.Bold, fontSize = 17.sp)
                val label = peer?.let { presetLabel(it.preset) }.orEmpty()
                val line = listOf(label, peer?.text.orEmpty()).filter { it.isNotBlank() }.joinToString(" · ")
                Text(line.ifBlank { stringResource(R.string.no_status_yet) }, color = Palette.Muted, fontSize = 14.sp)
            }
            TextButton(onClick = onRemove) { Text("✕", color = Palette.Faint) }
        }
        if (peer != null && peer.updatedAt > 0) {
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                if (peer.battery >= 0) Text((if (peer.charging) "⚡ " else "🔋 ") + "${peer.battery}%", color = Palette.Fg, fontSize = 13.sp)
                if (peer.inCall) Text("📞 " + stringResource(R.string.in_call), color = Palette.Amber, fontSize = 13.sp)
                Text("🕒 " + DateUtils.getRelativeTimeSpanString(peer.updatedAt * 1000).toString(),
                    color = Palette.Faint, fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun InviteDialog(client: PeopleClient, myName: String, onDone: (Contact?) -> Unit) {
    val context = LocalContext.current
    var invite by remember { mutableStateOf<Pair<String, String>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        runCatching { client.createInvite(myName) }.onSuccess { invite = it }.onFailure { error = peopleError(it, context) }
        val code = invite?.first ?: return@LaunchedEffect
        repeat(300) {  // 10 minutes
            delay(2000)
            val added = runCatching { client.inviteResult(code) }.getOrNull()
            if (added != null) { onDone(added); return@LaunchedEffect }
        }
    }
    AlertDialog(
        onDismissRequest = { onDone(null) },
        title = { Text(stringResource(R.string.invite)) },
        text = {
            Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                val inv = invite
                when {
                    error != null -> Text(error!!, color = Palette.Red)
                    inv == null -> CircularProgressIndicator(color = Palette.Orange)
                    else -> {
                        Text(stringResource(R.string.invite_hint), color = Palette.Muted, fontSize = 13.sp, textAlign = TextAlign.Center)
                        Spacer(Modifier.height(12.dp))
                        val qr = remember(inv.second) { qrBitmap(inv.second) }
                        Box(Modifier.size(220.dp).clip(RoundedCornerShape(12.dp))) {
                            Image(qr.asImageBitmap(), contentDescription = null, modifier = Modifier.fillMaxSize())
                        }
                        Spacer(Modifier.height(10.dp))
                        Text(inv.first.chunked(3).joinToString(" "), color = Palette.Orange, fontSize = 32.sp,
                            fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(4.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(Modifier.size(14.dp), color = Palette.Muted, strokeWidth = 2.dp)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.waiting_other), color = Palette.Muted, fontSize = 12.sp)
                        }
                    }
                }
            }
        },
        confirmButton = {
            invite?.let { inv ->
                TextButton(onClick = { share(context, inv.second) }) {
                    Text(stringResource(R.string.share_link), color = Palette.Orange, fontWeight = FontWeight.Bold)
                }
            }
        },
        dismissButton = { TextButton(onClick = { onDone(null) }) { Text(stringResource(R.string.close)) } },
        containerColor = Palette.Panel,
    )
}

@Composable
private fun JoinDialog(client: PeopleClient, myName: String, initialCode: String, initialFp: String,
                       onDone: (Contact?) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var code by remember { mutableStateOf(initialCode) }
    var fp by remember { mutableStateOf(initialFp) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scanner = rememberQrScanner { text ->
        when (val link = parseLink(text)) {
            is DeskLink.Invite -> { code = link.code; fp = link.keyFp }
            else -> error = context.getString(R.string.err_not_invite)
        }
    }
    AlertDialog(
        onDismissRequest = { if (!busy) onDone(null) },
        title = { Text(stringResource(R.string.join)) },
        text = {
            Column {
                Text(stringResource(R.string.join_hint), color = Palette.Muted, fontSize = 13.sp)
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(value = code, onValueChange = { v -> code = v.filter(Char::isDigit).take(6); fp = "" },
                    label = { Text(stringResource(R.string.pair_code)) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                    modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
                Spacer(Modifier.height(8.dp))
                GhostButton("⌖  " + stringResource(R.string.scan_qr)) { scanner.launch(scanOptions(context)) }
                error?.let { Text(it, color = Palette.Red, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp)) }
            }
        },
        confirmButton = {
            TextButton(enabled = code.length == 6 && !busy, onClick = {
                busy = true; error = null
                scope.launch {
                    runCatching { client.acceptInvite(code, fp, myName) }
                        .onSuccess { onDone(it) }
                        .onFailure { error = peopleError(it, context) }
                    busy = false
                }
            }) { Text(stringResource(R.string.pair_button), color = Palette.Orange, fontWeight = FontWeight.Bold) }
        },
        dismissButton = { TextButton(onClick = { onDone(null) }) { Text(stringResource(R.string.cancel)) } },
        containerColor = Palette.Panel,
    )
}
