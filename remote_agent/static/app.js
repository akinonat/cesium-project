"use strict";

const $ = (id) => document.getElementById(id);
const PRESETS = {
  low: { quality: 35, max_width: 1280, fps: 10 },
  mid: { quality: 60, max_width: 1920, fps: 15 },
  high: { quality: 80, max_width: 0, fps: 20 },
};
const MODIFIERS = new Set([
  "ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight",
  "AltLeft", "AltRight", "MetaLeft", "MetaRight",
]);

const canvas = $("screen");
const ctx = canvas.getContext("2d");
let ws = null;
let reconnectDelay = 1000;
let loggedOut = false;
let lastCursor = null;
let frameChain = Promise.resolve();
const stats = { frames: 0, bytes: 0 };

// ---------------------------------------------------------------- yardımcılar
function toast(msg, ms = 2500) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), ms);
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function showView(name) {
  $("login").hidden = name !== "login";
  $("remote").hidden = name !== "remote";
}

function overlay(text) {
  $("overlay").textContent = text || "";
  $("overlay").hidden = !text;
}

// ---------------------------------------------------------------- giriş
async function checkSession() {
  const r = await fetch("/api/session", { cache: "no-store", signal: AbortSignal.timeout(5000) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const s = await r.json();
  document.title = `${s.name} – Uzak Masaüstü`;
  $("login-name").textContent = s.name;
  $("pc-name").textContent = s.name;
  return s.authenticated;
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("login-error").textContent = "";
  const btn = e.submitter || e.target.querySelector("button");
  btn.disabled = true;
  try {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("password").value }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `Hata ${r.status}`);
    $("password").value = "";
    loggedOut = false;
    startRemote();
  } catch (err) {
    $("login-error").textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

$("btn-logout").addEventListener("click", async () => {
  loggedOut = true;
  releaseModifiers();
  if (ws) ws.close();
  await fetch("/api/logout", { method: "POST" });
  showView("login");
});

// ---------------------------------------------------------------- bağlantı
function startRemote() {
  showView("remote");
  connect();
}

const PING_EVERY_MS = 5000;
const DEAD_AFTER_MS = 15000; // bu süre hiç mesaj gelmezse bağlantı ölü sayılır
let lastMessageAt = 0;
let reconnectTimer = null;

function connect() {
  if (ws || loggedOut) return;
  clearTimeout(reconnectTimer);
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const sock = new WebSocket(`${proto}//${location.host}/ws`);
  ws = sock;
  sock.binaryType = "arraybuffer";
  lastMessageAt = Date.now();
  overlay("Bağlanıyor…");

  sock.onopen = () => {
    reconnectDelay = 1000;
    applyQuality();
  };
  sock.onmessage = (ev) => {
    lastMessageAt = Date.now();
    if (typeof ev.data === "string") onJson(JSON.parse(ev.data));
    // Kareler sırayla çizilmeli: fark döşemeleri önceki karenin üstüne gelir
    else frameChain = frameChain.then(() => onFrame(ev.data));
  };
  sock.onclose = () => onDisconnected(sock);
}

// Ağ değişince (Wi-Fi -> mobil veri) eski bağlantı hata vermeden "ölebilir".
// Düzenli ping atıp yanıt gelmezse bağlantıyı bırakıp yeniden kuruyoruz.
setInterval(() => {
  if (!ws) return;
  if (Date.now() - lastMessageAt > DEAD_AFTER_MS) {
    const dead = ws;
    dead.onclose = null;
    dead.onmessage = null;
    try { dead.close(); } catch { /* yok say */ }
    onDisconnected(dead);
  } else {
    send({ t: "ping" });
  }
}, PING_EVERY_MS);

async function onDisconnected(sock) {
  if (ws !== sock) return;
  ws = null;
  // Sunucu bağlantı kopunca basılı tuşları zaten bırakır; yerel durumu da sıfırla
  heldMods.clear();
  sentKeys.clear();
  if (loggedOut) return;
  overlay("Bağlantı koptu, kontrol ediliyor…");

  // Sunucuya ulaşılamıyorsa (internet yok, bilgisayar kapalı) denemeye devam et;
  // yalnızca sunucu "oturum geçersiz" derse giriş ekranına dön.
  let authed = null;
  try { authed = await checkSession(); } catch { /* ulaşılamıyor */ }
  if (authed === false) {
    showView("login");
    $("login-error").textContent = "Oturum sona erdi, tekrar giriş yapın.";
    return;
  }
  const secs = Math.round(reconnectDelay / 1000);
  overlay(`Bağlantı koptu. ${secs} sn içinde yeniden denenecek…\n(Hemen denemek için dokunun)`);
  reconnectTimer = setTimeout(connect, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, 15000);
}

function reconnectNow() {
  if (ws || loggedOut || $("remote").hidden) return;
  reconnectDelay = 1000;
  connect();
}
window.addEventListener("online", reconnectNow);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") reconnectNow();
});
$("overlay").addEventListener("click", reconnectNow);

