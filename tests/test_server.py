import asyncio
import json

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from remote_agent.capture import HEADER, KEYFRAME, DemoSource
from remote_agent.config import Config, hash_password
from remote_agent.input_win import RecordingBackend
from remote_agent.server import LoginLimiter, create_app

PASSWORD = "cok-gizli-parola"


def make_client():
    cfg = Config(name="Test", password_hash=hash_password(PASSWORD, iterations=1000))
    backend = RecordingBackend()
    app = create_app(cfg, DemoSource(640, 360), backend)
    return TestClient(TestServer(app)), backend


def run(coro):
    return asyncio.run(coro)


def test_limiter_locks_and_resets():
    lim = LoginLimiter(free_attempts=3, base_lock=10)
    for _ in range(2):
        lim.failure("1.2.3.4", now=0)
    assert lim.retry_after("1.2.3.4", now=0) == 0
    lim.failure("1.2.3.4", now=0)
    assert lim.retry_after("1.2.3.4", now=0) == 10
    lim.failure("1.2.3.4", now=0)
    assert lim.retry_after("1.2.3.4", now=0) == 20
    lim.success("1.2.3.4")
    assert lim.retry_after("1.2.3.4", now=0) == 0


def test_login_ws_stream_and_input():
    async def scenario():
        client, backend = make_client()
        async with client:
            r = await client.get("/api/session")
            assert (await r.json())["authenticated"] is False
            assert "Content-Security-Policy" in r.headers

            # Kimliksiz WebSocket reddedilir
            r = await client.get("/ws")
            assert r.status == 401

            r = await client.post("/api/login", json={"password": "yanlis"})
            assert r.status == 401
            r = await client.post("/api/login", json={"password": PASSWORD})
            assert r.status == 200
            assert (await (await client.get("/api/session")).json())["authenticated"]

            base = str(client.make_url("/"))[:-1]
            # Yabancı Origin reddedilir
            r = await client.get("/ws", headers={"Origin": "http://evil.example"})
            assert r.status == 403

            ws = await client.ws_connect("/ws", origin=base)
            hello = json.loads((await ws.receive(timeout=5)).data)
            assert hello["t"] == "hello" and len(hello["monitors"]) == 3

            await ws.send_str(json.dumps({"t": "cfg", "monitor": 1, "max_width": 320}))
            got_key = False
            for _ in range(10):
                msg = await ws.receive(timeout=5)
                if msg.type == WSMsgType.BINARY:
                    kind, w, h, _ = HEADER.unpack_from(msg.data, 0)
                    await ws.send_str('{"t":"ack"}')
                    if kind == KEYFRAME and w == 320:
                        assert h == 180
                        got_key = True
                        break
            assert got_key

            await ws.send_str(json.dumps({"t": "mb", "b": "left", "d": True, "x": 0.5, "y": 1.0}))
            await ws.send_str(json.dumps({"t": "k", "c": "ControlLeft", "d": True}))
            await ws.send_str(json.dumps({"t": "txt", "s": "Merhaba ğüşİ"}))
            await ws.send_str(json.dumps({"t": "clip_set", "s": "pano"}))
            await ws.send_str(json.dumps({"t": "clip_get"}))
            for _ in range(30):
                msg = await ws.receive(timeout=5)
                if msg.type == WSMsgType.BINARY:
                    await ws.send_str('{"t":"ack"}')
                    continue
                data = json.loads(msg.data)
                if data["t"] == "clip":
                    assert data["s"] == "pano"
                    break
            await ws.close()
            await asyncio.sleep(0.1)

            # Ekran 1: 640x360, (0.5, 1.0) -> (320, 359)
            assert ("move", 320, 359) in backend.events
            assert ("button", "left", True) in backend.events
            assert ("text", "Merhaba ğüşİ") in backend.events
            # Bağlantı kapanınca basılı kalan tuş ve düğme bırakılır
            assert ("key", 0xA2, False) in backend.events
            assert ("button", "left", False) in backend.events
            assert not backend.pressed_keys and not backend.pressed_buttons

            r = await client.post("/api/logout")
            assert r.status == 200
            assert not (await (await client.get("/api/session")).json())["authenticated"]

    run(scenario())


def test_login_rate_limit():
    async def scenario():
        client, _ = make_client()
        async with client:
            for _ in range(5):
                await client.post("/api/login", json={"password": "yanlis"})
            r = await client.post("/api/login", json={"password": PASSWORD})
            assert r.status == 429

    run(scenario())


def test_locked_desktop_notifies_client(monkeypatch):
    from remote_agent import winutil

    monkeypatch.setattr(winutil, "input_desktop_locked", lambda: True)

    async def scenario():
        client, _ = make_client()
        async with client:
            await client.post("/api/login", json={"password": PASSWORD})
            base = str(client.make_url("/"))[:-1]
            ws = await client.ws_connect("/ws", origin=base)
            seen = []
            for _ in range(3):
                msg = await ws.receive(timeout=5)
                assert msg.type == WSMsgType.TEXT  # kilitliyken görüntü gönderilmez
                seen.append(json.loads(msg.data))
                if seen[-1]["t"] == "locked":
                    break
            assert seen[-1] == {"t": "locked", "v": True}
            await ws.close()

    run(scenario())


def test_ping_pong():
    async def scenario():
        client, _ = make_client()
        async with client:
            await client.post("/api/login", json={"password": PASSWORD})
            base = str(client.make_url("/"))[:-1]
            ws = await client.ws_connect("/ws", origin=base)
            await ws.send_str('{"t":"ping"}')
            for _ in range(20):
                msg = await ws.receive(timeout=5)
                if msg.type == WSMsgType.BINARY:
                    await ws.send_str('{"t":"ack"}')
                elif json.loads(msg.data)["t"] == "pong":
                    break
            else:
                raise AssertionError("pong gelmedi")
            await ws.close()

    run(scenario())


def test_hello_carries_watchdog_warnings(tmp_path):
    import datetime as dt

    status = tmp_path / "status.json"
    status.write_text(json.dumps({
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "tailscale": "Running", "warnings": ["dikkat"], "actions": [],
    }), encoding="utf-8")

    async def scenario():
        cfg = Config(name="Test", password_hash=hash_password(PASSWORD, iterations=1000))
        client = TestClient(TestServer(create_app(cfg, DemoSource(64, 36), RecordingBackend(), status)))
        async with client:
            await client.post("/api/login", json={"password": PASSWORD})
            ws = await client.ws_connect("/ws", origin=str(client.make_url("/"))[:-1])
            hello = json.loads((await ws.receive(timeout=5)).data)
            assert hello["status"]["warnings"] == ["dikkat"]
            await ws.close()

    run(scenario())
