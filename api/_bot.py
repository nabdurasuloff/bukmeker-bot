"""Bot mantiqi (Vercel funksiyalari va GitHub Actions uchun umumiy)."""
import os

import requests

from _prognoz import analyse, report, fetch

REGION = "eu"
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
SIGNAL_LEAGUES = ["soccer_epl", "soccer_spain_la_liga", "soccer_uefa_champs_league"]

MAIN_KB = {"keyboard": [[{"text": "📋 Ligalar"}, {"text": "🔔 Signallar"}],
                        [{"text": "💳 Kredit"}, {"text": "🆔 Mening ID"}],
                        [{"text": "❓ Yordam"}]],
           "resize_keyboard": True}

HELP = (
    "ℹ️ Ko'rsatkichlar:\n\n"
    "• Adolatli ehtimol — bukmeker marjasi olib tashlangan ehtimol (asosan Pinnacle bo'yicha).\n"
    "• Adolatli koeffitsiyent = 1 / ehtimol.\n"
    "• EV — eng yaxshi koeffitsiyentning adolatli narxdan farqi. Musbat bo'lsa, koeffitsiyent \"qimmat\".\n"
    "• Arbitraj — barcha natijalarga tikkanda foyda qoladigan holat.\n"
    "• Kutilgan gollar — koeffitsiyentlardan Puasson modeli orqali hisoblangan.\n\n"
    "Har bir liga so'rovi 1 API kredit, \"Signallar\" 3 kredit sarflaydi.\n\n"
    "⚠️ Bu statistikani o'rganish vositasi. Musbat EV yutishni kafolatlamaydi."
)


def env(name):
    return os.environ.get(name, "").strip()


def tg(method, **data):
    try:
        return requests.post(f"https://api.telegram.org/bot{env('BOT_TOKEN')}/{method}",
                             json=data, timeout=20).json()
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


def analysed(league, limit=None):
    events, _ = fetch(env("ODDS_API_KEY"), league, REGION)
    events = sorted(events, key=lambda e: e.get("commence_time", ""))[:limit]
    res = [a for a in (analyse(e) for e in events) if a]
    res.sort(key=lambda a: a["time"])
    return res


def signals_text(leagues=SIGNAL_LEAGUES):
    found = []
    for lg in leagues:
        for a in analysed(lg):
            if a["arb"] < 1 or any(b["ev"] > MIN_EV for b in a["best"]):
                found.append(f"[{LEAGUES.get(lg, lg)}]\n" + report(a))
    if not found:
        return ""
    return f"🔔 {len(found)} ta signal:\n\n" + "\n\n".join(found)


def credits_left():
    # /sports so'rovi kredit sarflamaydi, lekin qolgan kreditni ko'rsatadi
    try:
        r = requests.get("https://api.the-odds-api.com/v4/sports",
                         params={"apiKey": env("ODDS_API_KEY")}, timeout=15)
        return r.headers.get("x-requests-remaining", "noma'lum")
    except Exception:
        return "noma'lum"


def handle_text(chat, text):
    t = text.strip().lower()
    if t.startswith("/start"):
        send(chat, "Salom! Men koeffitsiyent tahlilchi botman 📊\n"
                   "Ligani tanlang yoki signallarni ko'ring.\n\n"
                   f"Sizning chat ID: {chat}", keyboard=MAIN_KB)
    elif "liga" in t:
        send(chat, "Ligani tanlang:", league_buttons())
    elif "signal" in t:
        send(chat, "⏳ Tekshiryapman...")
        send(chat, signals_text() or
             f"Hozircha signal yo'q (EV > {MIN_EV*100:.0f}% yoki arbitraj topilmadi).")
    elif "kredit" in t:
        send(chat, f"💳 API kreditidan qoldi: {credits_left()}")
    elif "id" in t:
        send(chat, f"🆔 Sizning chat ID: {chat}\n(GitHub'dagi CHAT_ID secret'iga shu raqamni yozing)")
    elif "yordam" in t or t.startswith("/help"):
        send(chat, HELP)
    else:
        send(chat, "Buyruqni tushunmadim. /start ni bosing.", keyboard=MAIN_KB)


def handle_callback(cb):
    chat = cb["message"]["chat"]["id"]
    data = cb.get("data", "")
    tg("answerCallbackQuery", callback_query_id=cb["id"])
    if data.startswith("lg:"):
        lg = data[3:]
        res = analysed(lg, MAX_MATCHES)
        if not res:
            send(chat, "Bu ligada yaqin o'yinlar topilmadi.", league_buttons())
            return
        send(chat, f"{LEAGUES.get(lg, lg)} — {len(res)} ta o'yin\n\n"
             + "\n\n".join(report(a) for a in res), league_buttons())


def handle_update(u):
    try:
        if "message" in u and "text" in u["message"]:
            handle_text(u["message"]["chat"]["id"], u["message"]["text"])
        elif "callback_query" in u:
            handle_callback(u["callback_query"])
    except Exception as e:
        print("Xato:", e)
