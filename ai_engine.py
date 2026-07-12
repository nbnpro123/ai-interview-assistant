import queue
import threading
from openai import OpenAI


class AIEngine:
    def __init__(self, config):
        self.config = config
        self.client = None
        self.conversation_history = []
        self.event_queue = queue.Queue()
        self._init_client()

    def _init_client(self):
        key = self.config.get("api_key", "")
        if key:
            self.client = OpenAI(
                api_key=key,
                base_url=self.config.get("base_url", "https://api.deepseek.com"),
            )
        else:
            self.client = None

    def update_config(self, config):
        self.config = config
        self._init_client()

    def send_message(self, text):
        if not self.client:
            self.event_queue.put({"type": "error", "message": "API ключ не настроен. Укажите ключ DeepSeek в настройках."})
            self.event_queue.put({"type": "answer", "question": text, "text": "⚠ API ключ не настроен. Откройте настройки (⚙) и укажите ваш ключ DeepSeek."})
            return

        def query():
            try:
                system_prompt = self.config.get(
                    "system_prompt",
                    "Ты — опытный ассистент, помогающий проходить собеседования.",
                )
                messages = [{"role": "system", "content": system_prompt}]

                for msg in self.conversation_history[-12:]:
                    messages.append(msg)

                messages.append({"role": "user", "content": text})

                response = self.client.chat.completions.create(
                    model=self.config.get("model", "deepseek-chat"),
                    messages=messages,
                    temperature=self.config.get("temperature", 0.7),
                    max_tokens=self.config.get("max_tokens", 1000),
                )

                answer = response.choices[0].message.content

                self.conversation_history.append({"role": "user", "content": text})
                self.conversation_history.append({"role": "assistant", "content": answer})

                self.event_queue.put({"type": "answer", "question": text, "text": answer})

            except Exception as e:
                self.event_queue.put({"type": "error", "message": f"Ошибка API: {e}"})

        threading.Thread(target=query, daemon=True).start()

    def clear_history(self):
        self.conversation_history.clear()
