import datetime as dt
import json

import pytest

from remote_agent import watchdog
from remote_agent.config import Config

NOW = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def env(monkeypatch):
    """Dış komutları taklit eder; çalıştırılan komutları kaydeder."""
    state = {"ts": {"BackendState": "Running", "Self": {}}, "alive": True, "cmds": []}
    monkeypatch.setattr(watchdog, "tailscale_status", lambda: state["ts"])
    monkeypatch.setattr(watchdog, "agent_alive", lambda cfg: state["alive"])
    monkeypatch.setattr(watchdog, "run", lambda cmd, timeout=30: state["cmds"].append(cmd[1:]))
    monkeypatch.setattr(watchdog.time, "sleep", lambda s: None)
    return state


def test_all_good(env):
    r = watchdog.check(Config(), NOW)
    assert r["warnings"] == [] and r["actions"] == [] and env["cmds"] == []


def test_restarts_dead_agent(env):
    env["alive"] = False
    r = watchdog.check(Config(), NOW)
    assert r["actions"] == ["Ajan yanıt vermiyordu, yeniden başlatıldı"]
    assert env["cmds"] == [["/End", "/TN", "RemoteAgent"], ["/Run", "/TN", "RemoteAgent"]]


def test_brings_stopped_tailscale_up(env):
    env["ts"] = {"BackendState": "Stopped"}
    r = watchdog.check(Config(), NOW)
    assert ["up"] in env["cmds"] and "Tailscale kapatılmıştı" in r["actions"][0]


def test_needs_login_is_warning(env):
    env["ts"] = {"BackendState": "NeedsLogin"}
    r = watchdog.check(Config(), NOW)
    assert "yeniden giriş" in r["warnings"][0] and r["actions"] == []


def test_key_expiry_warning(env):
    env["ts"]["Self"]["KeyExpiry"] = "2026-10-05T12:00:00Z"  # 8 gün kaldı
    r = watchdog.check(Config(), NOW)
    assert "8 gün" in r["warnings"][0]
    env["ts"]["Self"]["KeyExpiry"] = "2027-06-01T00:00:00Z"
    assert watchdog.check(Config(), NOW)["warnings"] == []
    env["ts"]["Self"]["KeyExpiry"] = "0001-01-01T00:00:00Z"  # süresiz
    assert watchdog.check(Config(), NOW)["warnings"] == []


def test_tailscale_missing(env, monkeypatch):
    monkeypatch.setattr(watchdog, "tailscale_status", lambda: None)
    r = watchdog.check(Config(), NOW)
    assert ["start", "Tailscale"] in env["cmds"]
    assert "yanıt vermiyor" in r["warnings"][0]


def test_main_writes_status_and_agent_reads_it(env, tmp_path):
    env["ts"] = {"BackendState": "NeedsLogin"}
    watchdog.main(["--config-dir", str(tmp_path)])
    data = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert data["tailscale"] == "NeedsLogin"
    assert watchdog.read_status(tmp_path / "status.json")["warnings"] == data["warnings"]
    assert "UYARI" in (tmp_path / "watchdog.log").read_text(encoding="utf-8")
    # Bir saatten eski rapor gösterilmez
    data["checked_at"] = "2020-01-01T00:00:00+00:00"
    (tmp_path / "status.json").write_text(json.dumps(data), encoding="utf-8")
    assert watchdog.read_status(tmp_path / "status.json") is None