function onJson(msg) {
  switch (msg.t) {
    case "hello": {
      const sel = $("monitor");
      sel.innerHTML = "";
      for (const m of msg.monitors) {
        const o = document.createElement("option");
        o.value = m.index;
        o.textContent = m.label;
        sel.appendChild(o);
      }
      sel.value = msg.cfg.monitor;
      showStatus(msg.status);
      break;
    }
    case "cfg":
      $("monitor").value = msg.cfg.monitor;
      break;
    case "cursor":
      lastCursor = msg;
      placeCursor();
      break;
    case "clip":
      $("clip-text").value = msg.s;
      $("clip-text").select();
      toast(msg.s ? "Uzak pano alındı — Ctrl+C ile kopyalayın" : "Uzak pano boş");
      break;
    case "info":
      toast(msg.msg);
      break;
    case "locked":
      overlay(msg.v
        ? "Uzak bilgisayar kilitli veya bir UAC onay penceresi açık.\n" +
          "Bu ekran uzaktan kontrol edilemez (README: \"Kilit ekranı\" bölümü)."
        : "");
      break;
  }
}

// Bekçinin raporu: çözemediği sorunlar kalıcı uyarı, onardıkları kısa bilgi olarak
function showStatus(status) {
  const warnings = (status && status.warnings) || [];
  $("banner").textContent = warnings.map((w) => `⚠ ${w}`).join("\n");
  $("banner").hidden = warnings.length === 0;
  const actions = (status && status.actions) || [];
  if (actions.length) {
    const at = new Date(status.checked_at).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    toast(`Bekçi (${at}): ${actions.join("; ")}`, 6000);
  }
}
$("banner").addEventListener("click", () => ($("banner").hidden = true));

// ---------------------------------------------------------------- görüntü
async function onFrame(buf) {
  stats.frames++;
  stats.bytes += buf.byteLength;
  const dv = new DataView(buf);
  const kind = dv.getUint8(0);
  const w = dv.getUint16(1, true);
  const h = dv.getUint16(3, true);
  const count = dv.getUint16(5, true);
  let off = 7;
  const tiles = [];
  for (let i = 0; i < count; i++) {
    const x = dv.getUint16(off, true), y = dv.getUint16(off + 2, true);
    const len = dv.getUint32(off + 8, true);
    off += 12;
    tiles.push({ x, y, blob: new Blob([new Uint8Array(buf, off, len)], { type: "image/jpeg" }) });
    off += len;
  }
  try {
    const bitmaps = await Promise.all(tiles.map((t) => createImageBitmap(t.blob)));
    if (kind === 1 || canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      fitCanvas();
    }
    bitmaps.forEach((bm, i) => {
      ctx.drawImage(bm, tiles[i].x, tiles[i].y);
      bm.close();
    });
    overlay("");
  } catch (err) {
    console.error(err);
    send({ t: "key" });
  }
  send({ t: "ack" });
}

function fitCanvas() {
  const stage = $("stage").getBoundingClientRect();
  if (!canvas.width || !stage.width) return;
  const s = Math.min(stage.width / canvas.width, stage.height / canvas.height);
  canvas.style.width = `${Math.floor(canvas.width * s)}px`;
  canvas.style.height = `${Math.floor(canvas.height * s)}px`;
  placeCursor();
}
new ResizeObserver(fitCanvas).observe($("stage"));

function placeCursor() {
  const el = $("cursor");
  if (!lastCursor || lastCursor.x < 0 || lastCursor.x > 1 || lastCursor.y < 0 || lastCursor.y > 1) {
    el.hidden = true;
    return;
  }
  const c = canvas.getBoundingClientRect();
  const s = $("stage").getBoundingClientRect();
  el.style.left = `${c.left - s.left + lastCursor.x * c.width}px`;
  el.style.top = `${c.top - s.top + lastCursor.y * c.height}px`;
  el.hidden = false;
}

setInterval(() => {
  if (!ws) return;
  $("status").textContent = `${stats.frames} kare/sn · ${Math.round(stats.bytes / 1024)} KB/sn`;
  stats.frames = 0;
  stats.bytes = 0;
}, 1000);

// ---------------------------------------------------------------- ayarlar
function savedMonitor() {
  try { return localStorage.getItem("ra-monitor"); } catch { return null; }
}

