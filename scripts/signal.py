"""GitHub Actions: har 6 soatda signallarni CHAT_ID ga yuboradi."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from _bot import env, send, signals_text  # noqa: E402

chat = env("CHAT_ID")
if not chat:
    sys.exit("CHAT_ID secret'i kiritilmagan (botga /start yozsangiz, ID ni ko'rsatadi)")
text = signals_text()
if text:
    send(chat, text)
    print("Signal yuborildi")
else:
    print("Signal yo'q")
