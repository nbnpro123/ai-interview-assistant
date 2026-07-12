import numpy as np
import queue
import threading
import time
import speech_recognition as sr
import sounddevice as sd

from wasapi_capture import WasapiLoopbackCapture, is_wasapi_available


def _to_mono_float32(data, channels):
    """Convert raw PCM bytes to mono float32 normalized to [-1, 1]."""
    samples = np.frombuffer(data, dtype=np.float32).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples.astype(np.float32)


class AudioEngine:
    BACKEND_AUTO = "auto"
    BACKEND_WASAPI = "wasapi"
    BACKEND_SOUNDDEVICE = "sounddevice"

    def __init__(self, config):
        self.config = config
        self._running = False
        self._thread = None
        self._recognizer = sr.Recognizer()
        self._backend = self.BACKEND_AUTO
        self._wasapi_capture = None
        self._sd_device_index = None
        self.event_queue = queue.Queue()
        self._manual_recording = False
        self._manual_buffer = []
        self._manual_lock = threading.Lock()

    def get_devices(self):
        devices = sd.query_devices()
        result = []
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                api = sd.query_hostapis(dev["hostapi"])
                is_loopback = "WASAPI" in api["name"] and not any(
                    x in dev["name"].lower()
                    for x in ["microphone", "mic", "microf"]
                )
                result.append({
                    "index": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "api": api["name"],
                    "is_loopback": is_loopback,
                    "backend": "sounddevice",
                })
        result.insert(0, {
            "index": -1,
            "name": "[WASAPI Loopback] Системное аудио (рекомендуется)",
            "channels": 2,
            "api": "WASAPI",
            "is_loopback": True,
            "backend": "wasapi",
        })
        return result

    def start(self, device_index=None):
        if self._running:
            return
        self._running = True

        if device_index == -1 or (device_index is None and is_wasapi_available()):
            self._backend = self.BACKEND_WASAPI
            self._wasapi_capture = WasapiLoopbackCapture()
            self._thread = threading.Thread(target=self._wasapi_loop, daemon=True)
            self._thread.start()
            self.event_queue.put({"type": "status", "message": "Прослушивание: WASAPI Loopback (системное аудио)"})
        else:
            self._backend = self.BACKEND_SOUNDDEVICE
            self._sd_device_index = device_index
            self._thread = threading.Thread(target=self._sd_loop, daemon=True)
            self._thread.start()
            if device_index is not None:
                dev = sd.query_devices(device_index)
                self.event_queue.put({"type": "status", "message": f"Прослушивание: {dev['name']}"})
            else:
                self.event_queue.put({"type": "status", "message": "Прослушивание запущено"})

    def stop(self):
        self._running = False
        if self._wasapi_capture:
            self._wasapi_capture.stop()
            self._wasapi_capture = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.event_queue.put({"type": "status", "message": "Остановлено"})

    def start_manual_recording(self):
        with self._manual_lock:
            self._manual_buffer = []
            self._manual_recording = True
        self.event_queue.put({"type": "status", "message": "⏺ Ручная запись..."})

    def stop_manual_recording(self):
        with self._manual_lock:
            self._manual_recording = False
            buffer = self._manual_buffer
            self._manual_buffer = []
        if buffer:
            sr = 48000 if self._backend == self.BACKEND_WASAPI else 16000
            self._process_audio_buffer(buffer, sr, source="manual")
            self.event_queue.put({"type": "status", "message": "⏹ Запись обработана"})
        else:
            self.event_queue.put({"type": "status", "message": "Запись пуста"})

    @property
    def is_running(self):
        return self._running

    def _wasapi_loop(self):
        self._wasapi_capture.start()
        block_frames = 1440
        sr = 48000
        silence_sec = self.config.get("silence_timeout_seconds", 2.5)
        silence_timeout = int(silence_sec * sr / block_frames)
        min_phrase_frames = int(0.7 * sr / block_frames)

        speech_buffer = []
        is_speaking = False
        silence_count = 0

        while self._running:
            chunk = self._wasapi_capture.get_audio_chunk(timeout=0.1)
            if chunk is None:
                continue

            mono = _to_mono_float32(chunk["data"], chunk["channels"])
            if len(mono) == 0:
                continue

            energy = float(np.sqrt(np.mean(mono ** 2))) * 1000
            self.event_queue.put({"type": "level", "value": energy})

            with self._manual_lock:
                if self._manual_recording:
                    self._manual_buffer.append(mono.copy())

            if energy > 30:
                if not is_speaking:
                    is_speaking = True
                speech_buffer.append(mono)
                silence_count = 0
            else:
                if is_speaking:
                    speech_buffer.append(mono)
                    silence_count += 1
                    if silence_count > silence_timeout:
                        if len(speech_buffer) >= min_phrase_frames:
                            self._process_audio_buffer(speech_buffer, sr)
                        speech_buffer.clear()
                        is_speaking = False
                        silence_count = 0

    def _sd_loop(self):
        sample_rate = 16000
        blocksize = int(sample_rate * 0.03)
        silence_sec = self.config.get("silence_timeout_seconds", 2.5)
        silence_timeout = int(silence_sec * sample_rate / blocksize)
        min_phrase_frames = int(0.7 * sample_rate / blocksize)
        audio_queue = queue.Queue()
        speech_buffer = []
        is_speaking = False
        silence_count = 0

        def callback(indata, frames, time_info, status):
            if status:
                self.event_queue.put({"type": "debug", "message": str(status)})
            audio_queue.put(indata.copy())

        try:
            with sd.InputStream(
                device=self._sd_device_index,
                samplerate=sample_rate, channels=1,
                blocksize=blocksize, callback=callback,
            ):
                while self._running:
                    try:
                        data = audio_queue.get(timeout=0.1)
                        energy = float(np.sqrt(np.mean(data ** 2)) * 1000)

                        self.event_queue.put({"type": "level", "value": energy})

                        with self._manual_lock:
                            if self._manual_recording:
                                self._manual_buffer.append(data.copy())

                        if energy > 30:
                            if not is_speaking:
                                is_speaking = True
                            speech_buffer.append(data)
                            silence_count = 0
                        else:
                            if is_speaking:
                                speech_buffer.append(data)
                                silence_count += 1
                                if silence_count > silence_timeout:
                                    if len(speech_buffer) >= min_phrase_frames:
                                        self._process_audio_buffer(speech_buffer, sample_rate)
                                    speech_buffer.clear()
                                    is_speaking = False
                                    silence_count = 0
                    except queue.Empty:
                        pass
        except Exception as e:
            self.event_queue.put({"type": "error", "message": f"Ошибка: {e}"})
            self._running = False

    def _process_audio_buffer(self, buffer, sample_rate, source="vad"):
        if not buffer:
            return
        audio_data = np.concatenate(buffer)
        max_val = np.max(np.abs(audio_data))
        if max_val > 0:
            audio_data = audio_data / max_val
        audio_int16 = (audio_data * 32767).astype(np.int16)
        audio = sr.AudioData(audio_int16.tobytes(), sample_rate, 2)

        def transcribe():
            try:
                lang = self.config.get("language", "ru-RU")
                text = self._recognizer.recognize_google(audio, language=lang)
                if text and text.strip():
                    self.event_queue.put({"type": "transcription", "text": text.strip(), "source": source})
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                self.event_queue.put({"type": "error", "message": f"STT ошибка: {e}"})

        threading.Thread(target=transcribe, daemon=True).start()
