"""
Windows WASAPI loopback capture via ctypes (direct vtable calls).
Captures system audio from the default playback device.
"""
from ctypes import (
    c_void_p, c_uint32, c_int64, c_uint16, c_uint64,
    byref, sizeof, WinDLL, CFUNCTYPE, HRESULT,
    create_string_buffer, memmove, Structure,
)
from comtypes import GUID
import comtypes
import queue
import threading
import time


CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
IID_IAudioCaptureClient = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")

AUDCLNT_STREAMFLAGS_LOOPBACK = 0x20000
AUDCLNT_SHAREMODE_SHARED = 0
CLSCTX_ALL = 23


class WAVEFORMATEX(Structure):
    _fields_ = [
        ("wFormatTag", c_uint16),
        ("nChannels", c_uint16),
        ("nSamplesPerSec", c_uint32),
        ("nAvgBytesPerSec", c_uint32),
        ("nBlockAlign", c_uint16),
        ("wBitsPerSample", c_uint16),
        ("cbSize", c_uint16),
    ]


class WasapiLoopbackCapture:
    def __init__(self):
        self._running = False
        self._thread = None
        self._audio_queue = queue.Queue()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def is_running(self):
        return self._running

    def get_audio_chunk(self, timeout=0.1):
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _get_vtable_func(self, obj_ptr, index, func_type):
        vtable = c_void_p.from_address(obj_ptr).value
        fn = c_void_p.from_address(vtable + index * 8).value
        return func_type(fn)

    def _capture_loop(self):
        ole32 = WinDLL("ole32")
        comtypes.CoInitialize()

        try:
            # Create device enumerator
            enum_ptr = c_void_p()
            hr = ole32.CoCreateInstance(
                byref(CLSID_MMDeviceEnumerator), None, 5,
                byref(IID_IMMDeviceEnumerator), byref(enum_ptr),
            )
            if hr != 0:
                raise RuntimeError(f"CoCreateInstance: 0x{hr:08X}")

            # Get default audio endpoint (render/output device)
            GET_DEFAULT = CFUNCTYPE(HRESULT, c_void_p, c_uint32, c_uint32, c_void_p)
            get_default = self._get_vtable_func(enum_ptr.value, 4, GET_DEFAULT)

            dev_ptr = c_void_p()
            hr = get_default(enum_ptr.value, 0, 0, byref(dev_ptr))
            if hr != 0:
                raise RuntimeError(f"GetDefaultAudioEndpoint: 0x{hr:08X}")

            # Activate IAudioClient
            ACTIVATE = CFUNCTYPE(HRESULT, c_void_p, c_void_p, c_uint32, c_void_p, c_void_p)
            activate = self._get_vtable_func(dev_ptr.value, 3, ACTIVATE)

            client_ptr = c_void_p()
            hr = activate(dev_ptr.value, byref(IID_IAudioClient), CLSCTX_ALL, None, byref(client_ptr))
            if hr != 0:
                raise RuntimeError(f"Activate: 0x{hr:08X}")

            # Get mix format
            GET_MIX_FORMAT = CFUNCTYPE(HRESULT, c_void_p, c_void_p)
            get_mix = self._get_vtable_func(client_ptr.value, 8, GET_MIX_FORMAT)

            fmt_ptr = c_void_p()
            hr = get_mix(client_ptr.value, byref(fmt_ptr))
            if hr != 0:
                raise RuntimeError(f"GetMixFormat: 0x{hr:08X}")

            fmt = WAVEFORMATEX.from_address(fmt_ptr.value)
            sr = fmt.nSamplesPerSec
            ba = fmt.nBlockAlign

            # Initialize in loopback mode
            INIT = CFUNCTYPE(HRESULT, c_void_p, c_uint32, c_uint32, c_int64, c_int64, c_void_p, c_void_p)
            init = self._get_vtable_func(client_ptr.value, 3, INIT)

            hns = 200 * 10000
            hr = init(client_ptr.value, AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK,
                      hns, hns, fmt_ptr.value, None)
            if hr != 0:
                raise RuntimeError(f"Initialize: 0x{hr:08X}")

            # Get IAudioCaptureClient
            GET_SERVICE = CFUNCTYPE(HRESULT, c_void_p, c_void_p, c_void_p)
            get_service = self._get_vtable_func(client_ptr.value, 14, GET_SERVICE)

            capture_ptr = c_void_p()
            hr = get_service(client_ptr.value, byref(IID_IAudioCaptureClient), byref(capture_ptr))
            if hr != 0:
                raise RuntimeError(f"GetService: 0x{hr:08X}")

            # Start
            START = CFUNCTYPE(HRESULT, c_void_p)
            start = self._get_vtable_func(client_ptr.value, 10, START)
            hr = start(client_ptr.value)
            if hr != 0:
                raise RuntimeError(f"Start: 0x{hr:08X}")

            # Capture loop
            GET_NEXT = CFUNCTYPE(HRESULT, c_void_p, c_void_p)
            get_next = self._get_vtable_func(capture_ptr.value, 5, GET_NEXT)

            GET_BUF = CFUNCTYPE(HRESULT, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
            get_buf = self._get_vtable_func(capture_ptr.value, 3, GET_BUF)

            REL_BUF = CFUNCTYPE(HRESULT, c_void_p, c_uint32)
            rel_buf = self._get_vtable_func(capture_ptr.value, 4, REL_BUF)

            while self._running:
                ns = c_uint32()
                hr = get_next(capture_ptr.value, byref(ns))
                if hr != 0 or ns.value == 0:
                    time.sleep(0.005)
                    continue

                data = c_void_p()
                frames = c_uint32()
                flags = c_uint32()
                hr = get_buf(capture_ptr.value, byref(data), byref(frames), byref(flags), None, None)
                if hr == 0 and data.value and frames.value > 0:
                    nbytes = frames.value * ba
                    buf = create_string_buffer(nbytes)
                    memmove(buf, data.value, nbytes)
                    self._audio_queue.put({
                        "data": buf.raw,
                        "sample_rate": sr,
                        "channels": fmt.nChannels,
                        "bits_per_sample": fmt.wBitsPerSample,
                        "frames": frames.value,
                        "block_align": ba,
                    })
                rel_buf(capture_ptr.value, frames.value)

            # Stop
            STOP = CFUNCTYPE(HRESULT, c_void_p)
            stop = self._get_vtable_func(client_ptr.value, 11, STOP)
            stop(client_ptr.value)

        except Exception as e:
            print(f"[WASAPI] {e}")
        finally:
            comtypes.CoUninitialize()
            self._running = False


def is_wasapi_available():
    try:
        comtypes.CoInitialize()
        ole32 = WinDLL("ole32")
        ptr = c_void_p()
        hr = ole32.CoCreateInstance(
            byref(CLSID_MMDeviceEnumerator), None, 5,
            byref(IID_IMMDeviceEnumerator), byref(ptr),
        )
        comtypes.CoUninitialize()
        return hr == 0
    except Exception:
        return False
