"""Bekçi: "bilgisayar açık ama uzaktan bağlanılamıyor" durumlarını onarır.

Zamanlanmış Görev ile her 5 dakikada bir, pencere açmadan (pythonw) çalışır:

    pythonw -m remote_agent.watchdog --config-dir C:\\ProgramData\\RemoteAgent

- Tailscale hizmeti durmuşsa başlatır, Tailscale kapatılmışsa yeniden açar
- Ajan yanıt vermiyorsa (çökmüş veya donmuş) görevini yeniden başlatır
- Kendi çözemediği sorunları (Tailscale'in yeniden giriş istemesi, anahtar
  süresinin dolmak üzere olması) status.json'a yazar; ajan bunları bağlandığınızda
  uyarı olarak gösterir. Böylece sorun çıkmadan dışarıdayken haberiniz olur.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import ssl
import subprocess
import sys
import time
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import Config, default_config_dir

AGENT_TASK = "RemoteAgent"
KEY_EXPIRY_WARN_DAYS = 14
STATUS_FILE = "status.json"
CREATE_NO_WINDOW = 0x08000000

log = logging.getLogger("remote_agent.watchdog")


def _tailscale_exe() -> str:
    exe = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
    return str(exe) if exe.exists() else "tailscale"


def run(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess | None:
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Komut çalışmadı %s: %s", cmd, exc)
        return None


def tailscale_status() -> dict | None:
    r = run([_tailscale_exe(), "status", "--json"])
    if r is None:
        return None
    try:
        return json.loads(r.stdout)  # durdurulmuşken de JSON verir (çıkış kodu 0 olmasa bile)
    except ValueError:
        return None


def agent_alive(cfg: Config) -> bool:
    scheme = "https" if cfg.tls else "http"
    ctx = ssl._create_unverified_context() if cfg.tls else None  # yerel, kendinden imzalı
    try:
        with urllib.request.urlopen(
            f"{scheme}://127.0.0.1:{cfg.port}/api/session", timeout=10, context=ctx
        ) as resp:
            return resp.status == 200
    except OSError:
        return False


def restart_agent() -> None:
    run(["schtasks", "/End", "/TN", AGENT_TASK])
    time.sleep(3)
    run(["schtasks", "/Run", "/TN", AGENT_TASK])


def _days_left(expiry: str | None, now: dt.datetime) -> float | None:
    if not expiry:
        return None
    try:
        when = dt.datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.year < 2000:  # "süresiz" düğümlerde sıfır tarih gelir
        return None
    return (when - now).total_seconds() / 86400


def check(cfg: Config, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    warnings: list[str] = []
    actions: list[str] = []

    st = tailscale_status()
    if st is None:
        # Hizmet durmuş olabilir; zaten çalışıyorsa bu komut zararsızca hata verir
        run(["net", "start", "Tailscale"])
        time.sleep(10)
        st = tailscale_status()
        if st is not None:
            actions.append("Tailscale hizmeti durmuştu, başlatıldı")
    state = (st or {}).get("BackendState")

    if st is None:
        warnings.append("Tailscale yanıt vermiyor veya kurulu değil: dışarıdan erişim çalışmaz.")
    elif state == "Stopped":
        run([_tailscale_exe(), "up"])
        actions.append("Tailscale kapatılmıştı, yeniden açıldı")
    elif state == "NeedsLogin":
        warnings.append(
            "Tailscale yeniden giriş istiyor: dışarıdan erişim çalışmaz. Ofis bilgisayarında "
            "Tailscale'e giriş yapın ve yönetim panelinde 'Disable key expiry' seçin."
        )
    elif state and state != "Running":
        warnings.append(f"Tailscale durumu olağan dışı: {state}")

    days = _days_left(((st or {}).get("Self") or {}).get("KeyExpiry"), now)
    if days is not None and days < KEY_EXPIRY_WARN_DAYS:
        warnings.append(
            f"Tailscale anahtarının süresi {max(0, int(days))} gün içinde doluyor; dolunca "
            "dışarıdan erişim kesilir. Yönetim panelinde bu bilgisayar için 'Disable key expiry' seçin."
        )

    if not agent_alive(cfg):
        restart_agent()
        actions.append("Ajan yanıt vermiyordu, yeniden başlatıldı")

    return {
        "checked_at": now.isoformat(timespec="seconds"),
        "tailscale": state,
        "warnings": warnings,
        "actions": actions,
    }


def read_status(path: Path, max_age_s: float = 3600) -> dict | None:
    """Ajan tarafı: son bekçi raporunu okur (çok eskiyse yok sayar)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checked = dt.datetime.fromisoformat(data["checked_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > max_age_s:
        return None
    return data


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="remote_agent.watchdog")
    p.add_argument("--config-dir", type=Path, default=default_config_dir())
    args = p.parse_args(argv)

    args.config_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        args.config_dir / "watchdog.log", maxBytes=500_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

    cfg = Config.load(args.config_dir / "config.json")
    report = check(cfg)
    for a in report["actions"]:
        log.warning("ONARILDI: %s", a)
    for w in report["warnings"]:
        log.warning("UYARI: %s", w)
    if not report["actions"] and not report["warnings"]:
        log.info("Her şey yolunda (Tailscale: %s)", report["tailscale"])

    status = args.config_dir / STATUS_FILE
    tmp = status.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, status)


if __name__ == "__main__":
    main()
