import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from audio_engine import AudioEngine
from ai_engine import AIEngine
from screen_capture import ScreenRegionSelector, _OCR_AVAILABLE

try:
    import pystray
    from PIL import Image, ImageDraw
    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False

from hotkey import start_hotkey as _start_hotkey, stop_hotkey as _stop_hotkey


COLORS = {
    "bg": "#1a1a2e",
    "surface": "#16213e",
    "surface2": "#0f3460",
    "accent": "#e94560",
    "accent2": "#533483",
    "text": "#eaeaea",
    "text_secondary": "#a0a0b0",
    "success": "#4ecca3",
    "error": "#e94560",
    "warning": "#f5a623",
}

FONTS = {
    "header": ("Segoe UI", 16, "bold"),
    "subheader": ("Segoe UI", 11, "bold"),
    "body": ("Segoe UI", 10),
    "small": ("Segoe UI", 9),
    "mono": ("Consolas", 10),
}


class SettingsDialog:
    def __init__(self, parent, config, devices, on_save):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Настройки")
        self.dialog.geometry("500x550")
        self.dialog.resizable(False, False)
        self.dialog.configure(bg=COLORS["bg"])
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.config = config.copy()
        self.on_save = on_save

        main_frame = tk.Frame(self.dialog, bg=COLORS["bg"], padx=20, pady=20)
        main_frame.pack(fill="both", expand=True)

        row = 0

        tk.Label(main_frame, text="API Ключ DeepSeek", fg=COLORS["text"], bg=COLORS["bg"],
                 font=FONTS["subheader"], anchor="w").grid(row=row, column=0, sticky="w", pady=(0, 5))
        row += 1
        self.api_key_entry = tk.Entry(main_frame, width=50, show="*",
                                       bg=COLORS["surface"], fg=COLORS["text"],
                                       insertbackground=COLORS["text"],
                                       relief="flat", font=FONTS["body"])
        self.api_key_entry.insert(0, config.get("api_key", ""))
        self.api_key_entry.grid(row=row, column=0, pady=(0, 15), ipady=4, sticky="ew")
        row += 1

        tk.Label(main_frame, text="Base URL", fg=COLORS["text"], bg=COLORS["bg"],
                 font=FONTS["subheader"], anchor="w").grid(row=row, column=0, sticky="w", pady=(0, 5))
        row += 1
        self.base_url_entry = tk.Entry(main_frame, width=50,
                                        bg=COLORS["surface"], fg=COLORS["text"],
                                        insertbackground=COLORS["text"],
                                        relief="flat", font=FONTS["body"])
        self.base_url_entry.insert(0, config.get("base_url", "https://api.deepseek.com"))
        self.base_url_entry.grid(row=row, column=0, pady=(0, 15), ipady=4, sticky="ew")
        row += 1

        tk.Label(main_frame, text="Модель", fg=COLORS["text"], bg=COLORS["bg"],
                 font=FONTS["subheader"], anchor="w").grid(row=row, column=0, sticky="w", pady=(0, 5))
        row += 1
        self.model_combo = ttk.Combobox(main_frame, values=[
            "deepseek-chat", "deepseek-reasoner", "gpt-4o-mini", "gpt-4o"
        ], state="normal", width=47)
        self.model_combo.set(config.get("model", "deepseek-chat"))
        self.model_combo.grid(row=row, column=0, pady=(0, 15), ipady=2, sticky="ew")
        row += 1

        tk.Label(main_frame, text="Устройство захвата аудио", fg=COLORS["text"], bg=COLORS["bg"],
                 font=FONTS["subheader"], anchor="w").grid(row=row, column=0, sticky="w", pady=(0, 5))
        row += 1
        self.device_combo = ttk.Combobox(main_frame, values=[
            f"{d['index']}: {d['name']} ({d['api']})"
            for d in devices
        ], state="readonly", width=47)
        if devices:
            current = config.get("device_index")
            found = False
            for d in devices:
                if d["index"] == current:
                    self.device_combo.set(f"{d['index']}: {d['name']} ({d['api']})")
                    found = True
                    break
            if not found:
                first = devices[0]
                self.device_combo.set(f"{first['index']}: {first['name']} ({first['api']})")
        self.device_combo.grid(row=row, column=0, pady=(0, 15), ipady=2, sticky="ew")
        row += 1

        tk.Label(main_frame, text="Системный промпт", fg=COLORS["text"], bg=COLORS["bg"],
                 font=FONTS["subheader"], anchor="w").grid(row=row, column=0, sticky="w", pady=(0, 5))
        row += 1
        self.prompt_text = tk.Text(main_frame, width=50, height=5,
                                    bg=COLORS["surface"], fg=COLORS["text"],
                                    insertbackground=COLORS["text"],
                                    relief="flat", font=FONTS["small"],
                                    wrap="word")
        self.prompt_text.insert("1.0", config.get("system_prompt", ""))
        self.prompt_text.grid(row=row, column=0, pady=(0, 15), sticky="ew")
        row += 1

        btn_frame = tk.Frame(main_frame, bg=COLORS["bg"])
        btn_frame.grid(row=row, column=0, pady=(5, 0))
        row += 1

        tk.Button(btn_frame, text="Сохранить", command=self._save,
                  bg=COLORS["success"], fg=COLORS["bg"],
                  font=FONTS["body"], relief="flat", padx=20, pady=4,
                  cursor="hand2").pack(side="left", padx=5)
        tk.Button(btn_frame, text="Отмена", command=self.dialog.destroy,
                  bg=COLORS["surface2"], fg=COLORS["text"],
                  font=FONTS["body"], relief="flat", padx=20, pady=4,
                  cursor="hand2").pack(side="left", padx=5)

        main_frame.columnconfigure(0, weight=1)

    def _save(self):
        try:
            device_str = self.device_combo.get()
            device_index = None
            if device_str and ":" in device_str:
                device_index = int(device_str.split(":")[0])
        except (ValueError, IndexError):
            device_index = self.config.get("device_index")

        self.config["api_key"] = self.api_key_entry.get().strip()
        self.config["base_url"] = self.base_url_entry.get().strip()
        self.config["model"] = self.model_combo.get().strip()
        self.config["device_index"] = device_index
        self.config["system_prompt"] = self.prompt_text.get("1.0", "end-1c").strip()
        self.on_save(self.config)
        self.dialog.destroy()


