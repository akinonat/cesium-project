"""HTTP + WebSocket sunucusu: giriş, ekran yayını ve girdi iletimi."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

from . import winutil
from .capture import FrameEncoder, Monitor, scale_to_width
from .config import Config, verify_password
from .input_win import InputBackend
from .watchdog import read_status

log = logging.getLogger("remote_agent")

STATIC_DIR = Path(__file__).parent / "static"
COOKIE = "ra_session"
MAX_INFLIGHT = 2
CFG_KEY = web.AppKey("cfg", Config)
STATUS_KEY = web.AppKey("status_path", object)
STATE_KEY = web.AppKey("state", "AppState")


class LoginLimiter:
    """IP başına başarısız denemeleri sayar; 5 hatadan sonra katlanarak artan kilit."""

    def __init__(self, free_attempts: int = 5, base_lock: float = 30.0, max_lock: float = 3600.0):
        self.free_attempts = free_attempts
        self.base_lock = base_lock
        self.max_lock = max_lock
        self._fails: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def retry_after(self, ip: str, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        return max(0.0, self._locked_until.get(ip, 0.0) - now)

    def failure(self, ip: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        n = self._fails.get(ip, 0) + 1
        self._fails[ip] = n
        if n >= self.free_attempts:
            lock = min(self.max_lock, self.base_lock * 2 ** (n - self.free_attempts))
            self._locked_until[ip] = now + lock

    def success(self, ip: str) -> None:
        self._fails.pop(ip, None)
        self._locked_until.pop(ip, None)


class SessionStore:
    def __init__(self, lifetime_s: float):
        self.lifetime_s = lifetime_s
        self._sessions: dict[str, float] = {}

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = time.monotonic() + self.lifetime_s
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        exp = self._sessions.get(token)
        if exp is None:
            return False
        if exp < time.monotonic():
            del self._sessions[token]
            return False
        return True

    def revoke(self, token: str | None) -> None:
        self._sessions.pop(token or "", None)


@dataclass
class AppState:
    source: object
    backend: InputBackend
    sessions: SessionStore
    limiter: LoginLimiter = field(default_factory=LoginLimiter)
    auth_pool: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(1, thread_name_prefix="auth")
    )
    active_streams: int = 0


# --- Yardımcılar -------------------------------------------------------------------

def _clamp(v, lo, hi, default):
    try:
        v = type(default)(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _same_origin(request: web.Request) -> bool:
    """WebSocket çapraz site ele geçirmesine karşı Origin == Host kontrolü."""
    origin = request.headers.get("Origin")
    if not origin:
        return False
    allowed = {request.host.lower()}
    # Aynı makinedeki ters vekil (ör. "tailscale serve") Host başlığını değiştirebilir
    if request.remote in ("127.0.0.1", "::1") and "X-Forwarded-Host" in request.headers:
        allowed.add(request.headers["X-Forwarded-Host"].lower())
    return urlsplit(origin).netloc.lower() in allowed


def _authed(request: web.Request) -> bool:
    return request.app[STATE_KEY].sessions.valid(request.cookies.get(COOKIE))


@web.middleware
async def security_headers(request: web.Request, handler):
    resp = await handler(request)
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' blob: data:; connect-src 'self' ws: wss:; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'",
    )
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# --- HTTP uçları ---------------------------------------------------------------------

async def index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def api_session(request: web.Request) -> web.Response:
    cfg = request.app[CFG_KEY]
    return web.json_response({"authenticated": _authed(request), "name": cfg.name})


async def api_login(request: web.Request) -> web.Response:
    state = request.app[STATE_KEY]
    cfg = request.app[CFG_KEY]
    ip = request.remote or "?"

    wait = state.limiter.retry_after(ip)
    if wait > 0:
        return web.json_response(
            {"error": f"Çok fazla hatalı deneme. {int(wait) + 1} sn sonra tekrar deneyin."},
            status=429,
        )
    try:
        body = await request.json()
        password = str(body.get("password", ""))
    except (json.JSONDecodeError, AttributeError):
        return web.json_response({"error": "Geçersiz istek"}, status=400)

    ok = await asyncio.get_running_loop().run_in_executor(
        state.auth_pool, verify_password, password[:1024], cfg.password_hash
    )
    if not ok:
        state.limiter.failure(ip)
        log.warning("Hatalı parola denemesi: %s", ip)
        return web.json_response({"error": "Parola hatalı"}, status=401)

    state.limiter.success(ip)
    log.info("Giriş başarılı: %s", ip)
    resp = web.json_response({"ok": True})
    resp.set_cookie(
        COOKIE, state.sessions.create(), httponly=True, samesite="Strict",
        secure=request.secure, max_age=int(state.sessions.lifetime_s), path="/",
    )
    return resp


async def api_logout(request: web.Request) -> web.Response:
    request.app[STATE_KEY].sessions.revoke(request.cookies.get(COOKIE))
    resp = web.json_response({"ok": True})
    resp.del_cookie(COOKIE, path="/")
    return resp


# --- WebSocket: yayın + girdi ---------------------------------------------------------

class StreamSession:
    def __init__(self, ws: web.WebSocketResponse, state: AppState, cfg: Config,
                 status_path: Path | None = None):
        self.ws = ws
        self.status_path = status_path
        self.state = state
        self.source = state.source
        self.backend = state.backend
        self.monitors: list[Monitor] = self.source.monitors()
        self.monitor = next(
            (m.index for m in self.monitors if m.primary), 1 if len(self.monitors) > 1 else 0
        )
        self.fps = cfg.fps
        self.quality = cfg.quality
        self.max_width = cfg.max_width
        self.inflight = 0
        self.acked = asyncio.Event()
        self.need_key = True
        self.encoder = FrameEncoder()
        self.grabber = ThreadPoolExecutor(1, thread_name_prefix="grab")
        self.last_cursor = None
        self.locked = False
        self.lock_checked = 0.0

    # Yakalama iş parçacığında çalışır
    def _produce(self) -> bytes | None:
        if self.need_key:
            self.need_key = False
            self.encoder.reset()
        img = self.source.grab(self.monitor)
        img = scale_to_width(img, self.max_width)
        return self.encoder.encode(img, self.quality)

    async def send_json(self, obj) -> None:
        if not self.ws.closed:
            await self.ws.send_str(json.dumps(obj, ensure_ascii=False))

    def hello(self) -> dict:
        return {
            "t": "hello",
            "monitors": [m.as_dict() for m in self.monitors],
            "cfg": self.cfg_dict(),
            # Bekçinin son raporu: uyarılar (ör. Tailscale anahtarı dolmak üzere)
            "status": read_status(self.status_path) if self.status_path else None,
        }

    def cfg_dict(self) -> dict:
        return {"monitor": self.monitor, "fps": self.fps, "quality": self.quality,
                "max_width": self.max_width}

    async def frame_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self.ws.closed:
            started = loop.time()
            if started - self.lock_checked >= 1.0:
                self.lock_checked = started
                locked = winutil.input_desktop_locked()
                if locked != self.locked:
                    self.locked = locked
                    self.need_key = True
                    await self.send_json({"t": "locked", "v": locked})
            if self.locked:
                await asyncio.sleep(0.5)
                continue
            if self.inflight >= MAX_INFLIGHT:
                self.acked.clear()
                try:
                    await asyncio.wait_for(self.acked.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self.inflight = 0  # istemci yanıt vermedi: baştan başla
                    self.need_key = True
                continue
            try:
                data = await loop.run_in_executor(self.grabber, self._produce)
            except Exception:  # ekran kilitli / UAC vb. geçici hatalar
                log.exception("Ekran yakalanamadı")
                await asyncio.sleep(1)
                self.need_key = True
                continue
            if data and not self.ws.closed:
                await self.ws.send_bytes(data)
                self.inflight += 1
            await self._send_cursor()
            delay = 1 / self.fps - (loop.time() - started)
            await asyncio.sleep(max(0.005, delay))

    async def _send_cursor(self) -> None:
        pos = self.backend.cursor_pos()
        if pos is None or pos == self.last_cursor:
            return
        self.last_cursor = pos
        mon = self._mon()
        await self.send_json({
            "t": "cursor",
            "x": (pos[0] - mon.left) / mon.width,
            "y": (pos[1] - mon.top) / mon.height,
        })

    def _mon(self) -> Monitor:
        return self.monitors[self.monitor]

    def _to_screen(self, msg: dict) -> tuple[int, int]:
        mon = self._mon()
        nx = _clamp(msg.get("x"), 0.0, 1.0, 0.0)
        ny = _clamp(msg.get("y"), 0.0, 1.0, 0.0)
        return (mon.left + round(nx * (mon.width - 1)), mon.top + round(ny * (mon.height - 1)))

    async def handle(self, msg: dict) -> None:
        t = msg.get("t")
        b = self.backend
        if t == "ping":
            await self.send_json({"t": "pong"})
        elif t == "ack":
            self.inflight = max(0, self.inflight - 1)
            self.acked.set()
        elif t == "mm":
            b.move(*self._to_screen(msg))
        elif t == "mb":
            if "x" in msg:
                b.move(*self._to_screen(msg))
            b.button(str(msg.get("b")), bool(msg.get("d")))
        elif t == "wh":
            b.wheel(_clamp(msg.get("dy"), -2400, 2400, 0), _clamp(msg.get("dx"), -2400, 2400, 0))
        elif t == "k":
            b.key(str(msg.get("c")), bool(msg.get("d")))
        elif t == "combo":
            codes = msg.get("c")
            if isinstance(codes, list):
                b.combo([str(c) for c in codes[:6]])
        elif t == "rel":
            b.release_all()
        elif t == "txt":
            b.text(str(msg.get("s", "")))
        elif t == "key":
            self.need_key = True
        elif t == "cfg":
            self.monitors = self.source.monitors()
            self.monitor = _clamp(msg.get("monitor", self.monitor), 0, len(self.monitors) - 1, 1)
            self.fps = _clamp(msg.get("fps", self.fps), 1, 30, 15)
            self.quality = _clamp(msg.get("quality", self.quality), 10, 95, 60)
            self.max_width = _clamp(msg.get("max_width", self.max_width), 0, 7680, 1920)
            self.need_key = True
            self.last_cursor = None
            await self.send_json({"t": "cfg", "cfg": self.cfg_dict()})
        elif t == "clip_get":
            text = await asyncio.get_running_loop().run_in_executor(None, winutil.get_clipboard)
            await self.send_json({"t": "clip", "s": text})
        elif t == "clip_set":
            ok = await asyncio.get_running_loop().run_in_executor(
                None, winutil.set_clipboard, str(msg.get("s", ""))[:1_000_000]
            )
            await self.send_json({"t": "info", "msg": "Pano güncellendi" if ok else "Pano açılamadı"})

    def close(self) -> None:
        self.backend.release_all()  # takılı kalan Ctrl/Shift veya fare düğmesi olmasın
        self.grabber.shutdown(wait=False)


async def ws_handler(request: web.Request) -> web.StreamResponse:
    if not _authed(request):
        raise web.HTTPUnauthorized()
    if not _same_origin(request):
        raise web.HTTPForbidden(text="Origin reddedildi")

    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=2 * 1024 * 1024)
    await ws.prepare(request)
    state = request.app[STATE_KEY]
    session = StreamSession(ws, state, request.app[CFG_KEY], request.app[STATUS_KEY])
    state.active_streams += 1
    log.info("Uzak oturum başladı: %s", request.remote)
    await session.send_json(session.hello())
    sender = asyncio.create_task(session.frame_loop())
    try:
        async for raw in ws:
            if raw.type == WSMsgType.TEXT:
                try:
                    msg = json.loads(raw.data)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict):
                    await session.handle(msg)
            elif raw.type == WSMsgType.ERROR:
                break
            if not state.sessions.valid(request.cookies.get(COOKIE)):
                break  # oturum süresi doldu veya çıkış yapıldı
    finally:
        sender.cancel()
        session.close()
        state.active_streams -= 1
        log.info("Uzak oturum bitti: %s", request.remote)
    return ws


def create_app(cfg: Config, source, backend: InputBackend,
               status_path: Path | None = None) -> web.Application:
    app = web.Application(middlewares=[security_headers], client_max_size=64 * 1024)
    app[CFG_KEY] = cfg
    app[STATUS_KEY] = status_path
    app[STATE_KEY] = AppState(source, backend, SessionStore(cfg.session_hours * 3600))
    app.router.add_get("/", index)
    app.router.add_get("/api/session", api_session)
    app.router.add_post("/api/login", api_login)
    app.router.add_post("/api/logout", api_logout)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/static", STATIC_DIR)
    return app
