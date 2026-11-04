"""Vercel funksiyasi: Telegram webhook. Manzil: https://<loyiha>.vercel.app/api/telegram"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _bot import env, handle_update  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _reply(self, code, text):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(text.encode())

    def do_POST(self):
        if self.headers.get("X-Telegram-Bot-Api-Secret-Token") != env("TG_SECRET"):
            return self._reply(403, "forbidden")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            update = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            update = {}
        handle_update(update)
        self._reply(200, "ok")

    def do_GET(self):
        self._reply(200, "Bot ishlayapti ✅")
