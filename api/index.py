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
        sec = env("TG_SECRET")
        if not sec:
            return self._reply(500, "❌ Serverda TG_SECRET topilmadi. Vercel → Settings → Environment Variables'da "
                                    "TG_SECRET borligini tekshiring va Redeploy qiling.")
        if key.strip() != sec:
            return self._reply(403, f"❌ key mos emas. Serverdagi TG_SECRET {len(sec)} belgidan iborat, "
                                    f"'{sec[0]}' bilan boshlanadi; siz yozgan key {len(key.strip())} belgi.")
        if not env("BOT_TOKEN") or not env("ODDS_API_KEY"):
            return self._reply(500, "❌ Vercel'da BOT_TOKEN yoki ODDS_API_KEY kiritilmagan.")
        host = self.headers.get("x-forwarded-host") or self.headers.get("host")
        url = f"https://{host}/api/telegram"
        res = tg("setWebhook", url=url, secret_token=env("TG_SECRET"),
                 allowed_updates=["message", "callback_query"])
        if res.get("ok"):
            return self._reply(200, f"✅ Webhook ulandi: {url}\nEndi Telegramda botga /start yozing.")
        return self._reply(500, "❌ Telegram javobi: " + json.dumps(res, ensure_ascii=False))
