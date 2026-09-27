"""Windows'a özgü yardımcılar: DPI farkındalığı, uyku engelleme, pano.

Windows dışında hepsi zararsız şekilde hiçbir şey yapmaz (pano bellekte tutulur).
"""

from __future__ import annotations

import sys
import time

_fake_clipboard = ""


def set_dpi_aware() -> None:
    """Ekran yakalama ve imleç koordinatlarının fiziksel piksel olması için şart."""
    if sys.platform != "win32":
        return
    import ctypes

    try:  # Windows 10 1703+: Per-Monitor v2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


def keep_awake(enable: bool) -> None:
    """Bilgisayarın uykuya geçmesini ve ekranın kapanmasını engeller."""
    if sys.platform != "win32":
        return
    import ctypes

    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2
    flags = ES_CONTINUOUS
    if enable:
        flags |= ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def input_desktop_locked() -> bool:
    """Kilit ekranı veya UAC güvenli masaüstü aktifse True.

    Kullanıcı oturumundaki bir işlem güvenli masaüstünü açamaz; OpenInputDesktop
    başarısız olursa ekran kilitli demektir.
    """
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    desk = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not desk:
        return True
    user32.CloseDesktop(ctypes.c_void_p(desk))
    return False


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
    _u32.OpenClipboard.argtypes = (wintypes.HWND,)
    _u32.GetClipboardData.argtypes = (wintypes.UINT,)
    _u32.GetClipboardData.restype = wintypes.HANDLE
    _u32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    _u32.SetClipboardData.restype = wintypes.HANDLE
    _k32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    _k32.GlobalAlloc.restype = wintypes.HGLOBAL
    _k32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    _k32.GlobalLock.restype = ctypes.c_void_p
    _k32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    _k32.GlobalFree.argtypes = (wintypes.HGLOBAL,)

    def _open_clipboard() -> bool:
        for _ in range(10):  # başka uygulama panoyu kısa süre kilitlemiş olabilir
            if _u32.OpenClipboard(None):
                return True
            time.sleep(0.05)
        return False

    def get_clipboard() -> str:
        if not _open_clipboard():
            return ""
        try:
            handle = _u32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = _k32.GlobalLock(handle)
            try:
                return ctypes.wstring_at(ptr) if ptr else ""
            finally:
                _k32.GlobalUnlock(handle)
        finally:
            _u32.CloseClipboard()

    def set_clipboard(text: str) -> bool:
        data = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(data)
        if not _open_clipboard():
            return False
        try:
            _u32.EmptyClipboard()
            handle = _k32.GlobalAlloc(GMEM_MOVEABLE, size)
            if not handle:
                return False
            ptr = _k32.GlobalLock(handle)
            ctypes.memmove(ptr, data, size)
            _k32.GlobalUnlock(handle)
            if not _u32.SetClipboardData(CF_UNICODETEXT, handle):
                _k32.GlobalFree(handle)
                return False
            return True  # başarılıysa belleğin sahibi artık sistem
        finally:
            _u32.CloseClipboard()

else:

    def get_clipboard() -> str:
        return _fake_clipboard

    def set_clipboard(text: str) -> bool:
        global _fake_clipboard
        _fake_clipboard = text
        return True
