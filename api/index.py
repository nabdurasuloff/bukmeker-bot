"""Vercel kirish nuqtasi (bitta funksiya).

POST /api/telegram           — Telegram webhook
GET  /api/setup?key=SECRET   — webhook'ni bir marta ulash
GET  /                       — holat tekshiruvi
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))
from _bot import env, handle_update, tg  # noqa: E402


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
        u = urlparse(self.path)
        key = parse_qs(u.query).get("key", [""])[0]
        if not key:
            return self._reply(200, "Bot ishlayapti ✅\nWebhook ulash uchun manzil oxiriga ?key=TG_SECRET qo'shing.")
        if not env("TG_SECRET") or key != env("TG_SECRET"):
            return self._reply(403, "❌ key noto'g'ri. Manzil oxiriga ?key=TG_SECRET qiymatini yozing.")
        if not env("BOT_TOKEN") or not env("ODDS_API_KEY"):
            return self._reply(500, "❌ Vercel'da BOT_TOKEN yoki ODDS_API_KEY kiritilmagan.")
        host = self.headers.get("x-forwarded-host") or self.headers.get("host")
        url = f"https://{host}/api/telegram"
        res = tg("setWebhook", url=url, secret_token=env("TG_SECRET"),
                 allowed_updates=["message", "callback_query"])
        if res.get("ok"):
            return self._reply(200, f"✅ Webhook ulandi: {url}\nEndi Telegramda botga /start yozing.")
        return self._reply(500, "❌ Telegram javobi: " + json.dumps(res, ensure_ascii=False))
