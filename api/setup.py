"""Vercel funksiyasi: Telegram webhook'ni bir marta ulash.

Brauzerda oching:  https://<loyiha>.vercel.app/api/setup?key=<TG_SECRET>
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))
from _bot import env, tg  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        if not env("TG_SECRET") or q.get("key", [""])[0] != env("TG_SECRET"):
            msg, code = "❌ key noto'g'ri. Manzil oxiriga ?key=TG_SECRET qiymatini yozing.", 403
        elif not env("BOT_TOKEN") or not env("ODDS_API_KEY"):
            msg, code = "❌ Vercel'da BOT_TOKEN yoki ODDS_API_KEY kiritilmagan.", 500
        else:
            host = self.headers.get("x-forwarded-host") or self.headers.get("host")
            url = f"https://{host}/api/telegram"
            res = tg("setWebhook", url=url, secret_token=env("TG_SECRET"),
                     allowed_updates=["message", "callback_query"])
            if res.get("ok"):
                msg, code = f"✅ Webhook ulandi: {url}\nEndi Telegramda botga /start yozing.", 200
            else:
                msg, code = "❌ Telegram javobi: " + json.dumps(res, ensure_ascii=False), 500
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(msg.encode())
