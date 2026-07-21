import tkinter as tk
import threading
import os
from PIL import ImageGrab

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    tessdata = os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tessdata")
    if os.path.isdir(tessdata):
        os.environ["TESSDATA_PREFIX"] = tessdata
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False


class ScreenRegionSelector:
    def __init__(self, parent, callback):
        self.parent = parent
        self.callback = callback
        self.start_x = None
        self.start_y = None
        self.rect_id = None

    def select(self):
        if not _OCR_AVAILABLE:
            self.callback(None, "pytesseract не установлен. Установите: pip install pytesseract")
            return

        self.root = tk.Toplevel(self.parent)
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.2)
        self.root.configure(bg="black")
        self.root.attributes("-topmost", True)

        self.canvas = tk.Canvas(self.root, cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self.root.focus_force()

    def _on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)

    def _on_drag(self, event):
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y,
            outline="#e94560", width=3, fill="", stipple="gray25",
        )

    def _on_release(self, event):
        x0, y0 = min(self.start_x, event.x), min(self.start_y, event.y)
        x1, y1 = max(self.start_x, event.x), max(self.start_y, event.y)
        self.root.destroy()

        if x1 - x0 < 20 or y1 - y0 < 20:
            return

        threading.Thread(target=self._ocr, args=(x0, y0, x1, y1), daemon=True).start()

    def _ocr(self, x0, y0, x1, y1):
        try:
            img = ImageGrab.grab(bbox=(x0, y0, x1, y1))
            text = pytesseract.image_to_string(img, lang="rus+eng")
            if text.strip():
                self.callback(text.strip(), None)
            else:
                self.callback(None, "Текст не найден в выбранной области")
        except Exception as e:
            self.callback(None, f"Ошибка OCR: {e}")
