"""Ekran yakalama ve değişen bölgeleri JPEG olarak kodlama.

Kablo formatı (little-endian, tek bir WebSocket ikili mesajı):
    başlık : <B type><H width><H height><H count>     type 1 = anahtar kare, 2 = fark
    her döşeme: <H x><H y><H w><H h><I len> + JPEG baytları
İstemci anahtar karede tuvali yeniden boyutlandırır, sonra döşemeleri üstüne çizer.
"""

from __future__ import annotations

import io
import math
import struct
import threading
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

HEADER = struct.Struct("<BHHH")
TILE = struct.Struct("<HHHHI")
KEYFRAME = 1
DELTA = 2


@dataclass(frozen=True)
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int
    primary: bool = False

    def as_dict(self) -> dict:
        label = "Tüm ekranlar" if self.index == 0 else f"Ekran {self.index}"
        if self.primary:
            label += ", ana ekran"
        return {
            "index": self.index,
            "label": f"{label} ({self.width}×{self.height})",
            "width": self.width,
            "height": self.height,
        }


class MssSource:
    """Gerçek ekran (mss). mss nesneleri iş parçacığına özel olduğundan her iş
    parçacığı kendi örneğini tembel olarak oluşturur."""

    def __init__(self) -> None:
        import mss  # noqa: F401  (erken hata vermek için)

        self._local = threading.local()

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss

            sct = self._local.sct = mss.mss()
        return sct

    def monitors(self) -> list[Monitor]:
        return [
            # Windows'ta ana ekranın sol üst köşesi her zaman (0, 0)'dır
            Monitor(i, m["left"], m["top"], m["width"], m["height"],
                    primary=i > 0 and m["left"] == 0 and m["top"] == 0)
            for i, m in enumerate(self._sct().monitors)
        ]

    def grab(self, index: int) -> Image.Image:
        mons = self._sct().monitors
        if not 0 <= index < len(mons):
            index = 1 if len(mons) > 1 else 0
        shot = self._sct().grab(mons[index])
        return Image.frombuffer("RGB", shot.size, shot.bgra, "raw", "BGRX")


class DemoSource:
    """Ekranı olmayan ortamlarda test için yapay görüntü (--demo)."""

    def __init__(self, width: int = 1280, height: int = 720) -> None:
        self._mons = [
            Monitor(0, 0, 0, width * 2, height),
            Monitor(1, 0, 0, width, height, primary=True),
            Monitor(2, width, 0, width, height),
        ]
        self.pointer_fn = lambda: None  # imleci çizmek için (--demo)

    def monitors(self) -> list[Monitor]:
        return list(self._mons)

    def grab(self, index: int) -> Image.Image:
        mon = self._mons[index if 0 <= index < len(self._mons) else 1]
        img = Image.new("RGB", (mon.width, mon.height), (24, 60, 110))
        draw = ImageDraw.Draw(img)
        for x in range(0, mon.width, 80):
            draw.line([(x, 0), (x, mon.height)], fill=(40, 80, 140))
        for y in range(0, mon.height, 80):
            draw.line([(0, y), (mon.width, y)], fill=(40, 80, 140))
        draw.rectangle([40, 40, 520, 140], fill=(250, 250, 250))
        draw.text((60, 60), f"DEMO - Ekran {mon.index}", fill=(0, 0, 0))
        draw.text((60, 90), time.strftime("%H:%M:%S"), fill=(0, 0, 0))
        pos = self.pointer_fn()
        if pos:
            px, py = pos[0] - mon.left, pos[1] - mon.top
            draw.ellipse([px - 6, py - 6, px + 6, py + 6], fill=(255, 200, 0))
        return img


def _jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=False)
    return buf.getvalue()


class FrameEncoder:
    """Önceki kareyle karşılaştırıp yalnızca değişen döşemeleri gönderir."""

    def __init__(self, tile: int = 128, full_ratio: float = 0.6) -> None:
        self.tile = tile
        self.full_ratio = full_ratio
        self._prev: np.ndarray | None = None

    def reset(self) -> None:
        self._prev = None

    def encode(self, img: Image.Image, quality: int) -> bytes | None:
        arr = np.asarray(img)
        h, w = arr.shape[:2]
        prev = self._prev
        self._prev = arr

        if prev is None or prev.shape != arr.shape:
            return self._pack(KEYFRAME, w, h, [(0, 0, w, h)], img, quality)

        rects = self._changed_rects(prev, arr)
        if not rects:
            return None
        changed_area = sum(rw * rh for _, _, rw, rh in rects)
        if changed_area >= self.full_ratio * w * h:
            rects = [(0, 0, w, h)]
        return self._pack(DELTA, w, h, rects, img, quality)

    def _changed_rects(self, prev: np.ndarray, cur: np.ndarray) -> list[tuple[int, int, int, int]]:
        h, w = cur.shape[:2]
        t = self.tile
        rows, cols = math.ceil(h / t), math.ceil(w / t)
        # Satır başına değişen döşemeleri bul, bitişik olanları tek dikdörtgende birleştir
        diff = np.any(prev != cur, axis=2)
        pad_h, pad_w = rows * t - h, cols * t - w
        if pad_h or pad_w:
            diff = np.pad(diff, ((0, pad_h), (0, pad_w)))
        grid = diff.reshape(rows, t, cols, t).any(axis=(1, 3))

        rects = []
        for r in range(rows):
            c = 0
            while c < cols:
                if not grid[r, c]:
                    c += 1
                    continue
                start = c
                while c < cols and grid[r, c]:
                    c += 1
                x, y = start * t, r * t
                rects.append((x, y, min(c * t, w) - x, min(y + t, h) - y))
        return rects

    @staticmethod
    def _pack(kind, w, h, rects, img, quality) -> bytes:
        parts = [HEADER.pack(kind, w, h, len(rects))]
        for x, y, rw, rh in rects:
            region = img if (rw, rh) == img.size else img.crop((x, y, x + rw, y + rh))
            data = _jpeg(region, quality)
            parts.append(TILE.pack(x, y, rw, rh, len(data)))
            parts.append(data)
        return b"".join(parts)


def scale_to_width(img: Image.Image, max_width: int) -> Image.Image:
    if max_width <= 0 or img.width <= max_width:
        return img
    ratio = max_width / img.width
    return img.resize((max_width, max(1, round(img.height * ratio))), Image.BILINEAR)