function applyQuality() {
  const cfg = { t: "cfg", ...PRESETS[$("quality").value] };
  // Liste henüz dolmadıysa son seçilen ekranı iste; o da yoksa sunucu ana ekranı seçer
  const mon = $("monitor").value || savedMonitor();
  if (mon) cfg.monitor = Number(mon);
  send(cfg);
}
$("quality").addEventListener("change", () => {
  try { localStorage.setItem("ra-quality", $("quality").value); } catch { /* yok say */ }
  applyQuality();
});
$("monitor").addEventListener("change", () => {
  try { localStorage.setItem("ra-monitor", $("monitor").value); } catch { /* yok say */ }
  applyQuality();
});
try {
  const q = localStorage.getItem("ra-quality");
  if (q && PRESETS[q]) $("quality").value = q;
} catch { /* yok say */ }

$("btn-full").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => toast("Tam ekran desteklenmiyor"));
});
$("btn-hide").addEventListener("click", () => { $("toolbar").hidden = true; $("btn-show").hidden = false; });
$("btn-show").addEventListener("click", () => { $("toolbar").hidden = false; $("btn-show").hidden = true; });

document.querySelectorAll("[data-combo]").forEach((b) =>
  b.addEventListener("click", () => {
    send({ t: "combo", c: b.dataset.combo.split(",") });
    canvas.focus();
  }),
);

// ---------------------------------------------------------------- fare / kalem / dokunma
const BUTTONS = ["left", "middle", "right"];

function norm(e) {
  const r = canvas.getBoundingClientRect();
  return {
    x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
    y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
  };
}

let pendingMove = null;
function queueMove(p) {
  if (!pendingMove) {
    requestAnimationFrame(() => {
      send({ t: "mm", ...pendingMove });
      pendingMove = null;
    });
  }
  pendingMove = p;
}

// Dokunma durumu: tek dokunuş = tık, basılı tut = sağ tık, sürükle = sürükle,
// iki parmak = kaydırma
const touches = new Map();
let touchMode = null; // null | "tap" | "drag" | "scroll"
let longPressTimer = null;
let scrollLastY = 0, scrollLastX = 0;

function touchCenter() {
  let x = 0, y = 0;
  for (const t of touches.values()) { x += t.x; y += t.y; }
  return { x: x / touches.size, y: y / touches.size };
}

canvas.addEventListener("contextmenu", (e) => e.preventDefault());

canvas.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  canvas.focus();
  if (e.pointerType !== "touch") {
    canvas.setPointerCapture(e.pointerId);
    const b = BUTTONS[e.button];
    if (b) send({ t: "mb", b, d: true, ...norm(e) });
    return;
  }
  touches.set(e.pointerId, { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, t: performance.now() });
  canvas.setPointerCapture(e.pointerId);
  clearTimeout(longPressTimer);
  if (touches.size === 1) {
    touchMode = "tap";
    const p = norm(e);
    queueMove(p);
    longPressTimer = setTimeout(() => {
      if (touchMode === "tap") {
        touchMode = "done";
        send({ t: "mb", b: "right", d: true, ...p });
        send({ t: "mb", b: "right", d: false, ...p });
        navigator.vibrate?.(30);
      }
    }, 600);
  } else if (touches.size === 2) {
    if (touchMode === "drag") send({ t: "mb", b: "left", d: false });
    touchMode = "scroll";
    const c = touchCenter();
    scrollLastX = c.x;
    scrollLastY = c.y;
  }
});

canvas.addEventListener("pointermove", (e) => {
  if (e.pointerType !== "touch") {
    queueMove(norm(e));
    return;
  }
  const t = touches.get(e.pointerId);
  if (!t) return;
  t.x = e.clientX;
  t.y = e.clientY;
  if (touchMode === "tap" && Math.hypot(t.x - t.sx, t.y - t.sy) > 12) {
    clearTimeout(longPressTimer);
    touchMode = "drag";
    const start = norm({ clientX: t.sx, clientY: t.sy });
    send({ t: "mb", b: "left", d: true, ...start });
  }
  if (touchMode === "drag") queueMove(norm(e));
  if (touchMode === "scroll") {
    const c = touchCenter();
    const dy = Math.round((c.y - scrollLastY) * 3);
    const dx = Math.round((scrollLastX - c.x) * 3);
    if (Math.abs(dy) >= 10 || Math.abs(dx) >= 10) {
      send({ t: "wh", dy, dx });
      scrollLastX = c.x;
      scrollLastY = c.y;
    }
  }
});

function endPointer(e) {
  if (e.pointerType !== "touch") {
    const b = BUTTONS[e.button];
    if (b) send({ t: "mb", b, d: false, ...norm(e) });
    return;
  }
  if (!touches.has(e.pointerId)) return;
  touches.delete(e.pointerId);
  clearTimeout(longPressTimer);
  if (touchMode === "tap" && e.type === "pointerup") {
    const p = norm(e);
    send({ t: "mb", b: "left", d: true, ...p });
    send({ t: "mb", b: "left", d: false, ...p });
    touchMode = "done";
  } else if (touchMode === "drag") {
    send({ t: "mb", b: "left", d: false, ...norm(e) });
    touchMode = "done";
  }
  if (touches.size === 0) touchMode = null;
}
canvas.addEventListener("pointerup", endPointer);
canvas.addEventListener("pointercancel", endPointer);

