"""Fare ve klavye girdisi: Windows'ta SendInput, diğer sistemlerde kayıt tutan sahte arka uç.

Tarayıcıdan gelen tuşlar KeyboardEvent.code adlarıyla ("KeyA", "ArrowLeft" ...)
iletilir ve burada Windows sanal tuş kodlarına (VK) çevrilir. Yazdırılabilir
karakterler ise klavye düzeninden bağımsız olsun diye Unicode olarak yazılır.
"""

from __future__ import annotations

import sys

# --- KeyboardEvent.code -> Windows VK -------------------------------------------------
VK_CODES: dict[str, int] = {
    "Backspace": 0x08, "Tab": 0x09, "Enter": 0x0D, "NumpadEnter": 0x0D,
    "ShiftLeft": 0xA0, "ShiftRight": 0xA1, "ControlLeft": 0xA2, "ControlRight": 0xA3,
    "AltLeft": 0xA4, "AltRight": 0xA5, "MetaLeft": 0x5B, "MetaRight": 0x5C,
    "ContextMenu": 0x5D, "Pause": 0x13, "CapsLock": 0x14, "Escape": 0x1B, "Space": 0x20,
    "PageUp": 0x21, "PageDown": 0x22, "End": 0x23, "Home": 0x24,
    "ArrowLeft": 0x25, "ArrowUp": 0x26, "ArrowRight": 0x27, "ArrowDown": 0x28,
    "PrintScreen": 0x2C, "Insert": 0x2D, "Delete": 0x2E,
    "NumpadMultiply": 0x6A, "NumpadAdd": 0x6B, "NumpadSubtract": 0x6D,
    "NumpadDecimal": 0x6E, "NumpadDivide": 0x6F, "NumLock": 0x90, "ScrollLock": 0x91,
    "Semicolon": 0xBA, "Equal": 0xBB, "Comma": 0xBC, "Minus": 0xBD, "Period": 0xBE,
    "Slash": 0xBF, "Backquote": 0xC0, "BracketLeft": 0xDB, "Backslash": 0xDC,
    "BracketRight": 0xDD, "Quote": 0xDE, "IntlBackslash": 0xE2,
    "AudioVolumeMute": 0xAD, "AudioVolumeDown": 0xAE, "AudioVolumeUp": 0xAF,
}
VK_CODES.update({f"Key{chr(c)}": c for c in range(ord("A"), ord("Z") + 1)})
VK_CODES.update({f"Digit{d}": 0x30 + d for d in range(10)})
VK_CODES.update({f"Numpad{d}": 0x60 + d for d in range(10)})
VK_CODES.update({f"F{n}": 0x6F + n for n in range(1, 25)})

# Bu tuşlar KEYEVENTF_EXTENDEDKEY bayrağı ister
EXTENDED_VK = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E,
    0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5,
}

BUTTONS = ("left", "right", "middle")


class InputBackend:
    """Ortak arayüz. Basılı tuş/düğmeleri izler ki bağlantı koparsa bırakılabilsin."""

    def __init__(self) -> None:
        self.pressed_keys: set[str] = set()
        self.pressed_buttons: set[str] = set()

    # Alt sınıflar bunları uygular
    def _move(self, x: int, y: int) -> None: ...
    def _button(self, button: str, down: bool) -> None: ...
    def _wheel(self, dy: int, dx: int) -> None: ...
    def _key(self, vk: int, down: bool) -> None: ...
    def _text(self, text: str) -> None: ...
    def cursor_pos(self) -> tuple[int, int] | None:
        return None

    # --- Genel API ---
    def move(self, x: int, y: int) -> None:
        self._move(x, y)

    def button(self, button: str, down: bool) -> None:
        if button not in BUTTONS:
            return
        (self.pressed_buttons.add if down else self.pressed_buttons.discard)(button)
        self._button(button, down)

    def wheel(self, dy: int, dx: int = 0) -> None:
        self._wheel(dy, dx)

    def key(self, code: str, down: bool) -> bool:
        vk = VK_CODES.get(code)
        if vk is None:
            return False
        (self.pressed_keys.add if down else self.pressed_keys.discard)(code)
        self._key(vk, down)
        return True

    def combo(self, codes: list[str]) -> None:
        """Örn. ["ControlLeft", "ShiftLeft", "Escape"]: sırayla bas, tersten bırak."""
        valid = [c for c in codes if c in VK_CODES]
        for c in valid:
            self.key(c, True)
        for c in reversed(valid):
            self.key(c, False)

    def text(self, text: str) -> None:
        if text:
            self._text(text[:10_000])

    def release_all(self) -> None:
        for code in list(self.pressed_keys):
            self.key(code, False)
        for b in list(self.pressed_buttons):
            self.button(b, False)


class RecordingBackend(InputBackend):
    """Windows dışı / test: olayları listeye kaydeder."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple] = []
        self.pos = (0, 0)

    def _move(self, x, y):
        self.pos = (x, y)
        self.events.append(("move", x, y))

    def _button(self, button, down):
        self.events.append(("button", button, down))

    def _wheel(self, dy, dx):
        self.events.append(("wheel", dy, dx))

    def _key(self, vk, down):
        self.events.append(("key", vk, down))

    def _text(self, text):
        self.events.append(("text", text))

    def cursor_pos(self):
        return self.pos


def make_backend() -> InputBackend:
    if sys.platform == "win32":
        return WindowsBackend()
    return RecordingBackend()


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 1, 2, 4, 8
    MOUSEEVENTF = {
        ("left", True): 0x0002, ("left", False): 0x0004,
        ("right", True): 0x0008, ("right", False): 0x0010,
        ("middle", True): 0x0020, ("middle", False): 0x0040,
    }
    MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
    MAPVK_VK_TO_VSC = 0
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)

    def _send(*inputs: INPUT) -> None:
        arr = (INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))

    def _mouse(flags: int, data: int = 0) -> INPUT:
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(0, 0, ctypes.c_uint32(data).value, flags, 0, 0)
        return inp

    def _kbd(vk: int, scan: int, flags: int) -> INPUT:
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        return inp

    class WindowsBackend(InputBackend):
        def _move(self, x, y):
            user32.SetCursorPos(int(x), int(y))

        def _button(self, button, down):
            _send(_mouse(MOUSEEVENTF[(button, down)]))

        def _wheel(self, dy, dx):
            if dy:
                _send(_mouse(MOUSEEVENTF_WHEEL, int(dy)))
            if dx:
                _send(_mouse(MOUSEEVENTF_HWHEEL, int(dx)))

        def _key(self, vk, down):
            scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
            flags = 0 if down else KEYEVENTF_KEYUP
            if vk in EXTENDED_VK:
                flags |= KEYEVENTF_EXTENDEDKEY
            _send(_kbd(vk, scan, flags))

        def _text(self, text):
            inputs = []
            for ch in text:
                if ch == "\n":
                    inputs += [_kbd(0x0D, 0, 0), _kbd(0x0D, 0, KEYEVENTF_KEYUP)]
                    continue
                if ch == "\r":
                    continue
                encoded = ch.encode("utf-16-le")
                for i in range(0, len(encoded), 2):  # vekil çiftleri (emoji vb.)
                    unit = int.from_bytes(encoded[i:i + 2], "little")
                    inputs.append(_kbd(0, unit, KEYEVENTF_UNICODE))
                    inputs.append(_kbd(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            if inputs:
                _send(*inputs)

        def cursor_pos(self):
            pt = wintypes.POINT()
            if user32.GetCursorPos(ctypes.byref(pt)):
                return pt.x, pt.y
            return None
