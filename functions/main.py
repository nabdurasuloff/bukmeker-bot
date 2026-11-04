"""
Firebase Cloud Functions: Telegram koeffitsiyent tahlilchi bot (o'rganish uchun).

  telegram  — Telegram webhook (har bir xabar shu funksiyaga keladi)
  avto      — har 6 soatda obunachilarga signal yuboradi

Maxfiy qiymatlar functions/.env faylidan olinadi (uni GitHub Actions yaratadi):
  BOT_TOKEN, ODDS_API_KEY, TG_SECRET
"""
import json
import os
import time

import requests
from firebase_admin import firestore, initialize_app
from firebase_functions import https_fn, options, scheduler_fn

from prognoz import analyse, report, fetch

initialize_app()
options.set_global_options(region="europe-west1", memory=options.MemoryOption.MB_256,
                           max_instances=3)

REGION = "eu"
CACHE_MIN = 30
MIN_EV = 0.02
MAX_MATCHES = 8

LEAGUES = {
    "soccer_epl": "🏴 Angliya Premer-ligasi",
    "soccer_spain_la_liga": "🇪🇸 La Liga",
    "soccer_italy_serie_a": "🇮🇹 Seriya A",
    "soccer_germany_bundesliga": "🇩🇪 Bundesliga",
    "soccer_france_ligue_one": "🇫🇷 Liga 1",
    "soccer_uefa_champs_league": "🏆 Chempionlar ligasi",
}
AUTO_LEAGUES = ["soccer_epl", "soccer_spain_la_liga", "soccer_uefa_champs_league"]

MAIN_KB = {"keyboard": [[{"text": "📋 Ligalar"}, {"text": "🔔 Signallar"}],
                        [{"text": "⏱ Avto signal"}, {"text": "💳 Kredit"}],
                        [{"text": "❓ Yordam"}]],
           "resize_keyboard": True}

HELP = (
    "ℹ️ Ko'rsatkichlar:\n\n"
    "• Adolatli ehtimol — bukmeker marjasi olib tashlangan ehtimol (asosan Pinnacle bo'yicha).\n"
    "• Adolatli koeffitsiyent = 1 / ehtimol.\n"
    "• EV — eng yaxshi koeffitsiyentning adolatli narxdan farqi. Musbat bo'lsa, koeffitsiyent \"qimmat\".\n"
    "• Arbitraj — barcha natijalarga tikkanda foyda qoladigan holat.\n"
    "• Kutilgan gollar — koeffitsiyentlardan Puasson modeli orqali hisoblangan.\n\n"
    "⚠️ Bu statistikani o'rganish vositasi. Musbat EV yutishni kafolatlamaydi."
)

_db = None


def db():
    global _db
    if _db is None:
        _db = firestore.client()
    return _db


def env(name):
    return os.environ.get(name, "")


# ---------- Telegram ----------

def tg(method, **data):
    try:
        return requests.post(f"https://api.telegram.org/bot{env('BOT_TOKEN')}/{method}",
                             json=data, timeout=30).json()
    except Exception as e:
        print("Telegram xatosi:", e)
        return {}


def send(chat, text, buttons=None, keyboard=None):
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) > 3900:
            parts.append(cur)
            cur = ""
        cur += block + "\n\n"
    parts.append(cur)
    for i, p in enumerate(parts):
        extra = {}
        if i == len(parts) - 1:
            if buttons:
                extra["reply_markup"] = {"inline_keyboard": buttons}
            elif keyboard:
                extra["reply_markup"] = keyboard
        tg("sendMessage", chat_id=chat, text=p.strip() or "—", **extra)


def league_buttons():
    return [[{"text": n, "callback_data": f"lg:{k}"}] for k, n in LEAGUES.items()]


# ---------- Ma'lumot (Firestore keshi bilan) ----------

def get_events(league):
    ref = db().collection("kesh").document(league)
    snap = ref.get()
    if snap.exists:
        d = snap.to_dict()
        if time.time() - d.get("ts", 0) < CACHE_MIN * 60:
            return json.loads(d.get("data", "[]"))
    events, left = fetch(env("ODDS_API_KEY"), league, REGION)
    ref.set({"ts": time.time(), "data": json.dumps(events)})
    if left is not None:
        db().collection("holat").document("api").set({"kredit": left, "ts": time.time()})
    return events


