"""Komut satırı girişi.

    python -m remote_agent --set-password     # ilk kurulumda parola belirle
    python -m remote_agent                    # ajanı başlat
    python -m remote_agent --demo             # gerçek ekran yerine test görüntüsü
"""

from __future__ import annotations

import argparse
import getpass
import logging
import socket
import ssl
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiohttp import web

from . import __version__, winutil
from .capture import DemoSource, MssSource
from .config import MIN_PASSWORD_LENGTH, Config, default_config_dir, hash_password
from .input_win import make_backend
from .server import create_app

log = logging.getLogger("remote_agent")


def _setup_logging(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(
        config_dir / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    handlers: list[logging.Handler] = [file_handler]
    if sys.stderr is not None:  # pythonw.exe altında konsol yoktur
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        handlers.append(console)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def _prompt_password() -> str:
    while True:
        pw = getpass.getpass(f"Yeni parola (en az {MIN_PASSWORD_LENGTH} karakter): ")
        if len(pw) < MIN_PASSWORD_LENGTH:
            print("Parola çok kısa.")
            continue
        if pw != getpass.getpass("Parolayı tekrar girin: "):
            print("Parolalar eşleşmiyor.")
            continue
        return pw


def _tls_context(config_dir: Path) -> ssl.SSLContext:
    cert, key = config_dir / "cert.pem", config_dir / "key.pem"
    if not cert.exists() or not key.exists():
        _generate_self_signed(cert, key)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


def _generate_self_signed(cert_path: Path, key_path: Path) -> None:
    try:
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        sys.exit("TLS için 'pip install cryptography' gerekli (veya Tailscale kullanın).")

    host = socket.gethostname()
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("Kendinden imzalı sertifika oluşturuldu: %s", cert_path)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="remote_agent", description="Uzak Masaüstü Ajanı")
    p.add_argument("--config-dir", type=Path, default=default_config_dir())
    p.add_argument("--set-password", action="store_true", help="Parolayı belirle ve çık")
    p.add_argument("--port", type=int, help="Dinlenecek port (varsayılan 8765)")
    p.add_argument("--host", help="Dinlenecek adres (varsayılan 0.0.0.0)")
    p.add_argument("--name", help="Bu bilgisayarın görünen adı")
    p.add_argument("--tls", action="store_true", help="Kendinden imzalı sertifikayla HTTPS")
    p.add_argument("--demo", action="store_true", help="Test görüntüsü; gerçek girdi göndermez")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    cfg_path = args.config_dir / "config.json"
    cfg = Config.load(cfg_path)
    _setup_logging(args.config_dir)

    changed = False
    for attr in ("port", "host", "name"):
        if getattr(args, attr) is not None:
            setattr(cfg, attr, getattr(args, attr))
            changed = True
    if args.tls:
        cfg.tls, changed = True, True

    if args.set_password:
        cfg.password_hash = hash_password(_prompt_password())
        cfg.save(cfg_path)
        print(f"Parola kaydedildi: {cfg_path}")
        return
    if changed:
        cfg.save(cfg_path)
    if not cfg.password_hash:
        sys.exit("Önce parola belirleyin:  python -m remote_agent --set-password")

    winutil.set_dpi_aware()  # ekran yakalamadan ÖNCE çağrılmalı
    if args.demo:
        from .input_win import RecordingBackend

        backend = RecordingBackend()
        source = DemoSource()
        source.pointer_fn = backend.cursor_pos
    else:
        backend = make_backend()
        source = MssSource()

    if cfg.keep_awake:
        winutil.keep_awake(True)

    ssl_ctx = _tls_context(args.config_dir) if cfg.tls else None
    scheme = "https" if ssl_ctx else "http"
    log.info("Uzak Masaüstü Ajanı %s başlıyor: %s://%s:%d  (%s)",
             __version__, scheme, socket.gethostname(), cfg.port, cfg.name)
    try:
        app = create_app(cfg, source, backend, status_path=args.config_dir / "status.json")
        web.run_app(app, host=cfg.host, port=cfg.port,
                    ssl_context=ssl_ctx, print=None, access_log=None)
    finally:
        winutil.keep_awake(False)