def _create_tray_icon(app):
    if not _HAS_TRAY:
        return None
    img = Image.new("RGB", (16, 16), (233, 69, 96))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 13, 13], fill=(233, 69, 96))
    menu = pystray.Menu(
        pystray.MenuItem("Показать", lambda: app._show_window()),
        pystray.MenuItem("Выход", lambda: app._quit_app()),
    )
    return pystray.Icon("ai_interview", img, "AI Ассистент", menu)


class InterviewAssistantUI:
    def __init__(self, config, save_config_callback):
        self.config = config
        self._save_config = save_config_callback
        self._question_count = 0
        self._muted = config.get("muted", False)
        self._tray_icon = None
        self._last_source = "vad"

        self.root = tk.Tk()
        self.root.title("AI Ассистент собеседования")
        self.root.configure(bg=COLORS["bg"])

        geometry = config.get("window_geometry", "900x600+200+100")
        self.root.geometry(geometry)
        self.root.minsize(700, 500)

        self.root.bind("<Control-h>", lambda e: self._toggle_hidden())
        self.root.bind("<Control-H>", lambda e: self._toggle_hidden())

        self.audio_engine = AudioEngine(config)
        self.ai_engine = AIEngine(config)

        self._build_ui()
        self._poll_events()
        self._register_hotkeys()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg=COLORS["surface"], height=50)
        header.pack(fill="x")
        header.pack_propagate(False)

        self.status_dot = tk.Canvas(header, width=14, height=14,
                                     bg=COLORS["surface"], highlightthickness=0)
        self.status_dot.pack(side="left", padx=(15, 5), pady=18)
        self._dot = self.status_dot.create_oval(2, 2, 12, 12, fill=COLORS["text_secondary"], outline="")

        tk.Label(header, text="AI Ассистент собеседования",
                 fg=COLORS["text"], bg=COLORS["surface"],
                 font=FONTS["header"]).pack(side="left", padx=5)

        self.status_label = tk.Label(header, text="Готов к работе",
                                      fg=COLORS["text_secondary"], bg=COLORS["surface"],
                                      font=FONTS["small"])
        self.status_label.pack(side="left", padx=15)

        tk.Button(header, text="⚙", command=self._open_settings,
                  bg=COLORS["surface"], fg=COLORS["text"],
                  font=("Segoe UI", 14), relief="flat",
                  cursor="hand2", bd=0,
                  activebackground=COLORS["surface2"],
                  activeforeground=COLORS["accent"]).pack(side="right", padx=10)

        # Main content
        content = tk.Frame(self.root, bg=COLORS["bg"])
        content.pack(fill="both", expand=True, padx=12, pady=8)

        # Question panel
        q_frame = tk.LabelFrame(content, text="  Распознанный вопрос  ",
                                 fg=COLORS["accent"], bg=COLORS["bg"],
                                 font=FONTS["subheader"],
                                 relief="flat", bd=0)
        q_frame.pack(fill="both", expand=True, pady=(0, 6))

        q_inner = tk.Frame(q_frame, bg=COLORS["surface"],
                           highlightbackground=COLORS["surface2"],
                           highlightthickness=1)
        q_inner.pack(fill="both", expand=True, padx=0, pady=4)

        self.question_text = tk.Text(q_inner, height=3, wrap="word",
                                      bg=COLORS["surface"], fg=COLORS["text"],
                                      font=FONTS["body"], relief="flat",
                                      insertbackground=COLORS["text"])
        self.question_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.question_text.insert("1.0", "")
        self.question_text.config(state="disabled")

        # Answer panel — история ответов
        a_frame = tk.LabelFrame(content, text="  История ответов  ",
                                 fg=COLORS["success"], bg=COLORS["bg"],
                                 font=FONTS["subheader"],
                                 relief="flat", bd=0)
        a_frame.pack(fill="both", expand=True, pady=(6, 0))

        a_inner = tk.Frame(a_frame, bg=COLORS["surface"],
                           highlightbackground=COLORS["surface2"],
                           highlightthickness=1)
        a_inner.pack(fill="both", expand=True, padx=0, pady=4)

        self.answer_text = scrolledtext.ScrolledText(a_inner, wrap="word",
                                    bg=COLORS["surface"], fg=COLORS["text"],
                                    font=FONTS["body"], relief="flat",
                                    insertbackground=COLORS["text"])
        self.answer_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.answer_text.insert("1.0", "Нажмите «Начать» и задайте вопрос...")
        self.answer_text.config(state="disabled")
        self.answer_text.tag_config("vad_tag", foreground=COLORS["accent"])
        self.answer_text.tag_config("manual_tag", foreground=COLORS["success"])
        self.answer_text.tag_config("typed_tag", foreground=COLORS["warning"])

        # Manual text input
        manual_frame = tk.Frame(content, bg=COLORS["bg"])
        manual_frame.pack(fill="x", pady=(4, 0))

        self.manual_entry = tk.Entry(manual_frame,
                                      bg=COLORS["surface"], fg=COLORS["text"],
                                      insertbackground=COLORS["text"],
                                      font=FONTS["body"], relief="flat")
        self.manual_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
        self.manual_entry.bind("<Return>", lambda e: self._send_manual())

        tk.Button(manual_frame, text="📤 Отправить",
                  command=self._send_manual,
                  bg=COLORS["accent2"], fg="white",
                  font=FONTS["body"], relief="flat",
                  padx=12, pady=4, cursor="hand2").pack(side="right")

        # Control bar
        controls = tk.Frame(content, bg=COLORS["bg"], height=50)
        controls.pack(fill="x", pady=(6, 0))
        controls.pack_propagate(False)

        self.toggle_btn = tk.Button(controls, text="🎤 Начать прослушивание",
                                     command=self._toggle_listening,
                                     bg=COLORS["accent"], fg="white",
                                     font=FONTS["body"], relief="flat",
                                     padx=20, pady=6, cursor="hand2",
                                     activebackground=COLORS["accent2"])
        self.toggle_btn.pack(side="left", padx=(0, 8))

        self.manual_btn = tk.Button(controls, text="⏺ Захват",
                                     command=self._toggle_manual_recording,
                                     bg=COLORS["surface2"], fg=COLORS["text"],
                                     font=FONTS["body"], relief="flat",
                                     padx=10, pady=6, cursor="hand2")
        self.manual_btn.pack(side="left", padx=8)

        tk.Button(controls, text="📷 Экран (Ctrl+Alt+S)",
                  command=self._capture_screen,
                  bg=COLORS["surface2"], fg=COLORS["text"],
                  font=FONTS["body"], relief="flat",
                  padx=10, pady=6, cursor="hand2").pack(side="left", padx=8)

        tk.Button(controls, text="🗑 Очистить", command=self._clear,
                  bg=COLORS["surface2"], fg=COLORS["text"],
                  font=FONTS["body"], relief="flat",
                  padx=15, pady=6, cursor="hand2").pack(side="left", padx=8)

        self.mute_btn = tk.Button(controls, text="🔊 Звук",
                                   command=self._toggle_mute,
                                   bg=COLORS["surface2"], fg=COLORS["text"],
                                   font=FONTS["body"], relief="flat",
                                   padx=10, pady=6, cursor="hand2")
        self.mute_btn.pack(side="left", padx=8)
        self._update_mute_btn()

        if _HAS_TRAY:
            tk.Button(controls, text="🕶 Скрыть (Ctrl+H)",
                      command=self._toggle_hidden,
                      bg=COLORS["surface2"], fg=COLORS["text"],
                      font=FONTS["body"], relief="flat",
                      padx=10, pady=6, cursor="hand2").pack(side="left", padx=8)

        self.count_label = tk.Label(controls, text="Вопросов: 0",
                                     fg=COLORS["text_secondary"], bg=COLORS["bg"],
                                     font=FONTS["small"])
        self.count_label.pack(side="right", padx=5)

    def _toggle_listening(self):
        if self.audio_engine.is_running:
            self.audio_engine.stop()
            self.toggle_btn.config(text="🎤 Начать прослушивание", bg=COLORS["accent"])
            self.status_dot.itemconfig(self._dot, fill=COLORS["text_secondary"])
            self.manual_btn.config(text="⏺ Захват", bg=COLORS["surface2"])
        else:
            self.audio_engine.start(self.config.get("device_index"))
            self.toggle_btn.config(text="⏹ Остановить", bg=COLORS["error"])
            self.status_dot.itemconfig(self._dot, fill=COLORS["success"])

    def _toggle_manual_recording(self):
        if not self.audio_engine.is_running:
            self._set_status("⚠ Сначала запустите прослушивание")
            return
        engine = self.audio_engine
        if hasattr(engine, '_manual_recording') and engine._manual_recording:
            engine.stop_manual_recording()
            self.manual_btn.config(text="⏺ Захват", bg=COLORS["surface2"])
        else:
            engine.start_manual_recording()
            self.manual_btn.config(text="⏹ Стоп", bg=COLORS["error"])

    def _capture_screen(self):
        if not _OCR_AVAILABLE:
            messagebox.showwarning("OCR недоступен", "Установите pytesseract:\npip install pytesseract\n\nИ Tesseract-OCR: https://github.com/UB-Mannheim/tesseract")
            return

        def on_text(text, error):
            if error:
                self.root.after(0, lambda: self._set_status(f"⚠ {error}"))
                return
            self.root.after(0, lambda: self._on_ocr_text(text))

        self._set_status("Выделите область на экране...")
        self.root.iconify()
        self.root.after(500, lambda: self._show_selector(on_text))

    def _show_selector(self, callback):
        selector = ScreenRegionSelector(self.root, callback)
        selector.select()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_ocr_text(self, text):
        self._last_source = "typed"
        self.question_text.config(state="normal")
        self.question_text.delete("1.0", "end")
        self.question_text.insert("1.0", text)
        self.question_text.config(state="disabled")
        self._set_status(f"Распознано с экрана: {text[:40]}...")
        self.ai_engine.send_message(text)

    def _send_manual(self):
        text = self.manual_entry.get().strip()
        if not text:
            return
        self._last_source = "typed"
        self.manual_entry.delete(0, "end")
        self.question_text.config(state="normal")
        self.question_text.delete("1.0", "end")
        self.question_text.insert("1.0", text)
        self.question_text.config(state="disabled")
        self._set_status(f"Отправлено: {text[:40]}...")
        self.ai_engine.send_message(text)

    def _open_settings(self):
        devices = self.audio_engine.get_devices()
        SettingsDialog(self.root, self.config, devices, self._on_settings_save)

    def _on_settings_save(self, new_config):
        was_running = self.audio_engine.is_running
        if was_running:
            self.audio_engine.stop()
        self.config.update(new_config)
        self._save_config(self.config)
        self.ai_engine.update_config(self.config)
        self._set_status("Настройки сохранены")
        if was_running:
            self.audio_engine.start(self.config.get("device_index"))
            self.status_dot.itemconfig(self._dot, fill=COLORS["success"])

    def _clear(self):
        self.question_text.config(state="normal")
        self.question_text.delete("1.0", "end")
        self.question_text.config(state="disabled")
        self.answer_text.config(state="normal")
        self.answer_text.delete("1.0", "end")
        self.answer_text.insert("1.0", "История очищена. Нажмите «Начать» и задайте вопрос...")
        self.answer_text.config(state="disabled")
        self.ai_engine.clear_history()
        self._question_count = 0
        self.count_label.config(text="Вопросов: 0")

    def _toggle_mute(self):
        self._muted = not self._muted
        self.config["muted"] = self._muted
        self._update_mute_btn()
        self._set_status("🔇 Звук выключен" if self._muted else "🔊 Звук включён")

    def _update_mute_btn(self):
        if self._muted:
            self.mute_btn.config(text="🔇 Без звука", bg=COLORS["error"])
        else:
            self.mute_btn.config(text="🔊 Звук", bg=COLORS["surface2"])

    def _toggle_hidden(self):
        if self.root.state() in ("withdrawn", "iconic"):
            self._show_window()
        else:
            self._hide_window()

    def _hide_window(self):
        if not _HAS_TRAY:
            self.root.iconify()
            return
        self.root.withdraw()
        if self._tray_icon is None:
            self._tray_icon = _create_tray_icon(self)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None

    def _quit_app(self):
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.root.after(0, self._on_close)

    def _set_status(self, msg):
        self.status_label.config(text=msg)

    def _poll_events(self):
        for engine in (self.audio_engine, self.ai_engine):
            try:
                while True:
                    event = engine.event_queue.get_nowait()
                    self._handle_event(event)
            except queue.Empty:
                pass
        self.root.after(100, self._poll_events)

    def _handle_event(self, event):
        etype = event.get("type")
        if etype == "transcription":
            text = event["text"]
            self._last_source = event.get("source", "vad")
            self.question_text.config(state="normal")
            self.question_text.delete("1.0", "end")
            self.question_text.insert("1.0", text)
            self.question_text.config(state="disabled")
            self._set_status(f"Распознано: {text[:40]}...")
            self.ai_engine.send_message(text)

        elif etype == "answer":
            question = event.get("question", "")
            text = event.get("text", "")
            self._question_count += 1
            self.count_label.config(text=f"Вопросов: {self._question_count}")
            source = getattr(self, '_last_source', 'vad')

            src_labels = {
                "vad": "🎧 Распознано",
                "manual": "⏺ Захвачено",
                "typed": "✏️ Набрано",
            }
            src_tag = source + "_tag"
            if src_tag not in ("vad_tag", "manual_tag", "typed_tag"):
                src_tag = None
            src_label = src_labels.get(source, "Вопрос")

            self.answer_text.config(state="normal")
            if self._question_count == 1:
                self.answer_text.delete("1.0", "end")
            else:
                self.answer_text.insert("end", "\n\n" + "─" * 40 + "\n\n")
            if src_tag:
                self.answer_text.insert("end", f"[{src_label}]\n", src_tag)
            else:
                self.answer_text.insert("end", f"[{src_label}]\n")
            self.answer_text.insert("end", f"❓ Вопрос:\n{question}\n\n")
            self.answer_text.insert("end", f"💬 Ответ:\n{text}")
            self.answer_text.see("end")
            self.answer_text.config(state="disabled")
            self._set_status(f"Ответ получен на: {question[:40]}...")
            if not self._muted:
                self.root.bell()

        elif etype == "status":
            self._set_status(event["message"])

        elif etype == "error":
            self._set_status(f"⚠ {event['message']}")

        elif etype == "level":
            val = event.get("value", 0)
            if val > 1:
                self._set_status(f"🔊 Уровень: {val:.0f}")
            elif val > 0:
                self._set_status(f"🔈 Уровень: {val:.1f}")

        elif etype == "debug":
            pass

    def _on_close(self):
        _stop_hotkey()
        if self.audio_engine.is_running:
            self.audio_engine.stop()
        self.config["window_geometry"] = self.root.geometry()
        self._save_config(self.config)
        self.root.destroy()

    def _register_hotkeys(self):
        _start_hotkey(self._capture_screen)

    def run(self):
        self.root.mainloop()