def analysed(league):
    res = [a for a in (analyse(e) for e in get_events(league)) if a]
    res.sort(key=lambda a: a["time"])
    return res


def is_signal(a):
    return a["arb"] < 1 or any(b["ev"] > MIN_EV for b in a["best"])


def signals_text(leagues):
    found = []
    for lg in leagues:
        for a in analysed(lg):
            if is_signal(a):
                found.append(f"[{LEAGUES.get(lg, lg)}]\n" + report(a))
    if not found:
        return ""
    return f"🔔 {len(found)} ta signal:\n\n" + "\n\n".join(found)


# ---------- Buyruqlar ----------

def handle_text(chat, text):
    t = text.strip().lower()
    subs = db().collection("obunachilar")
    if t.startswith("/start"):
        send(chat, "Salom! Men koeffitsiyent tahlilchi botman 📊\n"
                   "Ligani tanlang yoki signallarni ko'ring.", keyboard=MAIN_KB)
    elif "ligalar" in t:
        send(chat, "Ligani tanlang:", league_buttons())
    elif "signal" in t and "avto" not in t:
        send(chat, "⏳ Tekshiryapman...")
        send(chat, signals_text(list(LEAGUES)) or
             f"Hozircha signal yo'q (EV > {MIN_EV*100:.0f}% yoki arbitraj topilmadi).")
    elif "avto" in t:
        ref = subs.document(str(chat))
        if ref.get().exists:
            ref.delete()
            send(chat, "⏱ Avto signal o'chirildi.")
        else:
            ref.set({"ts": time.time()})
            send(chat, "⏱ Avto signal yoqildi: har 6 soatda signallar keladi.")
    elif "kredit" in t:
        snap = db().collection("holat").document("api").get()
        left = snap.to_dict().get("kredit") if snap.exists else "noma'lum"
        send(chat, f"💳 API kreditidan qoldi: {left}")
    elif "yordam" in t:
        send(chat, HELP)
    else:
        send(chat, "Buyruqni tushunmadim. /start ni bosing.")


def handle_callback(cb):
    chat = cb["message"]["chat"]["id"]
    data = cb.get("data", "")
    tg("answerCallbackQuery", callback_query_id=cb["id"])
    if data.startswith("lg:"):
        lg = data[3:]
        send(chat, f"⏳ {LEAGUES.get(lg, lg)} yuklanmoqda...")
        res = analysed(lg)[:MAX_MATCHES]
        if not res:
            send(chat, "Bu ligada yaqin o'yinlar topilmadi.")
            return
        send(chat, f"{LEAGUES.get(lg, lg)} — {len(res)} ta o'yin\n\n"
             + "\n\n".join(report(a) for a in res), league_buttons())


# ---------- Cloud Functions ----------

@https_fn.on_request(timeout_sec=120)
def telegram(req: https_fn.Request) -> https_fn.Response:
    # Faqat Telegramdan kelgan so'rovlarni qabul qilamiz
    if req.headers.get("X-Telegram-Bot-Api-Secret-Token") != env("TG_SECRET"):
        return https_fn.Response("forbidden", status=403)
    u = req.get_json(silent=True) or {}
    try:
        if "message" in u and "text" in u["message"]:
            handle_text(u["message"]["chat"]["id"], u["message"]["text"])
        elif "callback_query" in u:
            handle_callback(u["callback_query"])
    except Exception as e:
        print("Xato:", e)
    return https_fn.Response("ok")


@scheduler_fn.on_schedule(schedule="every 6 hours",
                          timezone=scheduler_fn.Timezone("Asia/Tashkent"),
                          timeout_sec=300)
def avto(event: scheduler_fn.ScheduledEvent) -> None:
    subs = [d.id for d in db().collection("obunachilar").stream()]
    if not subs:
        return
    text = signals_text(AUTO_LEAGUES)
    if not text:
        return
    for chat in subs:
        send(int(chat), text)