let wheelAcc = { dx: 0, dy: 0 };
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const unit = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? 800 : 1;
  wheelAcc.dy -= e.deltaY * unit * 1.2;
  wheelAcc.dx += e.deltaX * unit * 1.2;
  if (!wheelAcc.pending) {
    wheelAcc.pending = true;
    requestAnimationFrame(() => {
      send({ t: "wh", dy: Math.round(wheelAcc.dy), dx: Math.round(wheelAcc.dx) });
      wheelAcc = { dx: 0, dy: 0 };
    });
  }
}, { passive: false });

// ---------------------------------------------------------------- klavye
// Değiştirici tuşlar (Ctrl/Alt/Shift/Win) hemen gönderilmez: bir kısayolda
// kullanılırsa (Ctrl+C gibi) o anda basılır. Böylece AltGr+Q ile "@" yazmak veya
// Shift+a ile "A" yazmak, karşı tarafta istenmeyen Ctrl/Alt basışı üretmez.
const heldMods = new Map(); // code -> { sent: bool, used: bool }
const sentKeys = new Set(); // karşıya "basıldı" olarak gönderilen normal tuşlar

function flushModifiers() {
  for (const [code, st] of heldMods) {
    if (!st.sent) {
      send({ t: "k", c: code, d: true });
      st.sent = true;
    }
  }
}

function releaseModifiers() {
  for (const [code, st] of heldMods) if (st.sent) send({ t: "k", c: code, d: false });
  for (const code of sentKeys) send({ t: "k", c: code, d: false });
  heldMods.clear();
  sentKeys.clear();
  send({ t: "rel" });
}

function remoteActive() {
  return !$("remote").hidden && !$("clip-dialog").open && ws;
}

function ownsKeys(e) {
  // Açılır listeler gibi arayüz öğeleri kendi tuşlarını kullansın
  return remoteActive() && !(e.target instanceof HTMLSelectElement);
}

document.addEventListener("keydown", (e) => {
  if (!ownsKeys(e)) return;
  if (e.isComposing || e.key === "Process" || e.key === "Unidentified" || e.key === "Dead") return;
  e.preventDefault();

  if (MODIFIERS.has(e.code)) {
    if (!heldMods.has(e.code)) heldMods.set(e.code, { sent: false, used: false });
    return;
  }
  for (const st of heldMods.values()) st.used = true;

  const altGr = e.getModifierState && e.getModifierState("AltGraph");
  const shortcut = (e.ctrlKey || e.altKey || e.metaKey) && !altGr;
  if (e.key.length === 1 && !shortcut) {
    send({ t: "txt", s: e.key });
    return;
  }
  flushModifiers();
  sentKeys.add(e.code);
  send({ t: "k", c: e.code, d: true });
});

document.addEventListener("keyup", (e) => {
  if (!ownsKeys(e)) return;
  e.preventDefault();
  if (MODIFIERS.has(e.code)) {
    const st = heldMods.get(e.code);
    heldMods.delete(e.code);
    if (!st) return;
    if (st.sent) send({ t: "k", c: e.code, d: false });
    else if (!st.used) {
      // Tek başına basılıp bırakıldı (örn. Win tuşu → Başlat menüsü)
      send({ t: "k", c: e.code, d: true });
      send({ t: "k", c: e.code, d: false });
    }
    return;
  }
  if (sentKeys.delete(e.code)) send({ t: "k", c: e.code, d: false });
});

window.addEventListener("blur", () => { if (ws) releaseModifiers(); });

// Dokunmatik klavye: gizli textarea'ya odaklan, "input" olaylarını metin olarak gönder
$("btn-kbd").addEventListener("click", () => {
  const k = $("kbd");
  k.value = "";
  k.focus();
});
$("kbd").addEventListener("input", (e) => {
  const k = e.target;
  if (k.value) {
    send({ t: "txt", s: k.value });
    k.value = "";
  }
});

// ---------------------------------------------------------------- pano
$("btn-clip").addEventListener("click", () => {
  releaseModifiers();
  $("clip-dialog").showModal();
});
$("clip-get").addEventListener("click", () => send({ t: "clip_get" }));
$("clip-set").addEventListener("click", () => send({ t: "clip_set", s: $("clip-text").value }));
$("clip-type").addEventListener("click", () => {
  send({ t: "txt", s: $("clip-text").value });
  $("clip-dialog").close();
});

// ---------------------------------------------------------------- başlat
(async () => {
  try {
    if (await checkSession()) startRemote();
    else showView("login");
  } catch {
    showView("login");
    $("login-error").textContent = "Sunucuya ulaşılamıyor.";
  }
})();
