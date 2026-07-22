import ctypes
from ctypes import wintypes
import threading

user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_ALT = 0x0001
VK_S = 0x53

_msg = wintypes.MSG()
_running = False


def start_hotkey(callback, hotkey_id=1):
    global _running
    _running = True

    def _listener():
        if not user32.RegisterHotKey(None, hotkey_id, MOD_CONTROL | MOD_ALT, VK_S):
            return
        try:
            while _running:
                if user32.PeekMessageW(ctypes.byref(_msg), None, 0, 0, 1):
                    if _msg.message == WM_HOTKEY and _msg.wParam == hotkey_id:
                        callback()
        finally:
            user32.UnregisterHotKey(None, hotkey_id)

    t = threading.Thread(target=_listener, daemon=True)
    t.start()
    return t


def stop_hotkey():
    global _running
    _running = False
